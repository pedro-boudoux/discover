"""
Run the offline eval (algorithm 2.0, Phase 0, task 3).

Runs every ground-truth seed through the live recommendation pipeline, scores the
results with eval/metrics.py, and prints a single four-metric table. Optionally
writes the result to a baseline JSON for cross-run comparison.

    python -m eval.run_eval --model current
    python -m eval.run_eval --model current --out eval/baselines/sparse_tag_baseline.json

The model is identified only by label (the pipeline always uses whatever vectors
are currently stored). Capture a baseline before a representation change, then
re-run after and diff the committed JSON.
"""
import argparse
import json
import os

from app.config import DEFAULT_K, MMR_LAMBDA
from app.db import get_cursor
from eval import ground_truth, metrics

# Imported lazily-safe: the router function is a plain callable. We pass k/lambda
# explicitly because its signature uses FastAPI Query() defaults, which are NOT
# the scalar defaults when the function is called directly.
from app.routers.recommendations import get_recommendations


def _embeddings_for(track_ids: list[str]) -> dict[str, list]:
    if not track_ids:
        return {}
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT track_id, embedding FROM songs WHERE track_id = ANY(%s) AND embedding IS NOT NULL",
            (track_ids,),
        )
        return {r["track_id"]: [float(x) for x in r["embedding"]] for r in cursor.fetchall()}


def evaluate(model: str, k: int = DEFAULT_K, gt_path: str = ground_truth.GROUND_TRUTH_PATH) -> dict:
    gt = ground_truth.load(gt_path)
    seeds = gt["seeds"]

    per_seed = {"recall": [], "mrr": [], "ild": [], "med_listeners": []}
    scored = 0

    for entry in seeds:
        seed_id = entry["seed_track_id"]
        target = set(entry["targets"])
        try:
            resp = get_recommendations(seed_id, k=k, lambda_param=MMR_LAMBDA, exclude=[])
        except Exception:
            continue

        recs = resp.recommendations if hasattr(resp, "recommendations") else resp["recommendations"]
        rec_ids = [r.track_id for r in recs]
        listeners = [r.listeners for r in recs]
        emb_map = _embeddings_for(rec_ids)
        vectors = [emb_map.get(tid) for tid in rec_ids]

        per_seed["recall"].append(metrics.recall_at_k(rec_ids, target, k))
        per_seed["mrr"].append(metrics.mrr(rec_ids, target))
        per_seed["ild"].append(metrics.intra_list_distance(vectors))
        per_seed["med_listeners"].append(metrics.median_listeners(listeners))
        scored += 1

    def avg(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {
        "model": model,
        "k": k,
        "seeds_scored": scored,
        "seeds_total": len(seeds),
        f"recall_at_{k}": avg(per_seed["recall"]),
        "mrr": avg(per_seed["mrr"]),
        "intra_list_distance": avg(per_seed["ild"]),
        # median of the per-seed median listener counts — the typical underground depth
        "median_listeners": avg(per_seed["med_listeners"]),
    }


def _print_table(result: dict) -> None:
    print()
    print(f"  model:           {result['model']}")
    print(f"  seeds scored:    {result['seeds_scored']} / {result['seeds_total']}")
    print("  " + "-" * 38)
    k = result["k"]
    print(f"  recall@{k:<10} {result[f'recall_at_{k}']:.4f}")
    print(f"  mrr             {result['mrr']:.4f}")
    print(f"  intra_list_dist {result['intra_list_distance']:.4f}")
    print(f"  median_listeners{result['median_listeners']:>14,.0f}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the recommendation eval.")
    parser.add_argument("--model", default="current", help="label for this run (e.g. current, stage_a)")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--ground-truth", default=ground_truth.GROUND_TRUTH_PATH)
    parser.add_argument("--out", default=None, help="optional path to write the result JSON")
    args = parser.parse_args()

    if not os.path.exists(args.ground_truth):
        print(f"Ground truth not found at {args.ground_truth}. Run: python -m eval.ground_truth --sample 300")
        return 1

    result = evaluate(args.model, k=args.k, gt_path=args.ground_truth)
    _print_table(result)

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote result to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())