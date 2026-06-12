import { SearchBar } from "./SearchBar";
import type { SongSearchResult } from "../types";

type Props = {
  onPick: (song: SongSearchResult) => void;
  disabled?: boolean;
};

export function Hero({ onPick, disabled }: Props) {
  return (
    <div
      className="absolute left-6 right-6 sm:left-[60px] sm:right-auto z-10 flex flex-col items-start fade-up"
      style={{ top: "38%" }}
    >
      <span
        className="font-display font-medium text-[96px] sm:text-[128px] text-black leading-none select-none"
        //style={{ textShadow: "0px 2px 8px rgba(0,0,0,0.18)" }}
      >
        pyo
      </span>
      <p
        className="text-black text-[15px] sm:text-[17px] leading-normal mt-3 font-light"
     //  style={{ textShadow: "0px 1px 4px rgba(0,0,0,0.3)" }}
      >
        stands for <span className="italic ">putting you on</span> good music.
      </p>
      <div className="mt-6 w-full sm:w-[430px] sm:max-w-[calc(100vw-80px)]">
        <SearchBar
          onPick={onPick}
          placeholder="Tell us what you like, and we'll find similar."
          placeholderShort="What do you like?"
          autoFocus
          disabled={disabled}
        />
      </div>
    </div>
  );
}
