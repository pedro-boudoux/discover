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

CREATE TABLE tag_vocab (
    id      SERIAL PRIMARY KEY,
    tag     TEXT UNIQUE NOT NULL
);

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

CREATE TABLE feedback (
    id          SERIAL PRIMARY KEY,
    spotify_id  TEXT REFERENCES songs(spotify_id),
    action      TEXT CHECK (action IN ('accept', 'reject')),
    created_at  TIMESTAMPTZ DEFAULT now()
);