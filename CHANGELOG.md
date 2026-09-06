# Changelog

## 0.5.1 — 2026-09-06
- Prevented a missing `WORKER_API_KEY` from crashing FastAPI startup.
- `/serp` remains unavailable with HTTP 503 until the required key is configured.
- Added configuration visibility to `/health` without exposing secrets.
- Kept search backend validation non-fatal at startup so Render can report service health.

## 0.5.0 — 2026-09-06
- Protected the `/serp` endpoint with required `X-API-Key` authentication.
- Disabled public API documentation endpoints.
- Added startup configuration validation.
- Removed backend error details from public API responses.
- Made Docker respect Render's `PORT` environment variable.
- Updated worker and client versioning.
