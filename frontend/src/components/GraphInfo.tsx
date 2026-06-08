import { useEffect, useRef, useState } from "react";
import { getDominantTags } from "../api";

type Tag = { tag: string; weight: number; count: number; share: number };

type Props = {
  nodeCount: number;
  edgeCount: number;
  trackIds: string[];
};

const SKELETON_WIDTHS = [75, 55, 68, 48, 62];

export function GraphInfo({ nodeCount, edgeCount, trackIds }: Props) {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loadingTags, setLoadingTags] = useState(false);

  // Stable string key so the effect only fires when node IDs change,
  // not on every position tick (which creates a new trackIds reference).
  const idsKey = trackIds.join(",");
  const trackIdsRef = useRef(trackIds);
  trackIdsRef.current = trackIds;

  useEffect(() => {
    if (trackIdsRef.current.length === 0) {
      setTags([]);
      setLoadingTags(false);
      return;
    }
    setLoadingTags(true);
    const handle = setTimeout(async () => {
      try {
        const data = await getDominantTags(trackIdsRef.current, 5);
        setTags(data.tags);
      } catch {
        // silently ignore
      } finally {
        setLoadingTags(false);
      }
    }, 600);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  return (
    <div className="relative overflow-hidden rounded-[15px] shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
      <div aria-hidden className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-[15px] pointer-events-none" />
      <div aria-hidden className="absolute inset-0 pointer-events-none rounded-[15px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]" />
      <div className="relative flex flex-col gap-[15px] p-5 min-w-[160px]">
        <p className="font-medium text-[#656565] text-base leading-none">Graph Info</p>
        <p className="font-medium text-[#656565] text-xs leading-none">Songs: {nodeCount}</p>
        <p className="font-medium text-[#656565] text-xs leading-none">Edges: {edgeCount}</p>

        {loadingTags ? (
          <div className="flex flex-col gap-2">
            <p className="font-medium text-[#656565] text-xs leading-none mb-0.5">Dominant Tags:</p>
            {SKELETON_WIDTHS.map((w, i) => (
              <div
                key={i}
                className="h-2.5 rounded-full bg-[#656565]/20 animate-pulse"
                style={{ width: `${w}%`, animationDelay: `${i * 80}ms` }}
              />
            ))}
          </div>
        ) : tags.length > 0 ? (
          <div className="font-medium text-[#656565] text-xs leading-normal">
            <p className="mb-2">Dominant Tags:</p>
            <ul className="list-disc list-inside space-y-1">
              {tags.map((t) => (
                <li key={t.tag} className="capitalize">
                  {t.tag} ({Math.round(t.share * 100)}%)
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
