# LeadHunter Research Worker

Standalone research worker for LeadHunter.

## Version 0.1

This first version focuses on Google organic SERP collection using Playwright.

### Endpoints

- `GET /` service information
- `GET /health` health check
- `POST /serp` Google organic search
- `GET /docs` Swagger API documentation

### SERP request

```json
{
  "query": "dentist",
  "location": "Indore",
  "country": "in",
  "language": "en",
  "max_results": 10
}
```

### Local run

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --host 0.0.0.0 --port 10000
```

Google markup can change and Google may rate-limit or challenge automated requests. This worker does not attempt to bypass CAPTCHA or security controls.

### Roadmap

1. Google organic SERP
2. Google Maps / Business Profile
3. Reviews
4. Photos
5. Website crawling
6. SEO
7. Conversion analysis
8. Social profiles
9. Directories/platforms
10. Citation consistency
11. Competitors
12. Buying signals
13. Evidence storage
14. AI analysis
15. Qualification
16. Sales recommendation
