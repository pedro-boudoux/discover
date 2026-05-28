export type SongSearchResult = {
  track_id: string;
  name: string;
  artist: string;
  image: string | null;
};

export type Recommendation = {
  track_id: string;
  name: string;
  artist: string;
  similarity: number;
  listeners: number;
  image: string | null;
};

export type PlaylistTrack = {
  track_id: string;
  name: string;
  artist: string;
  similarity: number;
  listeners: number;
  image: string | null;
};

export type ExpansionMethod = "recommendations" | "linear" | "tree";

export type ExpansionParams = {
  method: ExpansionMethod;
  k: number;
  lambda: number;
  niche: boolean;
  maxDepth: number;
};

export const DEFAULT_EXPANSION: ExpansionParams = {
  method: "recommendations",
  k: 10,
  lambda: 0.7,
  niche: false,
  maxDepth: 3,
};
