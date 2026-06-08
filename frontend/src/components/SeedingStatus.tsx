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
    <div className={`flex flex-col items-start gap-2 ${className}`}>
      <div className="relative overflow-hidden rounded-full shadow-[0px_1px_4.1px_rgba(0,0,0,0.25)]">
        <div aria-hidden className="absolute inset-0 backdrop-blur-[3px] bg-white/[0.22] pointer-events-none rounded-full" />
        <div
          className={`relative flex items-center gap-2.5 text-white ${compact ? "text-xs px-3 py-1.5" : "text-sm px-4 py-2"} font-medium`}
          style={{ textShadow: "0px 1px 3px rgba(0,0,0,0.4)" }}
        >
          <Spinner size={compact ? 13 : 15} className="text-white" />
          <span>{label}</span>
        </div>
      </div>
      {phase === "cold" && (
        <div
          className={`text-white/80 ${compact ? "text-[11px]" : "text-xs"} font-medium pl-1`}
          style={{ textShadow: "0px 1px 3px rgba(0,0,0,0.5)" }}
        >
          First time — fetching from Last.fm, may take 30+ sec.
        </div>
      )}
    </div>
  );
}
