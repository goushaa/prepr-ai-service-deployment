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
from google.cloud import monitoring_v3

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

@app.get("/generate")
async def generate():
    """Simulates an AI generation task with 2-4s latency."""
    delay = 2 + (time.time() % 2)
    await asyncio.sleep(delay)
    return {
        "text": "This is a simulated AI response from Prepr.",
        "latency": f"{delay:.2f}s",
        "instance": INSTANCE_ID
    }

@app.get("/burst")
async def burst(duration: int = 10, rps: int = 10):
    """Fires sustained load to demonstrate auto-scaling via SSE."""
    import httpx
    
    async def event_stream():
        start_time = time.time()
        total_requests = duration * rps
        completed = 0
        instance_counts = {}
        latencies = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            while time.time() - start_time < duration:
                # Fire batch of requests for the current second
                batch = [client.get("http://localhost:8080/generate", headers={"Connection": "close"}) for _ in range(rps)]
                results = await asyncio.gather(*batch, return_exceptions=True)
                
                for r in results:
                    if not isinstance(r, Exception) and r.status_code == 200:
                        completed += 1
                        data = r.json()
                        inst = data.get("instance", "unknown")
                        instance_counts[inst] = instance_counts.get(inst, 0) + 1
                        latencies.append(float(data["latency"].replace('s','')))

                # Calculate stats
                avg_lat = sum(latencies)/len(latencies) if latencies else 0
                p95_lat = sorted(latencies)[int(len(latencies)*0.95)] if latencies else 0
                
                # Prepare payload carefully for Python 3.11 compatibility
                payload = {
                    "completed": completed,
                    "total_expected": total_requests,
                    "instance_count": len(instance_counts),
                    "avg_latency": round(avg_lat, 2),
                    "p95_latency": round(p95_lat, 2),
                    "instances": instance_counts
                }
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(1)
        
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/instances")
async def get_instance_count():
    """Queries Cloud Monitoring for official active container count."""
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "prepr-ai-service-assessment")
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"

    filter_str = (
        'resource.type = "cloud_run_revision" AND '
        'resource.labels.service_name = "prepr-ai-service" AND '
        'metric.type = "run.googleapis.com/container/instance_count"'
    )

    interval = monitoring_v3.TimeInterval()
    now = time.time()
    interval.end_time = {"seconds": int(now), "nanos": int((now % 1) * 1e9)}
    interval.start_time = {"seconds": int(now - 120), "nanos": int((now % 1) * 1e9)}

    try:
        results = client.list_time_series(
            request={
                "name": project_name,
                "filter": filter_str,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
        count = sum(p.value.int64_value for s in results for p in (s.points[:1] if s.points else []))
        return {"instance_count": max(1, count)}
    except Exception:
        return {"instance_count": 1}

STATIC_DIR = Path(__file__).parent / "static"

@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open(STATIC_DIR / "index.html", "r") as f:
        return f.read()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
