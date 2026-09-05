# LeadHunter Research Worker

A standalone research worker for the LeadHunter platform.

The first version focuses on Google organic SERP collection using
Playwright.

## Current scope

This version provides:

- FastAPI service
- Google organic search
- Playwright Chromium
- Structured SERP results
- Query support
- Location support
- Country/language support
- Result ranking
- Result title
- Result URL
- Result domain
- Result snippet
- Health endpoint
- Docker deployment
- Render deployment configuration

## Architecture

```text
LeadHunter
    |
    | HTTP
    v
Research Worker
    |
    +-- Google SERP
    |
    +-- future: Google Maps / GBP
    |
    +-- future: Website crawler
    |
    +-- future: Reviews
    |
    +-- future: Competitors
    |
    +-- future: Citations
    |
    +-- future: Evidence analysis
