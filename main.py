from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from serp_worker.searxng import SearchError, SearXNGClient

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("leadhunter-research-worker")

VERSION = "0.4.0"

app = FastAPI(
    title="LeadHunter Research Worker",
    version=VERSION,
    description="SERP research API backed by a dedicated SearXNG service.",
)

client = SearXNGClient()


class SERPRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=150)
    country: str = Field(default="in", min_length=2, max_length=10)
    language: str = Field(default="en", min_length=2, max_length=10)
    max_results: int = Field(default=10, ge=1, le=50)


@app.get("/")
async def root() -> dict[str, Any]:
    return {"ok": True, "service": "leadhunter-research-worker", "version": VERSION, "status": "running", "search_backend": "searxng"}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "leadhunter-research-worker", "version": VERSION, "status": "healthy"}


@app.post("/serp")
async def serp(request: SERPRequest) -> dict[str, Any]:
    try:
        return await client.search(query=request.query.strip(), location=request.location, country=request.country, language=request.language, max_results=request.max_results)
    except SearchError as exc:
        logger.warning("SERP search failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        logger.exception("Unexpected SERP worker failure")
        raise HTTPException(status_code=500, detail="SERP worker failed unexpectedly")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
