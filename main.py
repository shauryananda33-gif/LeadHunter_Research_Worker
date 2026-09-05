from __future__ import annotations
import logging, os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from search_worker.searxng import SearchError, SearXNGClient

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="LeadHunter Research Worker", version="0.2.0",
             description="Standalone research worker for LeadHunter.")
client = SearXNGClient()

class SERPRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=150)
    country: str = Field(default="in", min_length=2, max_length=10)
    language: str = Field(default="en", min_length=2, max_length=10)
    max_results: int = Field(default=10, ge=1, le=50)

@app.get("/")
async def root():
    return {"ok": True, "service": "leadhunter-research-worker",
            "version": "0.2.0", "search_backend": "searxng", "status": "running"}

@app.get("/health")
async def health():
    return {"ok": True, "service": "leadhunter-research-worker",
            "status": "healthy", "search_backend": "searxng"}

@app.post("/serp")
async def serp(request: SERPRequest):
    try:
        return await client.search(
            query=request.query.strip(), location=request.location,
            country=request.country, language=request.language,
            max_results=request.max_results)
    except SearchError as exc:
        logger.warning("SERP search failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        logger.exception("Unexpected SERP worker failure")
        raise HTTPException(status_code=500, detail="SERP worker failed unexpectedly")
