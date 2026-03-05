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
def generate():
    """Simulates an AI response with 2-4s latency (blocking, like real ML inference)."""
    latency = random.uniform(2.0, 4.0)
    time.sleep(latency)  # Blocking sleep — simulates real CPU-bound ML processing

    return JSONResponse(
        content={
            "response": "This is a simulated AI-generated response.",
            "model": "kady-prepr",
            "latency_seconds": round(latency, 2),
            "instance_id": INSTANCE_ID,
        }
    )


# --- Load test (sustained server-side load to trigger auto-scaling) ---

@app.get("/burst")
async def burst(duration: int = 30, rps: int = 20, request: Request = None):
    """Fires sustained load for N seconds to trigger auto-scaling.
    
    Args:
        duration: How long to sustain load (seconds, max 60)
        rps: Requests per second to fire (max 50)
    """
    duration = min(duration, 60)
    rps = min(rps, 50)

    # Reconstruct the public URL (Cloud Run TLS terminates at load balancer)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost:8080"))
    scheme = request.headers.get("x-forwarded-proto", "http")
    target = f"{scheme}://{host}/generate"

    import httpx
    all_results = []
    limits = httpx.Limits(max_connections=rps * 5, max_keepalive_connections=rps * 5)

    async def fire_one(client):
        try:
            res = await client.get(target, timeout=30.0)
            return res.json()
        except Exception as e:
            return {"error": str(e)}

    async with httpx.AsyncClient(limits=limits) as client:
        start_time = time.time()
        wave = 0

        # Fire waves of requests every second for the specified duration
        while time.time() - start_time < duration:
            wave += 1
            tasks = [fire_one(client) for _ in range(rps)]
            results = await asyncio.gather(*tasks)
            all_results.extend(results)
            
            # Wait 1 second before next wave (minus time already spent)
            elapsed = time.time() - start_time
            wait = wave - elapsed
            if wait > 0:
                await asyncio.sleep(wait)

    # Aggregate results
    instances = {}
    latencies = []
    errors = 0

    for r in all_results:
        if "error" in r:
            errors += 1
        else:
            if "instance_id" in r:
                iid = r["instance_id"]
                instances[iid] = instances.get(iid, 0) + 1
            if "latency_seconds" in r:
                latencies.append(r["latency_seconds"])

    latencies.sort()
    total = len(all_results)
    avg = sum(latencies) / len(latencies) if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    return {
        "total": total,
        "successful": total - errors,
        "errors": errors,
        "duration_seconds": duration,
        "waves": wave,
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
