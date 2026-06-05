import { useReactFlow } from "reactflow";

export function ZoomControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  return (
    <div className="relative overflow-hidden rounded-[25px] w-[40px] h-[120px] flex flex-col items-center justify-center gap-[15px] p-[10px] shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
      <div
        aria-hidden
        className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-[25px] pointer-events-none"
      />
      <div
        aria-hidden
        className="absolute inset-0 pointer-events-none rounded-[25px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]"
      />
      <button
        onClick={() => zoomIn({ duration: 200 })}
        aria-label="Zoom in"
        className="relative w-5 h-5 flex items-center justify-center text-[#09090B]/60 hover:text-[#09090B] transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M7 1v12M1 7h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
      <button
        onClick={() => zoomOut({ duration: 200 })}
        aria-label="Zoom out"
        className="relative w-5 h-5 flex items-center justify-center text-[#09090B]/60 hover:text-[#09090B] transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M1 7h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
      <button
        onClick={() => fitView({ duration: 400, padding: 0.3 })}
        aria-label="Fit view"
        className="relative w-5 h-5 flex items-center justify-center text-[#09090B]/60 hover:text-[#09090B] transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path
            d="M1 5V1h4M9 1h4v4M13 9v4H9M5 13H1V9"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
  );
}
