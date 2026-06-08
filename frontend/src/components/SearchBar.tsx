import { useEffect, useRef, useState } from "react";
import { searchSongs } from "../api";
import type { SongSearchResult } from "../types";
import { Spinner } from "./Loader";

type Props = {
  onPick: (song: SongSearchResult) => void;
  placeholder?: string;
  autoFocus?: boolean;
  dropUp?: boolean;
  disabled?: boolean;
};

export function SearchBar({ onPick, placeholder, autoFocus, dropUp = false, disabled = false }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SongSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const reqIdRef = useRef(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }
    const myReq = ++reqIdRef.current;
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const data = await searchSongs(q.trim());
        if (reqIdRef.current === myReq) {
          setResults(data);
          setOpen(true);
        }
      } catch {
        if (reqIdRef.current === myReq) setResults([]);
      } finally {
        if (reqIdRef.current === myReq) setLoading(false);
      }
    }, 250);
    return () => clearTimeout(handle);
  }, [q]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div ref={wrapRef} className="relative w-full">
      {/* Search input — glass pill with hover pop */}
      <div className="relative overflow-hidden rounded-[25px] border border-white shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)] transition-all duration-200 hover:scale-[1.025] hover:shadow-[0px_6px_20px_rgba(0,0,0,0.18)] focus-within:scale-[1.025] focus-within:shadow-[0px_6px_20px_rgba(0,0,0,0.18)]">
        <div
          aria-hidden
          className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-[25px] pointer-events-none"
        />
        <div
          aria-hidden
          className="absolute inset-0 rounded-[25px] pointer-events-none shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]"
        />
        <input
          autoFocus={autoFocus}
          value={q}
          onChange={(e) => !disabled && setQ(e.target.value)}
          onFocus={() => !disabled && results.length > 0 && setOpen(true)}
          placeholder={disabled ? "Building your graph…" : (placeholder ?? "Search for a song…")}
          disabled={disabled}
          className="relative w-full bg-transparent h-[48px] px-5 pr-12 text-[14px] text-[#3a3a3a] placeholder:text-[#8a8a8a] focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        {loading && (
          <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none">
            <Spinner size={15} className="text-[#9a9a9a]" />
          </div>
        )}
      </div>

      {/* Results dropdown — glass panel, opens upward when dropUp=true */}
      {open && results.length > 0 && (
        <div
          className={[
            "absolute z-20 w-full overflow-hidden rounded-[15px] shadow-[0px_4px_20px_rgba(0,0,0,0.18)]",
            dropUp ? "bottom-[calc(100%+8px)]" : "top-[calc(100%+8px)]",
          ].join(" ")}
        >
          <div
            aria-hidden
            className="absolute inset-0 backdrop-blur-[2.5px] bg-white/90 rounded-[15px] pointer-events-none"
          />
          <div
            aria-hidden
            className="absolute inset-0 pointer-events-none rounded-[15px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]"
          />
          <ul className="relative max-h-64 overflow-y-auto py-2">
            {results.map((r) => (
              <li
                key={r.track_id}
                onClick={() => {
                  onPick(r);
                  setOpen(false);
                  setQ("");
                  setResults([]);
                }}
                className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-blue-100/60 transition-colors"
              >
                {r.image ? (
                  <img
                    src={r.image}
                    alt=""
                    className="w-9 h-9 rounded-md object-cover flex-shrink-0"
                  />
                ) : (
                  <div className="w-9 h-9 rounded-md bg-white/40 flex-shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[14px] font-medium text-[#3a3a3a]">{r.name}</div>
                  <div className="truncate text-[12px] text-[#8a8a8a]">{r.artist}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
