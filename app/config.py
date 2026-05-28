import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/music_db")

STEERING_ALPHA = 0.3
MAX_LISTENERS = 500000
DEFAULT_K = 10
EMBEDDING_DIM = 300
MMR_LAMBDA = 0.7         # relevance vs diversity tradeoff (1.0 = pure relevance, 0.0 = pure diversity)
MMR_POOL_MULTIPLIER = 3  # fetch this many × k candidates before re-ranking
MMR_MAX_PER_ARTIST = 2   # max tracks per artist in the MMR candidate pool