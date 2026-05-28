import type {
  ExpansionMethod,
  PlaylistTrack,
  Recommendation,
  SongSearchResult,
} from "./types";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "https://discover-dk7y.onrender.com";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} on ${path}`);
  }
  return res.json() as Promise<T>;
}

export function searchSongs(q: string) {
  const params = new URLSearchParams({ q });
  return request<SongSearchResult[]>(`/songs/search?${params}`);
}

export function getSongStatus(track_id: string) {
  return request<{ exists: boolean; cached: boolean }>(
    `/songs/${track_id}/status`,
  );
}

export function seedSong(track_id: string) {
  return request<{ track_id: string; name: string; artist: string }>(
    `/graph/seed`,
    { method: "POST", body: JSON.stringify({ track_id }) },
  );
}

export function getRecommendations(track_id: string, k: number, lambdaParam: number) {
  const params = new URLSearchParams({ k: String(k), lambda: String(lambdaParam) });
  return request<{ recommendations: Recommendation[] }>(
    `/recommendations/${track_id}?${params}`,
  );
}

export function linearPlaylist(track_id: string, n: number, niche: boolean) {
  return request<{ seed_track_id: string; tracks: PlaylistTrack[] }>(
    `/playlists/linear`,
    { method: "POST", body: JSON.stringify({ track_id, n, niche }) },
  );
}

export function treePlaylist(
  track_id: string,
  n: number,
  max_depth: number,
  niche: boolean,
) {
  return request<{ seed_track_id: string; tracks: PlaylistTrack[] }>(
    `/playlists/tree`,
    { method: "POST", body: JSON.stringify({ track_id, n, max_depth, niche }) },
  );
}

export type ExpandedTrack = {
  track_id: string;
  name: string;
  artist: string;
  similarity: number;
  listeners: number;
  image: string | null;
};

export async function expandFromTrack(
  track_id: string,
  method: ExpansionMethod,
  opts: { k: number; lambda: number; niche: boolean; maxDepth: number },
): Promise<ExpandedTrack[]> {
  if (method === "recommendations") {
    const data = await getRecommendations(track_id, opts.k, opts.lambda);
    return data.recommendations;
  }
  if (method === "linear") {
    const data = await linearPlaylist(track_id, opts.k, opts.niche);
    return data.tracks;
  }
  const data = await treePlaylist(track_id, opts.k, opts.maxDepth, opts.niche);
  return data.tracks;
}
