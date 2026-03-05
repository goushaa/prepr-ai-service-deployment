variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for deployment"
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "Docker image to deploy (full Artifact Registry path)"
  type        = string
}

# --- Scaling variables (tune per environment) ---

variable "min_instances" {
  description = "Minimum always-warm instances (2 for prod, 0 for demo)"
  type        = number
  default     = 2
}

variable "max_instances" {
  description = "Maximum instances (cost safety cap)"
  type        = number
  default     = 8
}

variable "max_concurrency" {
  description = "Max concurrent requests per instance"
  type        = number
  default     = 80
}
