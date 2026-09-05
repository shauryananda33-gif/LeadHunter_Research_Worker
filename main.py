import logging
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from serp_worker.scraper import GoogleSERPScraper, SERPError

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("leadhunter-research-worker")

app = FastAPI(title="LeadHunter Research Worker", description="Standalone research worker for LeadHunter.", version="0.1.0")

class SERPRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    location: Optional[str] = Field(default=None, max_length=150)
    country: str = Field(default="in", min_length=2, max_length=5)
    language: str = Field(default="en", min_length=2, max_length=10)
    max_results: int = Field(default=10, ge=1, le=50)

@app.get("/")
def root():
    return {"ok": True, "service": "leadhunter-research-worker", "version": "0.1.0"}

@app.get("/health")
def health():
    return {"ok": True, "service": "leadhunter-research-worker", "status": "healthy"}

@app.post("/serp")
def serp(request: SERPRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query cannot be empty")
    try:
        results = GoogleSERPScraper().search(query=query, location=request.location, country=request.country, language=request.language, max_results=request.max_results)
        return {"ok": True, "query": query, "location": request.location, "country": request.country, "language": request.language, "result_count": len(results), "results": results}
    except SERPError as exc:
        logger.warning("SERP failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected SERP worker failure")
        raise HTTPException(status_code=500, detail="SERP worker failed unexpectedly") from exc
