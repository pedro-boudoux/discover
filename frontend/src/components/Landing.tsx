import { useRef } from "react";
import { Hero } from "./Hero";
import { ShapeGrid } from "./ShapeGrid";
import type { SongSearchResult } from "../types";

type Props = {
  onPick: (song: SongSearchResult) => void;
  disabled?: boolean;
};

export function Landing({ onPick, disabled }: Props) {
  const aboutRef = useRef<HTMLElement>(null);

  function scrollToAbout() {
    aboutRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="absolute inset-0 overflow-x-hidden overflow-y-auto">
      {/* Section 1 — hero over the animated grid, one viewport tall */}
      <section className="relative h-full w-full">
        <div className="absolute inset-0">
          <ShapeGrid
            direction="diagonal"
            speed={0.5}
            borderColor="rgba(0,0,0,0.03)"
            hoverFillColor="rgba(255,255,255,0.00)"
            squareSize={44}
            hoverTrailAmount={0}
          />
        </div>

        <Hero onPick={onPick} disabled={disabled} />

        <button
          type="button"
          onClick={scrollToAbout}
          aria-label="Scroll down to learn more"
          className="group absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 text-black/40 hover:text-black/70 transition-colors"
        >
          <span className="text-[11px] uppercase tracking-[0.2em] font-medium">
            About
          </span>
          <span className="scroll-bob">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M6 9l6 6 6-6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        </button>
      </section>

      {/* Section 2 — solid white panel for project copy, one viewport tall */}
      <section
        ref={aboutRef}
        className="relative h-full w-full bg-white flex items-center justify-center"
      >
        {/* Project text goes here */}
      </section>
    </div>
  );
}
