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

Required environment variable:

```text
GOOGLE_API_KEY=<server-side Google Places API key>
```

Never place the Google key in GitHub Pages frontend code or commit it to the repository.

## Design

The first backend version performs discovery through Google Places, server-side website inspection, conservative business-specific email extraction, automation-signal detection, and explainable 0-100 opportunity scoring. Discovery is intentionally isolated from the frontend so additional compliant sources can be added later without rebuilding the UI.
