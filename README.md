# LeadHunter Research Worker v0.2.1

This version intentionally keeps the complete search implementation inside
`main.py`. This prevents Render deployment problems caused by a missing
Python package directory.

The worker uses SearXNG over HTTP instead of direct Google Playwright
scraping because the Render IP was challenged by Google.

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

Set `SEARXNG_URL` to a private/self-hosted SearXNG instance for production.
The included public instance is only for initial testing.
