import { useState } from "react";
import {
  clearSpotifyToken,
  createSpotifyPlaylist,
  getSpotifyUserId,
  getStoredToken,
  openSpotifyAuth,
  searchSpotifyTrack,
} from "../services/spotify";
import { Spinner } from "./Loader";

type Song = { name: string; artist: string };

type Props = {
  songs: Song[];
};

type ExportState =
  | { status: "idle" }
  | { status: "authenticating" }
  | { status: "generating" }
  | { status: "searching"; done: number; total: number }
  | { status: "creating" }
  | { status: "done"; url: string; found: number; total: number }
  | { status: "error"; message: string };

function SpotifyIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
    </svg>
  );
}

export function SpotifyExportButton({ songs }: Props) {
  const [state, setState] = useState<ExportState>({ status: "idle" });

  async function handleExport() {
    if (songs.length === 0) return;
    setState({ status: "authenticating" });

    let token = getStoredToken();
    if (!token) {
      try {
        await openSpotifyAuth();
        token = getStoredToken();
        if (!token) throw new Error("No token after authentication");
      } catch (err) {
        setState({ status: "error", message: err instanceof Error ? err.message : "Auth failed" });
        return;
      }
    }

    setState({ status: "searching", done: 0, total: songs.length });

    const uris: string[] = [];
    for (let i = 0; i < songs.length; i++) {
      try {
        const uri = await searchSpotifyTrack(token, songs[i].artist, songs[i].name);
        if (uri) uris.push(uri);
      } catch {
        // skip tracks that error
      }
      setState({ status: "searching", done: i + 1, total: songs.length });
    }

    setState({ status: "creating" });

    try {
      const userId = await getSpotifyUserId(token);
      const date = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" });
      const url = await createSpotifyPlaylist(token, userId, `pyo – ${date}`, uris);
      setState({ status: "done", url, found: uris.length, total: songs.length });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "Failed to create playlist" });
    }
  }

  function handleDisconnect() {
    clearSpotifyToken();
    setState({ status: "idle" });
  }

  const busy =
    state.status === "authenticating" ||
    state.status === "searching" ||
    state.status === "creating";

  return (
    <div className="flex flex-col items-end gap-2">
      {/* Result / error banners */}
      {state.status === "done" && (
        <div className="relative overflow-hidden rounded-[12px] shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
          <div aria-hidden className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-[12px] pointer-events-none" />
          <div aria-hidden className="absolute inset-0 pointer-events-none rounded-[12px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]" />
          <div className="relative flex items-center gap-2.5 px-3.5 py-2 text-xs font-medium text-black/70">
            <span className="text-[#1DB954]">✓</span>
            <span>
              Playlist created —{" "}
              <a
                href={state.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#1DB954] underline underline-offset-2"
              >
                open in Spotify
              </a>
              {state.found < state.total && (
                <span className="text-black/40 ml-1">
                  ({state.found}/{state.total} found)
                </span>
              )}
            </span>
            <button
              onClick={() => setState({ status: "idle" })}
              className="text-black/30 hover:text-black/60 transition-colors leading-none"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {state.status === "error" && (
        <div className="relative overflow-hidden rounded-[12px] shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
          <div aria-hidden className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-[12px] pointer-events-none" />
          <div aria-hidden className="absolute inset-0 pointer-events-none rounded-[12px] shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]" />
          <div className="relative flex items-center gap-2.5 px-3.5 py-2 text-xs font-medium">
            <span className="text-red-500">{state.message}</span>
            <button
              onClick={() => setState({ status: "idle" })}
              className="text-black/30 hover:text-black/60 transition-colors leading-none"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Main button */}
      <div className="relative overflow-hidden rounded-full shadow-[0px_1px_4.1px_0px_rgba(0,0,0,0.25)]">
        <div aria-hidden className="absolute inset-0 backdrop-blur-[2.5px] bg-white/75 rounded-full pointer-events-none" />
        <div aria-hidden className="absolute inset-0 pointer-events-none rounded-full shadow-[inset_0px_4px_4px_0px_rgba(255,255,255,0.25)]" />
        <div className="relative flex items-center">
          <button
            onClick={handleExport}
            disabled={busy || songs.length === 0}
            className="flex items-center gap-2 pl-3.5 pr-3 py-2 text-sm font-medium text-black disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
          >
            {busy ? (
              <Spinner size={14} className="text-[#1DB954]" />
            ) : (
              <SpotifyIcon className="w-[14px] h-[14px] text-[#1DB954]" />
            )}
            <span>
              {state.status === "authenticating" && "Connecting…"}
              {state.status === "searching" && `Searching… ${state.done}/${state.total}`}
              {state.status === "creating" && "Creating playlist…"}
              {(state.status === "idle" || state.status === "done" || state.status === "error") &&
                "Export to Spotify"}
            </span>
          </button>

          {/* Disconnect button — shown when a token is stored */}
          {getStoredToken() && state.status === "idle" && (
            <button
              onClick={handleDisconnect}
              className="pr-3 pl-1 py-2 text-[10px] text-black/30 hover:text-black/60 transition-colors font-medium"
              title="Disconnect Spotify"
            >
              ×
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
