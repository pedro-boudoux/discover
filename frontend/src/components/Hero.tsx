import { SearchBar } from "./SearchBar";
import type { SongSearchResult } from "../types";

type Props = {
  onPick: (song: SongSearchResult) => void;
  disabled?: boolean;
};

export function Hero({ onPick, disabled }: Props) {
  return (
    <div
      className="absolute flex flex-col items-start fade-up"
      style={{ left: 60, top: "38%" }}
    >
      <span
        className="font-display font-medium text-[128px] text-white leading-none select-none"
        style={{ textShadow: "0px 2px 8px rgba(0,0,0,0.18)" }}
      >
        pyo
      </span>
      <p
        className="text-white text-[17px] leading-normal mt-3 font-light"
        style={{ textShadow: "0px 1px 4px rgba(0,0,0,0.3)" }}
      >
        stands for &ldquo;putting you on&rdquo; good music.
      </p>
      <div className="mt-6 w-[430px] max-w-[calc(100vw-80px)]">
        <SearchBar
          onPick={onPick}
          placeholder="Tell us what you like, and we'll find similar."
          autoFocus
          disabled={disabled}
        />
      </div>
    </div>
  );
}
