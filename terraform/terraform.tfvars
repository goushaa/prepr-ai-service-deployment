project_id = "prepr-ai-service-assessment"
region     = "us-central1"
image      = "us-central1-docker.pkg.dev/prepr-ai-service-assessment/prepr-ai-service/api:latest"

# Demo settings (override for production)
min_instances   = 0
max_instances   = 4
max_concurrency = 10  # Low for demo — triggers scaling with small burst tests
