from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from serp_worker.searxng import SearchError, SearXNGClient

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("leadhunter-research-worker")
VERSION = "0.5.0"


def get_api_key() -> str:
    value = os.getenv("WORKER_API_KEY", "").strip()
    if not value:
        raise RuntimeError("WORKER_API_KEY is required")
    return value


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_api_key()
    client.validate_config()
    logger.info("LeadHunter Research Worker %s started", VERSION)
    yield


app = FastAPI(title="LeadHunter Research Worker", version=VERSION, description="Authenticated SERP research API backed by dedicated SearXNG.", lifespan=lifespan, docs_url=None, redoc_url=None)
client = SearXNGClient()


class SERPRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=150)
    country: str = Field(default="in", min_length=2, max_length=10)
    language: str = Field(default="en", min_length=2, max_length=10)
    max_results: int = Field(default=10, ge=1, le=50)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_api_key()
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.get("/")
async def root() -> dict[str, Any]:
    return {"ok": True, "service": "leadhunter-research-worker", "version": VERSION, "status": "running", "search_backend": "searxng"}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "leadhunter-research-worker", "version": VERSION, "status": "healthy"}


@app.post("/serp", dependencies=[Depends(require_api_key)])
async def serp(request: SERPRequest) -> dict[str, Any]:
    try:
        return await client.search(query=request.query.strip(), location=request.location, country=request.country, language=request.language, max_results=request.max_results)
    except SearchError as exc:
        logger.warning("SERP search failed: %s", exc)
        raise HTTPException(status_code=502, detail="Search backend unavailable") from exc
    except Exception:
        logger.exception("Unexpected SERP worker failure")
        raise HTTPException(status_code=500, detail="SERP worker failed unexpectedly")
