# Prepr AI Service: Architecture Assessment

## 1. Architecture

- **Where the service runs:** GCP Cloud Run. It runs Docker containers without any cluster or server management. No nodes to patch, no Kubernetes to maintain. A 1-2 person team can operate it without infrastructure overhead.

- **How it scales:** Cloud Run scales horizontally based on concurrent requests per instance. Config: `min_instances=2` (always warm), `max_instances=8` (cost ceiling), `concurrency=80` (requests per container). When concurrent requests on an instance approach 80, a new container spins up. During a 150 req/sec burst where each request takes ~3s, roughly 450 requests are in flight, so Cloud Run scales to about 6 instances.

- **How traffic reaches it:** Requests go through Google Front End (GFE), which is Cloud Run's built-in load balancer. It handles TLS termination, distributes connections across instances, and queues requests briefly during scale-up. No separate load balancer to provision or pay for.

- **How to deploy updates safely:** GitHub Actions CI/CD. Push to `main` triggers: authenticate to GCP, build Docker image tagged with commit SHA, push to Artifact Registry, deploy as a new Cloud Run revision. Cloud Run supports traffic splitting natively, so canary rollouts (e.g. send 10% of traffic to the new revision) are available if needed.

- **How to monitor:** Cloud Run exposes built-in metrics: request latency (p50/p95/p99), request count by status code, instance count, and CPU utilization. Two alert policies are defined in Terraform: one fires if p95 latency exceeds 2.5s (giving a buffer before the 3s SLA), another fires if server errors (5xx) spike, catching issues like container crashes or overloaded instances. Application logs with request IDs flow to Cloud Logging automatically.

## 2. Key Decisions

1. **Chose GCP Cloud Run over EKS, EC2+ASG, ECS Fargate, and Lambda.**
   - EKS / EC2+ASG: Too much operational overhead for 1-2 engineers running one service.
   - Lambda: At 20 req/sec steady, per-invocation billing gets expensive. Cold starts also risk blowing the p95 target.
   - ECS Fargate: Scales on CPU/memory thresholds with 1-3 minute reaction time. Cloud Run scales on concurrent requests in seconds, which is a much better fit for an I/O-bound service where CPU stays low but connections stack up. Fargate also requires a separate Application Load Balancer (~$18/month + data processing fees), while Cloud Run includes load balancing at no extra cost.
   - *I am AWS-native (Terraform, EC2, EKS across three internships), but chose GCP because Cloud Run is the right tool here. Built this using the $300 free trial to show I can adapt quickly.*

2. **Chose min_instances=2 over scale-to-zero.** The service handles 20 req/sec constantly. Scaling to zero would cause 2-5 second cold starts when traffic returns, which alone could break the p95 < 3s target.

3. **Chose a conservative concurrency limit (80 per instance).** A lower concurrency limit means Cloud Run starts adding new instances earlier during a burst, before existing ones get overwhelmed. This trades a slightly higher instance count for better burst absorption and more predictable latency.

4. **Chose "Always Allocated" CPU over "Request-Only" CPU.** At 20 req/sec steady, the instances are busy constantly anyway. Request-only billing would cost nearly the same but with slower cold starts and CPU throttling between requests.

5. **Chose built-in Cloud Run monitoring over Prometheus/Grafana or Datadog.** Cloud Run already exposes latency percentiles, error rates, and instance counts. Adding a separate observability stack to monitor one service would be over-engineering. At 10+ services, a centralized stack would make sense.

6. **Chose GitHub Actions over Cloud Build or Jenkins.** Code lives on GitHub already. One fewer system to maintain. Jenkins would require a server. Cloud Build would add GCP lock-in for no benefit.

## 3. Debugging Scenario

**The scenario:** `/generate` starts timing out during traffic bursts (150 req/sec).

**What I would check first:**
Cloud Run metrics dashboard. The key question: did instances scale up fast enough to handle the burst? I would compare Container Instance Count against Concurrent Requests over time to spot any gap between demand and available capacity.

**What signals/metrics I would look at:**
- `request_latencies` (p95) to confirm timeouts and measure how bad they are
- `container/instance_count` to see when new containers started spinning up
- `request_count` by response code to tell apart slow responses (504 timeout) from rejected requests (429/503)
- `container/cpu/utilization` to check if instances are maxing out on compute or just holding open connections

**Most likely cause and reasoning:**
At 150 req/sec with each request taking ~3 seconds, about 450 requests are in flight at the same time. At concurrency=80, Cloud Run needs about 6 instances to handle that load. The problem: only 2 instances are warm at steady state. So when the burst hits, Cloud Run has to cold-start 4 new containers. That takes several seconds. During that gap, the 2 existing instances receive far more traffic than they can handle, the load balancer starts queuing the overflow, and queued requests begin timing out.

**How to fix it:**
- If bursts are predictable (campaigns, scheduled jobs): raise `min_instances` to 4-5 so more capacity is already warm when the burst arrives.
- If bursts are unpredictable: lower the concurrency limit so scaling triggers even earlier, trading slightly higher cost for faster burst absorption.
- If the problem persists after scaling adjustments: check per-instance CPU utilization. If CPU is near 100%, the application itself is the bottleneck and needs more workers or lower concurrency.

## 4. Live Deployment & IaC

Instead of a rough snippet, I built and deployed the full service. This is my first time using GCP. I used the $300 new-account free trial credits.

**Live Demo:** [https://prepr-ai-service-ulgop5h7uq-uc.a.run.app/](https://prepr-ai-service-ulgop5h7uq-uc.a.run.app/)

**GitHub Repo:** [https://github.com/goushaa/prepr-ai-service-deployment](https://github.com/goushaa/prepr-ai-service-deployment)

The demo includes an interactive UI where you can hit the endpoints, run stress tests (10s, 30s, 60s), and watch Cloud Run scale out in real time with per-container IDs.

**How the service runs:**
Cloud Run pulls the Docker image from Artifact Registry and runs it as a container. The image is a Python 3.12-slim base running a single uvicorn process that serves the FastAPI app on port 8080. Cloud Run handles everything outside the container: TLS, routing, health checks, and instance lifecycle.

```hcl
containers {
  image = var.image
  ports {
    container_port = 8080
  }
  resources {
    limits = {
      cpu    = "1"
      memory = "512Mi"
    }
    cpu_idle = false  # Always-allocated CPU
  }
}
```

**How scaling is configured:**
Two warm instances handle steady-state traffic. When concurrent requests on any instance approach 80, Cloud Run adds containers up to a maximum of 8. This keeps latency stable during bursts while capping cost.

```hcl
scaling {
  min_instance_count = 2  # Always warm, no cold starts at steady state
  max_instance_count = 8  # Cost ceiling
}
max_instance_request_concurrency = 80  # Scale out before instances are overwhelmed
```

**A note on the demo numbers:** The live demo uses `concurrency=15` and `min_instances=1`, intentionally set low so scaling kicks in earlier and you can visually see new containers appear during small tests. The production numbers above are what I would deploy for the real workload.
