import os
import time
import uuid
import logging
import asyncio
import json
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Setup structured logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Unique ID generated once per container start
INSTANCE_ID = str(uuid.uuid4())[:8]

app = FastAPI(
    title="Prepr AI Service",
    version="1.0.0",
    swagger_ui_parameters={"defaultModelsExpandDepth": -1}
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(
        f"method={request.method} path={request.url.path} "
        f"status={response.status_code} duration_ms={process_time*1000:.1f} "
        f"request_id={request_id} instance={INSTANCE_ID}"
    )
    
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Instance-ID"] = INSTANCE_ID
    # Connection: close ensures Cloud Run load balancer distributes requests effectively
    response.headers["Connection"] = "close"
    return response

@app.get("/health")
async def health():
    """Liveness probe used by Cloud Run."""
    return {"status": "healthy", "instance": INSTANCE_ID}

@app.get("/generate", include_in_schema=False)
async def generate():
    """Simulates an AI generation task with 2-4s latency. Hidden from Swagger docs."""
    delay = 2 + (time.time() % 2)
    await asyncio.sleep(delay)
    return {
        "text": "This is a simulated AI response from Prepr.",
        "latency": f"{delay:.2f}s",
        "instance": INSTANCE_ID
    }

@app.get("/burst")
async def burst(request: Request, duration: int = 10, rps: int = 10):
    """Fires sustained load to demonstrate auto-scaling via SSE."""
    import httpx
    
    # Reconstruct the public URL so requests go through the Cloud Run Load Balancer
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost:8080"))
    scheme = request.headers.get("x-forwarded-proto", "http" if "localhost" in host else "https")
    target_url = f"{scheme}://{host}/generate"
    
    async def event_stream():
        # High concurrency limits to support burst traffic without queuing internally
        limits = httpx.Limits(max_connections=rps * 5, max_keepalive_connections=0)
        
        state = {
            "completed": 0,
            "instances": {},
            "latencies": [],
            "total_fired": 0
        }

        async def fire_one(client):
            try:
                # Connection: close forces the GFE load balancer to route new connections to new instances
                res = await client.get(target_url, headers={"Connection": "close"}, timeout=30.0)
                data = res.json()
                if "instance" in data:
                    iid = data["instance"]
                    state["instances"][iid] = state["instances"].get(iid, 0) + 1
                if "latency" in data:
                    state["latencies"].append(float(data["latency"].replace('s', '')))
            except Exception:
                pass
            finally:
                state["completed"] += 1

        async with httpx.AsyncClient(limits=limits) as client:
            start_time = time.time()
            wave = 0
            firing = True
            tasks = set()

            while firing or len(tasks) > 0:
                if await request.is_disconnected():
                    break

                if firing:
                    wave += 1
                    # Fire one wave of requests concurrently without blocking
                    for _ in range(rps):
                        t = asyncio.create_task(fire_one(client))
                        tasks.add(t)
                        t.add_done_callback(tasks.discard)
                    state["total_fired"] += rps
                    
                    if time.time() - start_time >= duration:
                        firing = False

                completed = state["completed"]
                total = state["total_fired"]
                instances = state["instances"]
                latencies = state["latencies"]
                avg = sum(latencies) / len(latencies) if latencies else 0
                
                if latencies:
                    lat_sorted = sorted(latencies)
                    p95 = lat_sorted[int(len(lat_sorted) * 0.95)]
                else:
                    p95 = 0

                payload = {
                    "completed": completed,
                    "total_expected": duration * rps,
                    "instance_count": len(instances),
                    "avg_latency": round(avg, 2),
                    "p95_latency": round(p95, 2),
                    "instances": instances
                }
                
                yield f"data: {json.dumps(payload)}\n\n"

                # Accurate 1-second ticks
                if firing:
                    elapsed = time.time() - start_time
                    wait = wave - elapsed
                    if wait > 0:
                        await asyncio.sleep(min(wait, 1.0))
                else:
                    await asyncio.sleep(1.0)
        
        if not await request.is_disconnected():
            yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open(STATIC_DIR / "index.html", "r") as f:
        return f.read()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
