# Lead Flow FastAPI Backend

Hosted backend for Lead Flow. The existing GitHub Pages frontend remains unchanged.

## API

- `GET /health`
- `GET /scan?city=Miami&industry=real%20estate&country=US`
- `GET /docs`

## Render

Use the repository's `backend/fastapi` directory as the Render Root Directory, or deploy from `render.yaml`.

Build:

```bash
pip install -r requirements.txt
```

Start:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

No Google Cloud account or API key is required.

## Discovery

The hosted backend uses OpenStreetMap data through Nominatim and Overpass for location/category discovery, then performs server-side website inspection and conservative business-specific email extraction. It detects lead forms, booking, chat/AI, analytics, HTTPS, response time and website health, then produces an explainable 0-100 opportunity score.

Discovery is intentionally isolated from the frontend so additional compliant sources can be added later without rebuilding the UI.
