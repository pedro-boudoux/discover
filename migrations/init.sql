CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS songs (
    id         SERIAL PRIMARY KEY,
    track_id   TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    artist     TEXT NOT NULL,
    listeners  INTEGER,
    image      TEXT,
    embedding  vector(300),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_songs_embedding
    ON songs USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS tag_vocab (
    id  SERIAL PRIMARY KEY,
    tag TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id         SERIAL PRIMARY KEY,
    track_id   TEXT UNIQUE REFERENCES songs(track_id),
    is_seed    BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id         SERIAL PRIMARY KEY,
    source_id  TEXT REFERENCES songs(track_id),
    target_id  TEXT REFERENCES songs(track_id),
    similarity FLOAT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_edges_source_target
    ON graph_edges(source_id, target_id);

CREATE TABLE IF NOT EXISTS feedback (
    id         SERIAL PRIMARY KEY,
    track_id   TEXT REFERENCES songs(track_id),
    action     TEXT CHECK (action IN ('accept', 'reject')),
    created_at TIMESTAMPTZ DEFAULT now()
);
