from pydantic import BaseModel
from typing import Optional


class SongSearchResult(BaseModel):
    track_id: str
    name: str
    artist: str
    image: Optional[str] = None


class SeedRequest(BaseModel):
    track_id: str


class GraphNode(BaseModel):
    track_id: str
    name: str
    artist: str
    is_seed: bool = False
    listeners: Optional[int] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    similarity: float


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class Recommendation(BaseModel):
    track_id: str
    name: str
    artist: str
    similarity: float
    listeners: int
    image: Optional[str] = None


class RecommendationsResponse(BaseModel):
    recommendations: list[Recommendation]


class FeedbackRequest(BaseModel):
    track_id: str
    action: str


class FeedbackResponse(BaseModel):
    success: bool
    message: str


class TrackFeatures(BaseModel):
    track_id: str
    name: str
    artist: str
    listeners: int
    tags: list[str]
    embedding: Optional[list[float]] = None


class PlaylistTrack(BaseModel):
    track_id: str
    name: str
    artist: str
    similarity: float
    listeners: int
    image: Optional[str] = None


class LinearPlaylistRequest(BaseModel):
    track_id: str
    n: int = 10
    niche: bool = False
    exclude_ids: list[str] = []


class TreePlaylistRequest(BaseModel):
    track_id: str
    n: int = 10
    max_depth: int = 3
    niche: bool = False
    exclude_ids: list[str] = []


class PlaylistResponse(BaseModel):
    seed_track_id: str
    tracks: list[PlaylistTrack]
