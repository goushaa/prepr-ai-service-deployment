project_id = "prepr-ai-service-assessment"
region     = "us-central1"
image      = "us-central1-docker.pkg.dev/prepr-ai-service-assessment/prepr-ai-service/api:latest"

# Demo settings (override for production)
min_instances   = 1
max_instances   = 4
max_concurrency = 5   # Low enough to trigger scaling, high enough to avoid deadlock
