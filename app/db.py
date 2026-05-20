import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from app.config import DATABASE_URL, EMBEDDING_DIM


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


@contextmanager
def get_cursor():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def init_db():
    with get_cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS songs (
                id         SERIAL PRIMARY KEY,
                track_id   TEXT UNIQUE NOT NULL,
                name       TEXT NOT NULL,
                artist     TEXT NOT NULL,
                listeners  INTEGER,
                image      TEXT,
                embedding  vector({EMBEDDING_DIM}),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        # Migrate existing installs that used spotify_id
        cursor.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'songs' AND column_name = 'spotify_id'
                ) THEN
                    ALTER TABLE songs RENAME COLUMN spotify_id TO track_id;
                END IF;
            END $$
        """)

        cursor.execute("ALTER TABLE songs ADD COLUMN IF NOT EXISTS image TEXT")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_songs_embedding
            ON songs USING hnsw (embedding vector_cosine_ops)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_vocab (
                id  SERIAL PRIMARY KEY,
                tag TEXT UNIQUE NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id         SERIAL PRIMARY KEY,
                track_id   TEXT UNIQUE REFERENCES songs(track_id),
                is_seed    BOOLEAN DEFAULT false,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cursor.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'graph_nodes' AND column_name = 'spotify_id'
                ) THEN
                    ALTER TABLE graph_nodes RENAME COLUMN spotify_id TO track_id;
                END IF;
            END $$
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id         SERIAL PRIMARY KEY,
                source_id  TEXT REFERENCES songs(track_id),
                target_id  TEXT REFERENCES songs(track_id),
                similarity FLOAT,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_edges_source_target
            ON graph_edges(source_id, target_id)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id         SERIAL PRIMARY KEY,
                track_id   TEXT REFERENCES songs(track_id),
                action     TEXT CHECK (action IN ('accept', 'reject')),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cursor.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'feedback' AND column_name = 'spotify_id'
                ) THEN
                    ALTER TABLE feedback RENAME COLUMN spotify_id TO track_id;
                END IF;
            END $$
        """)
