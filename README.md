# LeadHunter Research Worker v0.2.0

The SERP backend now uses SearXNG over HTTP instead of direct Google Playwright scraping.

## Test

POST `/serp`:

```json
{
  "query": "dentist",
  "location": "Indore",
  "country": "in",
  "language": "en",
  "max_results": 10
}
```

## Configuration

`SEARXNG_URL` controls the backend. The included Render configuration uses
`https://searx.tiekoetter.com` for initial testing.

Public SearXNG instances can change availability, rate limits, enabled formats,
and upstream engines. For long-term production, run your own SearXNG instance
and point `SEARXNG_URL` to it.

This worker does not bypass CAPTCHA, rate limits, or security controls.
