import { getSpotifyLink } from "../api";

// Spotify "listen" links are resolved once per track and cached in the browser
// so the popover opens instantly and we don't re-search on every node click.
// The map persists across sessions in localStorage.
//
//   undefined → never looked up
//   string    → resolved open.spotify.com URL
//   null      → looked up, the song isn't on Spotify

const STORAGE_KEY = "spotify_links";

type LinkMap = Record<string, string | null>;

function readMap(): LinkMap {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as LinkMap;
  } catch {
    return {};
  }
}

function writeMap(map: LinkMap): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // quota exceeded / private mode — links just won't persist, no harm done
  }
}

export function getCachedSpotifyLink(trackId: string): string | null | undefined {
  const map = readMap();
  return trackId in map ? map[trackId] : undefined;
}

// Dedupe concurrent lookups for the same track (e.g. prefetch + popover open).
const inflight = new Map<string, Promise<string | null>>();

// Resolve a track's Spotify link, hitting the cache first. A successful lookup
// (found or genuinely not-on-Spotify) is cached; a network/HTTP failure is not,
// so it can be retried later.
export function prefetchSpotifyLink(trackId: string): Promise<string | null> {
  const cached = getCachedSpotifyLink(trackId);
  if (cached !== undefined) return Promise.resolve(cached);

  const existing = inflight.get(trackId);
  if (existing) return existing;

  const p = getSpotifyLink(trackId)
    .then((res) => {
      // Only persist a definitive answer. checked=false means the backend
      // couldn't reach Spotify, so we leave it uncached to retry later.
      if (res.checked) {
        const map = readMap();
        map[trackId] = res.url;
        writeMap(map);
      }
      return res.url;
    })
    .catch(() => null)
    .finally(() => {
      inflight.delete(trackId);
    });

  inflight.set(trackId, p);
  return p;
}