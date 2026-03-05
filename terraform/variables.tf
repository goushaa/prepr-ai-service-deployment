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
  description = "Minimum always-warm instances"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum active instances"
  type        = number
  default     = 10
}

variable "max_concurrency" {
  description = "Max concurrent requests per instance"
  type        = number
  default     = 15
}
