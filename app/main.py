import asyncio
import logging
import random
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Structured logging — Cloud Logging picks this up automatically
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prepr AI Service",
    description="Minimal AI service for the Prepr Labs DevOps assessment.",
    version="1.0.0",
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Logs every request with its duration — gives us latency data in Cloud Logging."""
    request_id = str(uuid.uuid4())[:8]
    start = time.time()

    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000

    logger.info(
        "method=%s path=%s status=%d duration_ms=%.1f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health():
    """Health check — used by Cloud Run to know the container is alive."""
    return {"status": "healthy"}


@app.get("/generate")
async def generate():
    """Simulates an AI response with 1-5s latency (like calling an ML model)."""
    latency = random.uniform(1.0, 5.0)
    await asyncio.sleep(latency)

    return JSONResponse(
        content={
            "response": "This is a simulated AI-generated response.",
            "model": "kady-prepr",
            "latency_seconds": round(latency, 2),
        }
    )


# --- Landing page ---

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def landing():
    """Serves the interactive demo page for reviewers."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files (CSS, JS, etc. if needed in the future)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
