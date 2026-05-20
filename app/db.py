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
                id SERIAL PRIMARY KEY,
                spotify_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                artist TEXT NOT NULL,
                listeners INTEGER,
                image TEXT,
                embedding vector({EMBEDDING_DIM}),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cursor.execute("ALTER TABLE songs ADD COLUMN IF NOT EXISTS image TEXT")

        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_songs_embedding
            ON songs USING hnsw (embedding vector_cosine_ops)
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tag_vocab (
                id SERIAL PRIMARY KEY,
                tag TEXT UNIQUE NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id SERIAL PRIMARY KEY,
                spotify_id TEXT UNIQUE REFERENCES songs(spotify_id),
                is_seed BOOLEAN DEFAULT false,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id SERIAL PRIMARY KEY,
                source_id TEXT REFERENCES songs(spotify_id),
                target_id TEXT REFERENCES songs(spotify_id),
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
                id SERIAL PRIMARY KEY,
                spotify_id TEXT REFERENCES songs(spotify_id),
                action TEXT CHECK (action IN ('accept', 'reject')),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """)