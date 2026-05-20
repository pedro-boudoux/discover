import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from pgvector.psycopg2 import register_vector
from app.config import DATABASE_URL, EMBEDDING_DIM


def get_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    register_vector(conn)
    return conn


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


def _try(sql):
    """Run a DDL statement in its own transaction, silently ignoring errors."""
    try:
        with get_cursor() as cursor:
            cursor.execute(sql)
    except Exception:
        pass


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
            CREATE TABLE IF NOT EXISTS graph_edges (
                id         SERIAL PRIMARY KEY,
                source_id  TEXT REFERENCES songs(track_id),
                target_id  TEXT REFERENCES songs(track_id),
                similarity FLOAT,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id         SERIAL PRIMARY KEY,
                track_id   TEXT REFERENCES songs(track_id),
                action     TEXT CHECK (action IN ('accept', 'reject')),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

    # Migrations — each runs in its own transaction so one failure doesn't block the rest
    _try("ALTER TABLE songs RENAME COLUMN spotify_id TO track_id")
    _try("ALTER TABLE graph_nodes RENAME COLUMN spotify_id TO track_id")
    _try("ALTER TABLE feedback RENAME COLUMN spotify_id TO track_id")
    _try("ALTER TABLE songs ADD COLUMN IF NOT EXISTS image TEXT")

    # Ensure unique constraints and indexes exist regardless of how the table was created
    _try("CREATE UNIQUE INDEX IF NOT EXISTS songs_track_id_unique ON songs(track_id)")
    _try("CREATE UNIQUE INDEX IF NOT EXISTS graph_nodes_track_id_unique ON graph_nodes(track_id)")
    _try("CREATE INDEX IF NOT EXISTS idx_songs_embedding ON songs USING hnsw (embedding vector_cosine_ops)")
    _try("CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_edges_source_target ON graph_edges(source_id, target_id)")
