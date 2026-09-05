# LeadHunter Research Worker v0.4.0

Dedicated FastAPI SERP research service backed by LeadHunter SearXNG.

## Architecture

```text
LeadHunter / Dashboard / Bot
          |
          v
Research Worker (public API)
          |
          | authenticated HTTPS on free Render
          v
LeadHunter SearXNG
          |
          v
Search engines
```

The worker does not scrape Google directly.

## API

`GET /health`

`POST /serp`

```json
{"query":"dentist","location":"Indore","country":"in","language":"en","max_results":10}
```

## Render setup

Deploy `LeadHunter_SearXNG` first. Copy its Render URL and generated `SEARX_AUTH_PASSWORD`, then set these variables here:

- `SEARXNG_URL=https://YOUR-SEARXNG.onrender.com`
- `SEARXNG_AUTH_USER=leadhunter`
- `SEARXNG_AUTH_PASSWORD=<generated password>`

Keep both services in the same Render region. If you later use a paid Render plan with a private SearXNG service, replace the public URL with its internal address.

## Verification

```bash
curl https://YOUR-WORKER.onrender.com/health
curl -X POST https://YOUR-WORKER.onrender.com/serp -H 'content-type: application/json' -d '{"query":"dentist","location":"Indore","max_results":5}'
```

Do not connect the production LeadHunter app until `/serp` returns real search results.
