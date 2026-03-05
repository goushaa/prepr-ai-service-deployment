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

# --- Artifact Registry ---

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
    service_account = google_service_account.api_sa.email

    # Scaling configuration
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Container configuration
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
        cpu_idle = false
      }

      # Health check probe
      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 3
      }
    }

    # Concurrency limit
    max_instance_request_concurrency = var.max_concurrency
  }

  # Route all traffic to the latest revision
  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# --- IAM: Public Access ---

resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Service Account for the API ---

resource "google_service_account" "api_sa" {
  account_id   = "prepr-ai-service-sa"
  display_name = "Service Account for Prepr AI Service"
}

# Grant Monitoring Viewer to the service account
resource "google_project_iam_member" "monitoring_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.api_sa.email}"
}

# --- Monitoring: Alert on high p95 latency ---

resource "google_monitoring_alert_policy" "high_latency" {
  display_name = "Cloud Run - High p95 Latency"
  combiner     = "OR"

  conditions {
    display_name = "p95 request latency > 2500ms"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"prepr-ai-service\" AND metric.type = \"run.googleapis.com/request_latencies\""
      comparison      = "COMPARISON_GT"
      threshold_value = 2500
      duration        = "60s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

# --- Monitoring: Alert on high error rate ---

resource "google_monitoring_alert_policy" "high_error_rate" {
  display_name = "Cloud Run - High Error Rate"
  combiner     = "OR"

  conditions {
    display_name = "5xx error rate > 5%"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"prepr-ai-service\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "60s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }
}
