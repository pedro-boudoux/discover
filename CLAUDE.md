# Underground Music Discovery — Backend

## What we're building

A backend that powers a graph-based music discovery app. The user drops a seed
song onto a graph, the backend finds sonically similar underground tracks via
vector similarity search, and the graph expands based on user feedback. The user
can also export branches of the graph as linear or tree-shaped playlists.

"Underground" = low listener count from Last.fm (proxy for popularity, since
Spotify's popularity/audio-feature APIs are deprecated). The default underground
ceiling is `listeners < 500_000` (`MAX_LISTENERS`).

> See `ARCHITECTURE.md` for Mermaid diagrams of every flow described below.

---

## Stack

| Layer | Tool | Why |
|---|---|---|
| API | FastAPI (Python) | Async, fast, pairs well with ML tooling |
| Song search | Last.fm `track.search` + local Postgres cache | No login, and we reuse songs we've already embedded |
| Tags + listener counts | Last.fm API | Tag-based embeddings, listener counts, similar tracks — all free |
| Album covers | Deezer + iTunes | Last.fm stopped serving real artist/album images |
| Embeddings | numpy | Normalize + blend Last.fm tag vectors |
| Vector DB | Postgres + pgvector | ANN search + graph state in one DB |
| Hosting | Render | Managed Postgres with pgvector, easy FastAPI deploys |

### Dependencies (`requirements.txt`)

```
fastapi
uvicorn
requests
numpy
scikit-learn
psycopg2-binary
pgvector
python-dotenv
pydantic
```

> **No Spotify.** `spotipy` and all `SPOTIFY_*` config/env vars have been
> removed. Spotify is not called anywhere in the codebase. (The only remaining
> trace is the `spotify_id → track_id` rename migrations in `db.py`, kept to
> migrate older deployed databases.)

---

## Why not Spotify?

Spotify deprecated `GET /audio-features` and `GET /recommendations` in November
2024 (apps created after that date get a 403). Without audio features there was
no compelling reason to keep Spotify in the loop at all, so song search was moved
to **Last.fm `track.search`** merged with our **local Postgres cache**, and
album art is fetched from **Deezer/iTunes**. Everything embeddings-related comes
from Last.fm.

---

## Track identity

There is no Spotify ID. Every track is keyed by a **`track_id`**: a 20-char SHA1
of `"{artist}|||{track}"`, lowercased and stripped.

```python
# app/services/embeddings.py
def make_track_id(artist: str, track: str) -> str:
    key = f"{artist.strip().lower()}|||{track.strip().lower()}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]
```

This means the same song always resolves to the same id regardless of where it
entered the system (search, seed bootstrap, recommendation top-up, playlist
expansion), which is what lets all those paths dedupe against each other.

---

## How it works

### The core pipeline

1. User searches → `GET /songs/search` (local DB + Last.fm in parallel, covers from Deezer/iTunes)
2. User drops a song on the graph → `POST /graph/seed`
3. Backend builds the seed's tag embedding (cache-aware), runs ANN search, then
   bootstraps + recursively expands the candidate pool from Last.fm `getSimilar`
4. Candidates become graph nodes/edges
5. User accepts or rejects nodes → `POST /feedback`
   - **Accept** → song is promoted to a seed and recommendations rerun from it
   - **Reject** → stored as a negative; future queries from the parent seed steer away
6. User exports a branch → `POST /playlists/linear` or `POST /playlists/tree`

### Embedding strategy (blended tags)

A single embedding blends **three** Last.fm tag sources into one
`{tag: count}` dict (`lastfm.blend_tags`), so the vector reflects both the
specific track and its broader stylistic context:

| Source | Last.fm method | Weight |
|---|---|---|
| Track tags (dominant) | `track.getTopTags` | `1.0` |
| Artist tags (context) | `artist.getTopTags` | `0.3` |
| Similar-artist tags | `artist.getSimilar` → `artist.getTopTags` each | `0.1 × match` |

Then (`embeddings.py`):

1. Clean each tag: `tag.lower().strip()` — collapses "Hip-Hop"/"hip hop"/"hip-hop".
2. Upsert tags into `tag_vocab`; each tag's row `id` is its slot in the vector.
3. Normalize by dividing by the max blended count (top tag → `1.0`).
4. Write into a dense `float[EMBEDDING_DIM]` (300) aligned to the vocab.

Tags whose vocab `id >= EMBEDDING_DIM` are dropped (the vector is capped at 300
dimensions). Artists with overlapping high-count tags score high on cosine
similarity; low-count tags contribute little, which is the right behaviour.

### ANN search + diversity (recommendations)

`GET /recommendations/{track_id}` does more than raw nearest-neighbor:

1. **Steering** — `query = base − α·Σ(rejected neighbors)`, then normalized (`α = 0.3`).
2. **Over-fetch** — pull `k × MMR_POOL_MULTIPLIER` (3×) candidates with `listeners < 500k`.
3. **Per-artist cap** — at most `MMR_MAX_PER_ARTIST` (2) per artist in the pool; the rest go to an overflow list.
4. **MMR re-rank** — `score = λ·relevance − (1−λ)·redundancy` (`λ = 0.7`) for relevance/diversity balance.
5. **Backfill** — if still short of `k`, refill from the capped-out overflow (most similar first).
6. **Top-up** — if *still* short, fetch the seed's Last.fm `getSimilar`, embed+store, and score against the steered query. If the seed has no `getSimilar` at all, fall back to its **similar artists' top tracks** (same cold-start escape hatch as seeding).

### Vector steering on reject

When a song is rejected, future ANN queries from its parent seed are nudged away:

```
query_vector = seed_embedding − α · Σ rejected_embeddings   # then L2-normalized
```

`α` = `STEERING_ALPHA` = `0.3`. Rejections are scoped to a seed via
`graph_edges` (only rejected *neighbors of that seed* steer it) — see
`steering.get_rejected_embeddings`.

### Seed bootstrapping & recursive expansion

A fresh DB is sparse, so `POST /graph/seed` doesn't rely on ANN alone:

- Pull the seed's `getSimilar` (limit 25), embed+store each, score against the seed.
- If nothing lands under the underground cap, **escalate** the listener cap:
  `500k → 1M → 2M → 10M` until at least one candidate is added.
- Then **recursively expand**: take the top 3 candidates, pull *their* `getSimilar`
  (limit 10) and embed those too — this thickens the local neighborhood so BFS
  playlists don't drift into unrelated music once direct edges run out.
- **Cold-start fallback**: if the pool is *still* empty (instrumental / soundtrack /
  very obscure seeds often have no `track.getSimilar` at all), mine the seed's
  **similar artists' top tracks** (`artist.getSimilar` → `artist.getTopTracks`) and
  embed those instead. Without this such a seed yields an empty graph — nothing to
  embed means `/recommendations` returns nothing and the UI shows a lone node.
- Merge ANN + getSimilar + expansion, keep the top `DEFAULT_K` (10) by similarity, write edges.

### Playlists

Two strategies over a seed's graph neighborhood (`app/routers/playlists.py`):

- **Linear** (`/playlists/linear`) — flat list of the seed's neighbors. `niche=true`
  walks listener thresholds `100 → 1k → 10k → 100k → 500k`, collecting the most
  underground matches first, then sorts ascending by listener count.
- **Tree** (`/playlists/tree`) — BFS from the seed (`max_depth`, default 3),
  taking 2 neighbors per node and growing the allowed set with each visited
  node's own edges. Produces a branching path through the graph.

Both call `embed_missing` first to fill any null embeddings in the neighborhood.

---

## Data sources

### Last.fm (tags + listeners + similar — the core)

`app/services/lastfm.py`. Auth: just an API key (free, no OAuth). Methods used:

- **`track.search`** — song search (returns name, artist, listeners, image).
- **`track.getInfo`** — listener count (underground filter) + basic track tags.
- **`track.getTopTags`** — track-level tags (dominant embedding source).
- **`artist.getTopTags`** — artist-level tags with confidence counts (context).
- **`artist.getSimilar`** — similar artists (kept if `match > 0.5`) to widen tag context.
- **`track.getSimilar`** — candidate bootstrapping and recommendation top-up.

The `count` field on tags is how many users applied that tag — it acts as a
confidence score and drives normalization.

### Album covers (Deezer → iTunes → Deezer artist photo)

`app/services/covers.py`. Last.fm serves a single broken placeholder
(`2a96cbd8b46e442fc41c2b86b821562f`) for every artist, so covers are resolved by:

1. Deezer track search → `album.cover_xl` (best for underground)
2. iTunes search → `artworkUrl100` upscaled to `600x600`
3. Deezer artist photo (`picture_xl`) as a last resort

`is_broken_image()` detects the Last.fm placeholder so we never persist it, and
upserts use `COALESCE` so a known-good cover is never regressed to NULL.

---

## Database schema

Schema lives in **`migrations/init.sql`** and is also created/migrated at startup
by **`app/db.py:init_db()`** (idempotent — `CREATE TABLE IF NOT EXISTS` plus
best-effort `ALTER`/index migrations, each in its own transaction).

> The live schema is `migrations/init.sql` + `init_db()`. Connections use
> `RealDictCursor` and `pgvector.psycopg2.register_vector`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- for fast substring search on the cache

CREATE TABLE songs (
    id         SERIAL PRIMARY KEY,
    track_id   TEXT UNIQUE NOT NULL,   -- sha1(artist|||track)[:20]
    name       TEXT NOT NULL,
    artist     TEXT NOT NULL,
    listeners  INTEGER,
    image      TEXT,                   -- resolved album/artist cover URL
    embedding  vector(300),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON songs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON songs USING gin (name gin_trgm_ops);
CREATE INDEX ON songs USING gin (artist gin_trgm_ops);

CREATE TABLE tag_vocab (
    id  SERIAL PRIMARY KEY,   -- id == this tag's dimension in the embedding
    tag TEXT UNIQUE NOT NULL
);

CREATE TABLE graph_nodes (
    id         SERIAL PRIMARY KEY,
    track_id   TEXT UNIQUE REFERENCES songs(track_id),
    is_seed    BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE graph_edges (
    id         SERIAL PRIMARY KEY,
    source_id  TEXT REFERENCES songs(track_id),
    target_id  TEXT REFERENCES songs(track_id),
    similarity FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX ON graph_edges(source_id, target_id);

CREATE TABLE feedback (
    id         SERIAL PRIMARY KEY,
    track_id   TEXT REFERENCES songs(track_id),
    action     TEXT CHECK (action IN ('accept', 'reject')),
    created_at TIMESTAMPTZ DEFAULT now()
);
```

A row in `songs` can exist with `embedding IS NULL` — that's a search-cache hit
we haven't embedded yet. Embedding happens lazily on seed / features / playlist.

---

## API Endpoints

### Songs

```
GET /songs/search?q={query}
```
Local DB ILIKE search + Last.fm `track.search` run in parallel, merged
(Last.fm first, then local-only), capped at 15. Reuses cached covers; only calls
Deezer/iTunes for tracks missing a real one. Upserts everything into `songs`.

```
GET /songs/{track_id}/status
```
Lightweight check: `{ exists, cached }` — `cached` means an embedding is already
stored. The frontend uses this to warn about "cold" seeds (multiple Last.fm calls, slow).

```
GET /songs/{track_id}/features
```
Returns `{ track_id, name, artist, listeners, tags, embedding }`. Cache hit →
returns stored embedding + tags. Cache miss → runs the full blended-tag embedding
pipeline, stores it, and returns it.

```
POST /songs/backfill-covers?limit={n}
```
Maintenance: re-resolve covers for songs with NULL or placeholder images.

### Graph

```
GET /graph
```
All nodes + edges for the frontend.
```json
{
  "nodes": [{ "track_id": "abc", "name": "...", "artist": "...", "is_seed": true, "listeners": 18200 }],
  "edges": [{ "source": "abc", "target": "xyz", "similarity": 0.91 }]
}
```

```
POST /graph/tags
body: { "track_ids": ["abc", ...], "top_n": 15 }
```
Dominant tags across a graph (issue #2) — "which genres are taking over". Sums
each song's normalized tag weights (from its embedding) across the node set and
returns the top `top_n` as `{ tag, weight, count, share }` (`share` ≈ % of the
vibe). Pass `track_ids` to scope to the UI's current node set; omit it to
aggregate the whole persisted graph (nodes + both ends of every edge). Empty set
or no embeddings → `{ "tags": [] }`.

```
POST /graph/seed
body: { "track_id": "abc123" }
```
Builds the embedding (cache-aware), promotes to seed node, runs ANN + getSimilar
bootstrap + recursive expansion, writes edges. Returns `{ track_id, name, artist }`.
**The track must already exist in `songs` (i.e. have been returned by search) — 404 otherwise.**

### Recommendations

```
GET /recommendations/{track_id}?k=10&lambda=0.7&exclude=...
```
Steering → ANN over-fetch → per-artist cap → MMR re-rank → overflow backfill →
Last.fm top-up. Returns `k` neighbors with `listeners < 500k`.
```json
{ "recommendations": [{ "track_id": "xyz", "name": "...", "artist": "...", "similarity": 0.94, "listeners": 18200, "image": "..." }] }
```
A cold seed (row exists but `embedding IS NULL`) is **embedded on demand** before
ranking. An unknown `track_id` → **404**. An empty list means the seed genuinely
has no underground neighbors locally or on Last.fm (or it has no usable tags at
all, yielding an all-zero vector, which is guarded against).

### Feedback

```
POST /feedback
body: { "track_id": "xyz", "action": "accept" | "reject" }
```
- `accept` → promote to seed node, copy the parent edge, rerun ANN from the
  accepted node (with its own steering) and write new edges.
- `reject` → log it; it becomes a negative that steers future recs from the parent seed.

### Playlists

```
POST /playlists/linear
body: { "track_id": "abc", "n": 10, "niche": false, "exclude_ids": [] }

POST /playlists/tree
body: { "track_id": "abc", "n": 10, "max_depth": 3, "niche": false, "exclude_ids": [] }
```
Both return `{ "seed_track_id": "abc", "tracks": [PlaylistTrack...] }`.

---

## Project structure

```
discover/
├── CLAUDE.md
├── ARCHITECTURE.md           # Mermaid diagrams of every flow
├── README.md
├── requirements.txt
├── render.yaml
├── .env.example
├── migrations/
│   └── init.sql              # canonical DDL (track_id schema)
│
├── app/
│   ├── main.py               # FastAPI app, CORS, router registration, startup init_db()
│   ├── config.py             # env vars + tunables (MAX_LISTENERS, MMR_*, STEERING_ALPHA, ...)
│   ├── db.py                 # psycopg2 connection, pgvector register, init_db() + migrations
│   ├── models.py             # pydantic request/response models
│   │
│   ├── routers/
│   │   ├── songs.py          # search, status, features, backfill-covers
│   │   ├── graph.py          # GET /graph, POST /graph/seed (+ bootstrap/expansion)
│   │   ├── recommendations.py# ANN + steering + MMR + backfill + top-up
│   │   ├── feedback.py       # accept/reject
│   │   └── playlists.py      # linear + tree (BFS)
│   │
│   └── services/
│       ├── lastfm.py         # Last.fm API + blend_tags
│       ├── embeddings.py     # track_id, tag vocab, vector build, cosine, MMR, ann_search
│       ├── steering.py       # reject vector math
│       ├── ingest.py         # embed_and_store_track — the one tag→vector pipeline, called everywhere
│       └── covers.py         # Deezer/iTunes cover resolution
│
└── frontend/                 # React + Vite + ReactFlow graph UI
```

---

## Configuration (`app/config.py`)

```python
STEERING_ALPHA      = 0.3      # reject steering strength
MAX_LISTENERS       = 500000   # underground ceiling
DEFAULT_K           = 10       # default neighbors per query
EMBEDDING_DIM       = 300      # pgvector dimension
MMR_LAMBDA          = 0.7      # relevance vs diversity (1.0 = pure relevance)
MMR_POOL_MULTIPLIER = 3        # over-fetch k × this before re-ranking
MMR_MAX_PER_ARTIST  = 2        # per-artist cap in the candidate pool
```

### Environment variables

```
LASTFM_API_KEY=
LASTFM_SHARED_SECRET=          # present in .env.example; not currently required
DATABASE_URL=postgresql://user:password@localhost:5432/music_db
```

Get a Last.fm key at [last.fm/api](https://www.last.fm/api).

---

## Local development

```bash
pip install -r requirements.txt

# Postgres with pgvector via Docker
docker run -e POSTGRES_PASSWORD=password -p 5432:5432 ankane/pgvector

# Schema is auto-created on startup by init_db(), but you can also run it manually:
psql $DATABASE_URL -f migrations/init.sql

uvicorn app.main:app --reload
```

---

## Deployment (Render)

`render.yaml` provisions a web service + free Postgres. After the DB is up,
enable pgvector once (`CREATE EXTENSION IF NOT EXISTS vector;`) — though
`init_db()` also attempts this on startup. Set `LASTFM_API_KEY` in the dashboard;
`DATABASE_URL` is wired automatically.

> Free tier spins down after 15 min idle — first request after idle takes ~30s.

---

## Notes for future work

- **Two shared building blocks — don't re-inline them.** Every embedding goes
  through `ingest.embed_and_store_track` (the one tag→vector pipeline, cache-aware)
  and every nearest-neighbor lookup goes through `embeddings.ann_search`. Routers
  call these instead of repeating the Last.fm pipeline or the `embedding <=>`
  SQL. If you need a slightly different query/pipeline, extend the helper rather
  than copying it back into a router.
- Embedding dimension is fixed at 300; tags beyond vocab slot 300 are silently
  dropped. Bump `EMBEDDING_DIM` (and the `vector(...)` column) if the vocab outgrows it.
