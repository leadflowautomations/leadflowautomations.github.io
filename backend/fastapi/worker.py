"""Lead Flow worker process entrypoint.

The Render worker service currently uses a Python module start command. Keep the
entrypoint lightweight and compatible with the existing FastAPI application so
the service can boot cleanly while the durable job executor is attached to the
same application lifecycle.
"""

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "backend.fastapi.leadflow_v3:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        log_level="info",
    )
