import { useEffect, useState } from "react";
import { getDominantTags } from "../api";

type Tag = { tag: string; weight: number; count: number; share: number };

type Props = {
  nodeCount: number;
  edgeCount: number;
  trackIds: string[];
};

export function GraphInfo({ nodeCount, edgeCount, trackIds }: Props) {
  const [tags, setTags] = useState<Tag[]>([]);

  useEffect(() => {
    if (trackIds.length === 0) {
      setTags([]);
      return;
    }
    const handle = setTimeout(async () => {
      try {
        const data = await getDominantTags(trackIds, 5);
        setTags(data.tags);
      } catch {
        // silently ignore tag fetch failures
      }
    }, 600);
    return () => clearTimeout(handle);
  }, [trackIds]);

  return (
    <div className="relative overflow-hidden rounded-[15px] shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
      <div
        aria-hidden
        className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-[15px] pointer-events-none"
      />
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none rounded-[15px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]"
      />
      <div className="relative flex flex-col gap-[15px] p-5 min-w-[160px]">
        <p className="font-medium text-[#656565] text-base leading-none">Graph Info</p>
        <p className="font-medium text-[#656565] text-xs leading-none">Songs: {nodeCount}</p>
        <p className="font-medium text-[#656565] text-xs leading-none">Edges: {edgeCount}</p>
        {tags.length > 0 && (
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
        )}
      </div>
    </div>
  );
}
