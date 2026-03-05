import asyncio
import logging
import os
import random
import time
import uuid
from pathlib import Path

import json
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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


from starlette.concurrency import run_in_threadpool

def _cpu_bound_task(duration: float):
    """Simulates real ML ML CPU load without sleeping."""
    start = time.time()
    while time.time() - start < duration:
        pass

@app.get("/generate")
async def generate():
    """Simulates an AI response with 2-4s latency (ML CPU load)."""
    latency = random.uniform(2.0, 4.0)
    # Run CPU intensive task in a background thread to avoid blocking FastAPI
    await run_in_threadpool(_cpu_bound_task, latency)

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

    async def event_stream():
        limits = httpx.Limits(max_connections=rps * 5, max_keepalive_connections=rps * 5)
        
        state = {
            "completed": 0,
            "errors": 0,
            "instances": {},
            "latencies": [],
            "total_fired": 0
        }

        async def fire_one(client):
            try:
                res = await client.get(target, timeout=30.0)
                data = res.json()
                if "instance_id" in data:
                    iid = data["instance_id"]
                    state["instances"][iid] = state["instances"].get(iid, 0) + 1
                if "latency_seconds" in data:
                    state["latencies"].append(data["latency_seconds"])
            except Exception as e:
                state["errors"] += 1
            finally:
                state["completed"] += 1

        async with httpx.AsyncClient(limits=limits) as client:
            start_time = time.time()
            wave = 0
            firing = True
            tasks = set()

            # Loop while we are still supposed to fire OR we have pending requests
            while firing or len(tasks) > 0:
                if await request.is_disconnected():
                    # Stop if client disconnects
                    break

                if firing:
                    wave += 1
                    # Fire one wave of requests
                    for _ in range(rps):
                        t = asyncio.create_task(fire_one(client))
                        tasks.add(t)
                        t.add_done_callback(tasks.discard)
                    state["total_fired"] += rps
                    
                    if time.time() - start_time >= duration:
                        firing = False

                # Calc stats to stream
                completed = state["completed"]
                total = state["total_fired"]
                instances = state["instances"]
                latencies = state["latencies"]
                avg = sum(latencies) / len(latencies) if latencies else 0
                
                # Fast p95 calc
                if latencies:
                    lat_sorted = sorted(latencies)
                    p95 = lat_sorted[int(len(lat_sorted) * 0.95)]
                else:
                    p95 = 0

                update_data = {
                    "type": "update",
                    "completed": completed,
                    "total_expected": duration * rps,
                    "errors": state["errors"],
                    "instances": instances,
                    "instance_count": len(instances),
                    "avg_latency": round(avg, 2),
                    "p95_latency": round(p95, 2)
                }
                
                yield f"data: {json.dumps(update_data)}\n\n"

                # Wait for next tick (~1 second)
                if firing:
                    elapsed = time.time() - start_time
                    wait = wave - elapsed
                    if wait > 0:
                        await asyncio.sleep(min(wait, 1.0))
                else:
                    await asyncio.sleep(1.0)

            # Final success message
            if not await request.is_disconnected():
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- Landing page ---

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def landing():
    """Serves the interactive demo page for reviewers."""
    return FileResponse(STATIC_DIR / "index.html")


# Mount static files (CSS, JS, etc. if needed in the future)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
