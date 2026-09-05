# LeadHunter Research Worker

Standalone research worker for LeadHunter.

## Version

0.1.1

## Current capability

- Google organic SERP scraping
- Playwright Chromium
- India/local query support
- Multiple extraction strategies
- URL normalization
- Deduplication
- Google challenge detection
- Structured JSON responses

## Endpoints

- `GET /`
- `GET /health`
- `POST /serp`
- `GET /docs`

## Test request

```json
{
  "query": "dentist",
  "location": "Indore",
  "country": "in",
  "language": "en",
  "max_results": 10
}
```

## Important

This worker does not bypass CAPTCHA, rate limits, or security challenges.
