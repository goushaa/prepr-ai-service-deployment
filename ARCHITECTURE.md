# Prepr AI Service: Architecture Assessment

## 1. Architecture

* **Where the service runs (Compute):** GCP Cloud Run. It is a fully managed, serverless platform that natively runs Docker containers. It is perfectly optimized for stateless APIs experiencing variable traffic patterns and I/O-bound workloads.
* **How it scales:** Scaling is triggered by concurrent requests per instance. We use a "Warm Minimum + Moderate Concurrency" strategy (min instances: 2, max instances: 8, concurrency: 80). When active concurrent requests on an instance exceed 80, a new container is provisioned.
* **How traffic reaches it:** Traffic routes through the Google Front End (GFE) load balancer, which terminates HTTPS and distributes connections across active instances. The service uses IAM to allow unauthenticated invocations, acting as a public REST API.
* **How to deploy updates safely:** A GitHub Actions CI/CD pipeline. Pushes to the main branch authenticate via a Service Account, build the Docker image, push it to Google Artifact Registry, and deploy an immutable new Revision to Cloud Run. Traffic cuts over instantly.
* **How to monitor:** Cloud Monitoring tracks the `run.googleapis.com/request_latencies` metric. Alert policies notify the team if the p95 latency consistently exceeds 2.5 seconds over a 60-second window, providing a buffer before breaching the 3-second SLA. We also constantly monitor the 5xx error rate.

## 2. Key Decisions

* **Chose GCP Cloud Run over AWS ECS Fargate, EKS, EC2+ASG, or Lambda because:**
  * vs. EKS or EC2+ASG: Managing Kubernetes clusters or EC2 nodes introduces too much operational overhead for a 1 to 2 person team maintaining this service.
  * vs. Lambda: A steady state of 20 requests per second makes per-invocation billing expensive.
  * vs. ECS Fargate: Fargate scales primarily on CPU/Memory thresholds. Cloud Run's concurrency-aware scaling is far superior and faster for async, I/O-bound FastAPI services.
  * *Note:* I am an AWS native, but chose to build this on Cloud Run using the $300 GCP free trial credits to demonstrate rapid adaptability to Prepr's production stack. It is genuinely the right tool for the job.
* **Chose Strategy B (Warm Minimum 2) over Scale-to-Zero (min 0) because:** A steady 20 requests/second workload means the API is constantly serving traffic. Scaling to zero would cause 2 to 5 second cold starts, completely destroying the p95 < 3s target constraint on the very first request of an idle period.
* **Chose Conservative Concurrency (80) over High Concurrency (250) because:** While async Python can handle 250 concurrent I/O requests, 80 provides a smaller blast radius if a future feature adds real computational workload. It also leaves plenty of CPU headroom for request overhead like JSON serialization. This triggers scaling early enough to stay ahead of bursts.
* **Chose "Always Allocated" CPU over "Request-Only" because:** At a steady 20 requests/second, the instances are constantly processing anyway. Request-only billing would charge for essentially all the time but with the downside of slower cold starts and no background processing. Always-allocated CPU provides faster cold starts when scaling up and prevents CPU throttling during background tasks.

## 3. Debugging Scenario

**The Scenario:** The `/generate` endpoint starts timing out during traffic bursts (150 requests/sec).

* **What would I check first?**
  I would check the Cloud Run Revision Metrics dashboard, looking specifically at the "Container Instance Count" versus "Active Requests" graphs. I would also review Cloud Logging for HTTP 429 (Too Many Requests) or 504 (Gateway Timeout) errors.
* **What signals/metrics would I look at?**
  I would monitor the rate of incoming concurrent requests versus our configured `max_instance_request_concurrency` limit and look at `run.googleapis.com/container/cpu/utilization`.
* **What is the most likely cause in this design?**
  The concurrency limit is likely set too high. If the limit is too high (e.g., leaving the default of 80 to 250), the load balancer routes too many concurrent connections to a single FastAPI container. The Python async event loop eventually saturates, causing requests to queue internally within the container and hit the 3-second timeout before being processed. The fix is to lower the concurrency limit to force horizontal scaling earlier during bursts.

## 4. (Optional) Live Demo & IaC Snippet

To fully demonstrate this architecture, I built a live, interactive deployment. This was my first time utilizing GCP, so I used the $300 new-account free credits to deploy this without incurring personal costs.

**Live Demo URL:** https://prepr-ai-service-ulgop5h7uq-uc.a.run.app/

**Note on Code Numbers vs. Production Numbers:**
The numbers defined in the Terraform code accompanying this repo (concurrency: 15, min_instances: 1, max_instances: 10) are specifically tuned for this visual live demo. I artificially bottlenecked the concurrency to 15 to force the load balancer to scale horizontally much earlier. This allows you to easily visualize the parallel container spin-ups in the custom browser UI during small stress tests. The production numbers discussed above (concurrency: 80, min: 2, max: 8) are what I would use for the actual 150 requests/sec workload.

**Terraform Snippet (Production Scaling Config):**
```hcl
resource "google_cloud_run_v2_service" "api" {
  name     = "prepr-ai-service"
  location = "us-central1"

  template {
    scaling {
      min_instance_count = 2  # Prevents cold starts for steady traffic
      max_instance_count = 8  # Financial circuit breaker
    }

    containers {
      image = var.image
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = false # Always-allocated CPU
      }
    }

    # Triggers scaling when concurrent requests exceed 80
    max_instance_request_concurrency = 80 
  }
}
```
