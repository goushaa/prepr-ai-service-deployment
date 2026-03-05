terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- Artifact Registry (stores our Docker images) ---

resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "prepr-ai-service"
  format        = "DOCKER"
  description   = "Docker images for Prepr AI Service"
}

# --- Cloud Run Service ---

resource "google_cloud_run_v2_service" "api" {
  name     = "prepr-ai-service"
  location = var.region

  template {
    # Scaling configuration
    scaling {
      min_instance_count = var.min_instances  # 2 in prod (eliminates cold starts + redundancy)
      max_instance_count = var.max_instances  # 8 in prod (buffer for burst traffic)
    }

    # Container configuration
    containers {
      image = var.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"       # 1 vCPU — plenty for I/O-bound async workload
          memory = "512Mi"   # FastAPI + uvicorn barely uses 100MB
        }
        cpu_idle = false     # CPU always allocated (steady 20 req/s = always active)
      }

      # Health check — Cloud Run uses this to verify the container is alive
      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 3
      }
    }

    # Max concurrent requests per instance
    max_instance_request_concurrency = var.max_concurrency  # 80 — conservative for async Python
  }

  # Route all traffic to the latest revision
  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# --- IAM: Allow public access (unauthenticated) ---

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
