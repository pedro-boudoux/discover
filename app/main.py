from fastapi import FastAPI
from app.db import init_db
from app.routers import songs, graph, recommendations, feedback

app = FastAPI(title="Underground Music Discovery")

app.include_router(songs.router)
app.include_router(graph.router)
app.include_router(recommendations.router)
app.include_router(feedback.router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}