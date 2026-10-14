from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from .api.routes import router
from .api.ai_routes import router as ai_router
from .database import engine
from .init_db import initialize_schema

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Upgrade only recorded, pending revisions; tests use isolated SQLite.
    if os.getenv("FORGEIQ_DISABLE_STARTUP_DB") != "1":
        initialize_schema()
    yield


app = FastAPI(title="ForgeIQ API", version="1.0.0", description="Manual manufacturing scheduling, comparisons and deterministic recommendations.", docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Accept"])
app.include_router(router)
app.include_router(ai_router)


@app.get("/api/health")
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "service": "forgeiq-api", "database": "connected"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "service": "forgeiq-api", "detail": "Database connection could not be established."})


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
assets_dir = frontend_dist / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")


@app.get("/{path:path}", include_in_schema=False)
def serve_frontend(path: str):
    if path.startswith(("api/", "docs", "redoc", "openapi.json")):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    candidate = (frontend_dist / path).resolve()
    try:
        candidate.relative_to(frontend_dist.resolve())
    except ValueError:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if candidate.is_file():
        return FileResponse(candidate)
    index = frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(status_code=503, content={"detail": "Frontend build is not available. Run pnpm build from the project root."})
