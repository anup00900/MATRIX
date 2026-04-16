from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import r
from .logging import configure_logging
from .storage.db import init_db

configure_logging()
init_db()

app = FastAPI(title="Matrix PoC")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(r)


@app.get("/health")
def health():
    return {"ok": True}
