import { Spinner } from "./Loader";

type Phase = "checking" | "warm" | "cold";

type Props = {
  phase: Phase;
  compact?: boolean;
  className?: string;
};

export function SeedingStatus({ phase, compact = false, className = "" }: Props) {
  const label = phase === "checking" ? "Checking song" : "Building your graph";

  return (
    <div className={`flex flex-col items-center gap-2 ${className}`}>
      <div className="relative overflow-hidden rounded-full shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
        <div aria-hidden className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 pointer-events-none rounded-full" />
        <div aria-hidden className="absolute inset-0 pointer-events-none rounded-full shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]" />
        <div
          className={`relative flex items-center gap-2.5 text-black ${compact ? "text-xs px-3 py-1.5" : "text-sm px-4 py-2"} font-medium`}
        >
          <Spinner size={compact ? 13 : 15} className="text-black" />
          <span>{label}</span>
        </div>
      </div>
      {phase === "cold" && (
        <div
          className={`text-black/80 ${compact ? "text-[11px]" : "text-xs"} font-medium`}
//          style={{ textShadow: "0px 1px 3px rgba(0,0,0,0.5)" }}
        >
          First time seeing this song, give us a minute this could take a while!
        </div>
      )}
    </div>
  );
}
