import { useEffect, useRef, useState } from "react";
import { searchSongs } from "../api";
import type { SongSearchResult } from "../types";

type Props = {
  onPick: (song: SongSearchResult) => void;
  placeholder?: string;
  autoFocus?: boolean;
};

export function SearchBar({ onPick, placeholder, autoFocus }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SongSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const reqIdRef = useRef(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
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
    <div ref={wrapRef} className="relative w-full max-w-xl">
      <input
        autoFocus={autoFocus}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder={placeholder ?? "Search for a song to seed your graph…"}
        className="w-full bg-canvas border border-edge rounded-xl px-5 py-3.5 text-base placeholder:text-muted focus:outline-none focus:border-accent transition"
      />
      {loading && (
        <div className="absolute right-4 top-1/2 -translate-y-1/2 text-xs text-muted">
          …
        </div>
      )}
      {open && results.length > 0 && (
        <ul className="absolute z-20 mt-2 w-full bg-canvas border border-edge rounded-xl overflow-hidden shadow-2xl max-h-80 overflow-y-auto">
          {results.map((r) => (
            <li
              key={r.track_id}
              onClick={() => {
                onPick(r);
                setOpen(false);
                setQ("");
                setResults([]);
              }}
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-edge/60 transition"
            >
              {r.image ? (
                <img src={r.image} alt="" className="w-10 h-10 rounded object-cover" />
              ) : (
                <div className="w-10 h-10 rounded bg-edge" />
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{r.name}</div>
                <div className="truncate text-xs text-muted">{r.artist}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
