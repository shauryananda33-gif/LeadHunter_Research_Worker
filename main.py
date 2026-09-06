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
VERSION = "0.5.1"

client = SearXNGClient()


def get_configured_api_key() -> str:
    return os.getenv("WORKER_API_KEY", "").strip()


@asynccontextmanager
async def lifespan(_: FastAPI):
    api_key = get_configured_api_key()
    if not api_key:
        logger.warning("WORKER_API_KEY is not configured; /serp will remain unavailable until it is set")
    try:
        client.validate_config()
    except SearchError as exc:
        logger.warning("Search backend configuration is incomplete: %s", exc)
    logger.info("LeadHunter Research Worker %s started", VERSION)
    yield


app = FastAPI(
    title="LeadHunter Research Worker",
    version=VERSION,
    description="Authenticated SERP research API backed by dedicated SearXNG.",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class SERPRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=150)
    country: str = Field(default="in", min_length=2, max_length=10)
    language: str = Field(default="en", min_length=2, max_length=10)
    max_results: int = Field(default=10, ge=1, le=50)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_configured_api_key()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research worker authentication is not configured",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "leadhunter-research-worker",
        "version": VERSION,
        "status": "running",
        "search_backend": "searxng",
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "leadhunter-research-worker",
        "version": VERSION,
        "status": "healthy",
        "api_key_configured": bool(get_configured_api_key()),
        "search_backend_configured": bool(client.base_url),
    }


@app.post("/serp", dependencies=[Depends(require_api_key)])
async def serp(request: SERPRequest) -> dict[str, Any]:
    try:
        return await client.search(
            query=request.query.strip(),
            location=request.location,
            country=request.country,
            language=request.language,
            max_results=request.max_results,
        )
    except SearchError as exc:
        logger.warning("SERP search failed: %s", exc)
        raise HTTPException(status_code=502, detail="Search backend unavailable") from exc
    except Exception:
        logger.exception("Unexpected SERP worker failure")
        raise HTTPException(status_code=500, detail="SERP worker failed unexpectedly")
