# Underground Music Discovery — Backend Plan

## What we're building

A backend that powers a graph-based music discovery app. The user drops a seed song onto a graph, the backend finds sonically similar underground tracks via vector similarity search, and the graph expands based on user feedback.

"Underground" = low listener/playcount count from Last.fm (proxy for popularity since Spotify's popularity score is behind a deprecated API).

---

## Stack

| Layer | Tool | Why |
|---|---|---|
| API | FastAPI (Python) | Async, fast, pairs well with ML tooling |
| Song search | Spotify Web API via `spotipy` | Search by name, get metadata — no login required |
| Audio features + tags | Last.fm API | Tag-based embeddings, listener counts, similar tracks — all free |
| Embeddings | numpy + scikit-learn | Normalize Last.fm tag vectors |
| Vector DB | Postgres + pgvector | ANN search + graph state in one DB |
| Hosting | Render | Managed Postgres with pgvector, easy FastAPI deploys |

### Dependencies

```
fastapi
uvicorn
spotipy
requests
numpy
scikit-learn
psycopg2-binary
pgvector
python-dotenv
```

---

## Why not Spotify audio features?

Spotify deprecated `GET /audio-features` and `GET /recommendations` in November 2024. Apps created after that date get a 403 on these endpoints with no alternative from Spotify. We use Spotify only for search and basic metadata, and Last.fm for everything embeddings-related.

---

## How it works

### The core pipeline

1. User searches for a song → `GET /songs/search` (hits Spotify)
2. User drops it on the graph → `POST /graph/seed`
3. Backend fetches Last.fm tags + listener count for the song
4. Builds a tag vector: `{ "shoegaze": 91, "dream pop": 74, "lo-fi": 40, ... }`
5. Normalizes the vector → stores embedding in pgvector
6. Runs ANN search: find k-nearest neighbors filtered to `listeners < threshold`
7. Returns candidate songs as new graph nodes
8. User accepts or rejects each node → `POST /feedback`
   - **Accept** → song becomes a new seed, pipeline reruns on it
   - **Reject** → embedding stored as a negative, steers future searches away

### Vector steering on reject

When a song is rejected, future ANN queries from that seed are nudged away from it:

```
query_vector = seed_embedding - α * rejected_embedding
```

`α` controls how strongly rejections steer (start with `0.3`, tune from there).

---

## Data sources

### Spotify (search + metadata only)

Used for: searching songs by name, getting the Spotify ID, artist name, album art.

Auth: **Client Credentials** — no user login needed.

```python
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
))
```

Get credentials at [developer.spotify.com](https://developer.spotify.com) → create an app → copy client ID + secret into `.env`.

Example response from `GET /search`:
```json
{
  "tracks": {
    "items": [
      {
        "id": "abc123",
        "name": "Believe",
        "artists": [{ "name": "Cher" }],
        "album": { "name": "Believe", "images": [...] },
        "duration_ms": 240000
      }
    ]
  }
}
```

### Last.fm (tags + listener counts → embeddings)

Used for: building tag vectors (the actual embedding), filtering underground tracks by listener count, bootstrapping candidate songs via `track.getSimilar`.

Auth: just an API key — free, no OAuth.

Get a key at [last.fm/api](https://www.last.fm/api).

**`track.getInfo`** — called per song, gives listener count (underground filter) and top tags:

```json
{
  "track": {
    "name": "Believe",
    "listeners": "69572",
    "playcount": "281445",
    "artist": { "name": "Cher" },
    "toptags": {
      "tag": [
        { "name": "pop" },
        { "name": "dance" },
        { "name": "90s" }
      ]
    }
  }
}
```

**`artist.getTopTags`** — richer tags with confidence counts, used as the primary embedding source:

```json
{
  "toptags": {
    "tag": [
      { "count": 100, "name": "female vocalists" },
      { "count": 93,  "name": "indie" },
      { "count": 88,  "name": "indie pop" },
      { "count": 80,  "name": "pop" },
      { "count": 67,  "name": "alternative" },
      { "count": 13,  "name": "dream pop" }
    ]
  }
}
```

The `count` field is how many Last.fm users applied that tag — it acts as a confidence score. Normalize these counts into a sparse vector and you have your embedding.

**`track.getSimilar`** — useful for bootstrapping candidates when the vector DB is sparse:

```json
{
  "similartracks": {
    "track": [
      { "name": "If You Had My Love", "artist": { "name": "Jennifer Lopez" }, "match": 1.0 },
      { "name": "Genie In a Bottle", "artist": { "name": "Christina Aguilera" }, "match": 0.82 }
    ]
  }
}
```

### Combining both sources

For a single seed song the pipeline makes 3 API calls:

```
Spotify /search          → get spotify_id, name, artist, album art
Last.fm track.getInfo    → get listener count (underground filter) + basic tags
Last.fm artist.getTopTags → get full tag vector with confidence counts → embedding
```

---

## Embedding strategy

Tags from `artist.getTopTags` form a sparse dictionary. To turn this into a fixed-size vector for pgvector:

1. Maintain a global tag vocabulary (grows as new songs are added)
2. For each song, fetch tags from `artist.getTopTags`
3. Clean each tag: `tag.lower().strip()` — Last.fm tags are user-generated so "Hip-Hop", "hip hop", and "hip-hop" will all appear and must be collapsed into one dimension
4. Normalize counts by dividing by the max count in the response (so the top tag is always 1.0)
5. Store as a dense vector aligned to the vocabulary

For example, Fakemink's tag response normalizes to:

```python
{
    "cloud rap": 1.0,   # 100/100
    "jerk": 0.49,       # 49/100
    "pop rap": 0.11,    # 11/100
    "british": 0.11,    # 11/100
    "plugg": 0.05,      # 5/100
    "hip-hop": 0.03,    # 3/100 (after cleaning "Hip-Hop" → "hip-hop")
    "rap": 0.03,        # 3/100
    "uk hip hop": 0.01,
    "hip hop": 0.01,
    "experimental hip hop": 0.01
}
```

Artists with overlapping high-count tags (e.g. both have "cloud rap": ~1.0) will score high on cosine similarity. Low-count tags like "experimental hip hop" contribute very little — which is the right behaviour since they're low-confidence.

Underground filter: `listeners < 500000` from `track.getInfo` (tune this threshold to taste).

---

## Database Schema

### Enable pgvector

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Songs table

Embedding dimension is dynamic based on tag vocabulary size — start with 300 as a reasonable upper bound and expand as needed.

```sql
CREATE TABLE songs (
    id              SERIAL PRIMARY KEY,
    spotify_id      TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    artist          TEXT NOT NULL,
    listeners       INTEGER,
    embedding       vector(300),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON songs USING hnsw (embedding vector_cosine_ops);
```

### Tag vocabulary table

```sql
CREATE TABLE tag_vocab (
    id      SERIAL PRIMARY KEY,
    tag     TEXT UNIQUE NOT NULL
);
```

### Graph tables

```sql
CREATE TABLE graph_nodes (
    id          SERIAL PRIMARY KEY,
    spotify_id  TEXT REFERENCES songs(spotify_id),
    is_seed     BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE graph_edges (
    id              SERIAL PRIMARY KEY,
    source_id       TEXT REFERENCES songs(spotify_id),
    target_id       TEXT REFERENCES songs(spotify_id),
    similarity      FLOAT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### Feedback table

```sql
CREATE TABLE feedback (
    id          SERIAL PRIMARY KEY,
    spotify_id  TEXT REFERENCES songs(spotify_id),
    action      TEXT CHECK (action IN ('accept', 'reject')),
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

---

## API Endpoints

### Songs

```
GET /songs/search?q={query}
```
Searches Spotify by song name or artist. Returns name, artist, spotify_id, album art. No Last.fm call here — keep search fast.

```
GET /songs/{spotify_id}/features
```
Fetches and caches Last.fm tags + listener count for a song. Returns the tag vector. If already in DB, returns cached version.

---

### Graph

```
GET /graph
```
Returns all current nodes and edges for the frontend to render.

Response shape:
```json
{
  "nodes": [
    { "spotify_id": "abc", "name": "...", "artist": "...", "is_seed": true }
  ],
  "edges": [
    { "source": "abc", "target": "xyz", "similarity": 0.91 }
  ]
}
```

```
POST /graph/seed
body: { "spotify_id": "abc123" }
```
Adds a song as a seed node. Internally: fetches Last.fm data → builds tag vector → stores embedding → triggers recommendation fetch.

---

### Recommendations

```
GET /recommendations/{spotify_id}?k=10
```
Runs ANN search from the song's tag embedding. Returns k nearest neighbors filtered to `listeners < 500000`. Applies reject steering if the seed has prior negative feedback.

Response shape:
```json
{
  "recommendations": [
    { "spotify_id": "xyz", "name": "...", "artist": "...", "similarity": 0.94, "listeners": 18200 }
  ]
}
```

---

### Feedback

```
POST /feedback
body: { "spotify_id": "xyz", "action": "accept" | "reject" }
```

- `accept` → adds the song as a new graph node + seed, reruns recommendations on it
- `reject` → stores the embedding as a negative, updates the steering vector for the parent seed

---

## Project Structure

```
music-discovery/
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── render.yaml
├── README.md
│
├── app/
│   ├── main.py               # FastAPI app + router registration
│   ├── config.py             # env vars, settings
│   ├── db.py                 # postgres connection, pgvector helpers
│   ├── models.py             # pydantic request/response models
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── songs.py          # GET /songs/search, GET /songs/{id}/features
│   │   ├── graph.py          # GET /graph, POST /graph/seed
│   │   ├── recommendations.py
│   │   └── feedback.py
│   │
│   └── services/
│       ├── __init__.py
│       ├── spotify.py        # spotipy wrapper — search only
│       ├── lastfm.py         # last.fm API — tags, listeners, similar tracks
│       ├── embeddings.py     # tag dict → normalized vector
│       └── steering.py       # reject vector math
│
└── migrations/
    └── init.sql              # CREATE EXTENSION + CREATE TABLE statements
```

---

## Environment Variables

```
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
LASTFM_API_KEY=
DATABASE_URL=postgresql://user:password@localhost:5432/music_db
```

---

## Local development

```bash
# Install deps
pip install -r requirements.txt

# Run Postgres locally with pgvector via Docker
docker run -e POSTGRES_PASSWORD=password -p 5432:5432 ankane/pgvector

# Run migrations
psql $DATABASE_URL -f migrations/init.sql

# Run the app
uvicorn app.main:app --reload
```

---

## Deployment (Render)

### 1. Add `render.yaml` to the root of your repo

```yaml
services:
  - type: web
    name: music-discovery-api
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: SPOTIFY_CLIENT_ID
        sync: false
      - key: SPOTIFY_CLIENT_SECRET
        sync: false
      - key: LASTFM_API_KEY
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: music-discovery-db
          property: connectionString

databases:
  - name: music-discovery-db
    plan: free
```

### 2. Enable pgvector on Render's Postgres

Render supports pgvector but it's not enabled by default. After the DB is provisioned, connect via psql and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then run the rest of your migrations from `migrations/init.sql`.

### 3. Deploy

- Push your repo to GitHub
- Go to [render.com](https://render.com) → New → Blueprint
- Point it at your repo — Render detects `render.yaml` and provisions everything automatically
- Add `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `LASTFM_API_KEY` in the Render dashboard under Environment

### Notes

- Free tier spins down after 15 minutes of inactivity — first request after idle takes ~30s. Fine for a side project; upgrade to the $7/month plan if it gets annoying.
- `DATABASE_URL` is wired automatically via `render.yaml` — don't set it manually.

---

## What to build first

1. `config.py` + `db.py` — DB connection + pgvector setup
2. `services/lastfm.py` — fetch tags + listener count, build tag vector
3. `services/embeddings.py` — normalize tag dict → fixed-size vector
4. `services/spotify.py` — search wrapper only
5. `POST /graph/seed` + `GET /recommendations/{id}` — the core loop
6. `POST /feedback` — accept/reject + steering
7. `GET /graph` + `GET /songs/search` — supporting endpoints