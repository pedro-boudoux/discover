import { Handle, Position, type NodeProps } from "reactflow";

export type SongNodeData = {
  name: string;
  artist: string;
  image: string | null;
  isSeed: boolean;
  similarity?: number;
  listeners?: number;
};

export function SongNode({ data, selected }: NodeProps<SongNodeData>) {
  return (
    <div
      className={[
        "group flex items-center gap-3 px-3 py-2 rounded-xl border w-[230px] transition",
        "bg-canvas",
        selected
          ? "border-accent shadow-[0_0_0_2px_rgba(34,211,238,0.25)]"
          : data.isSeed
            ? "border-accent/60"
            : "border-edge hover:border-neutral-500",
      ].join(" ")}
    >
      <Handle type="target" position={Position.Top} />
      {data.image ? (
        <img
          src={data.image}
          alt=""
          className="w-10 h-10 rounded-md object-cover flex-shrink-0"
        />
      ) : (
        <div className="w-10 h-10 rounded-md bg-edge flex-shrink-0" />
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium leading-tight">
          {data.name}
        </div>
        <div className="truncate text-xs text-muted">{data.artist}</div>
        {typeof data.similarity === "number" && !data.isSeed && (
          <div className="mt-0.5 text-[10px] text-muted">
            sim {data.similarity.toFixed(2)}
            {typeof data.listeners === "number" &&
              ` · ${formatListeners(data.listeners)} listeners`}
          </div>
        )}
        {data.isSeed && (
          <div className="mt-0.5 text-[10px] uppercase tracking-wider text-accent">
            seed
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

function formatListeners(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
