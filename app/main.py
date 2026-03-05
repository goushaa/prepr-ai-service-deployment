import asyncio
import logging
import os
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

# Unique ID for this instance — generated once at startup.
# If Cloud Run scales to 3 instances, there will be 3 different INSTANCE_IDs.
INSTANCE_ID = os.environ.get("K_REVISION", str(uuid.uuid4())[:8])

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
        "method=%s path=%s status=%d duration_ms=%.1f request_id=%s instance=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
        INSTANCE_ID,
    )

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Instance-ID"] = INSTANCE_ID
    return response


@app.get("/health")
async def health():
    """Health check — used by Cloud Run to know the container is alive."""
    return {"status": "healthy", "instance_id": INSTANCE_ID}


@app.get("/generate")
async def generate():
    """Simulates an AI response with 0.5-1.5s latency (like calling an ML model)."""
    latency = random.uniform(0.5, 1.5)
    await asyncio.sleep(latency)

    return JSONResponse(
        content={
            "response": "This is a simulated AI-generated response.",
            "model": "kady-prepr",
            "latency_seconds": round(latency, 2),
            "instance_id": INSTANCE_ID,
        }
    )


# --- Burst test (server-side load testing) ---

@app.get("/burst")
async def burst(count: int = 50, request: Request = None):
    """Fires N concurrent requests through the load balancer to trigger auto-scaling."""
    count = min(count, 200)  # Safety cap

    # On Cloud Run, TLS terminates at the load balancer so the app sees http://localhost.
    # Use forwarded headers to reconstruct the public URL that goes through the LB.
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost:8080"))
    scheme = request.headers.get("x-forwarded-proto", "http")
    target = f"{scheme}://{host}/generate"

    results = []

    async def fire_one(client):
        try:
            res = await client.get(target, timeout=30.0)
            return res.json()
        except Exception as e:
            return {"error": str(e)}

    async with __import__("httpx").AsyncClient() as client:
        tasks = [fire_one(client) for _ in range(count)]
        results = await asyncio.gather(*tasks)

    # Aggregate results
    instances = {}
    latencies = []
    errors = 0

    for r in results:
        if "error" in r:
            errors += 1
        else:
            if "instance_id" in r:
                iid = r["instance_id"]
                instances[iid] = instances.get(iid, 0) + 1
            if "latency_seconds" in r:
                latencies.append(r["latency_seconds"])

    latencies.sort()
    avg = sum(latencies) / len(latencies) if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    return {
        "total": count,
        "successful": count - errors,
        "errors": errors,
        "instance_count": len(instances),
        "instances": instances,
        "avg_latency": round(avg, 2),
        "p95_latency": round(p95, 2),
    }


# --- Landing page ---

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def landing():
    """Serves the interactive demo page for reviewers."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files (CSS, JS, etc. if needed in the future)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
