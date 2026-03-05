# Prepr AI Service Deployment

This repository contains the infrastructure and application code for the Prepr AI Service assessment. It features a fully production-ready, auto-scaling FastAPI service deployed on GCP Cloud Run via Terraform and GitHub Actions.

## 📝 Assessment Submission

*   The answers to the official assessment prompt (Architecture, Key Decisions, Debugging) can be found in **[`ARCHITECTURE.md`](./ARCHITECTURE.md)**.

## 🎯 Implemented Requirements

As per the assessment guidelines, the following core endpoints were implemented and mocked using FastAPI:
*   `GET /health` : Liveness probe returning a basic `{"status": "healthy"}` JSON payload.
*   `GET /generate` : Simulates an AI generation task. It utilizes Python's `asyncio.sleep` to artificially mock a 2 to 4 second latency before returning a simulated text response.

## 🚀 Live Interactive Demo

A live, interactive frontend was built to visually demonstrate Cloud Run's auto-scaling capabilities under burst traffic. 

**Live URL:** [https://prepr-ai-service-ulgop5h7uq-uc.a.run.app/](https://prepr-ai-service-ulgop5h7uq-uc.a.run.app/)

*The demo utilizes Server-Sent Events (SSE) and client-side heartbeat polling to provide real-time, sub-second visibility into Cloud Run instance spin-ups and organic scale-downs.*

## 📂 Repository Structure

*   `app/` - The FastAPI application (`main.py`) and static frontend UI.
*   `terraform/` - Infrastructure as Code definitions for Cloud Run, Artifact Registry, and IAM.
*   `.github/workflows/` - CI/CD pipeline for automated multi-stage deployments.
*   `Dockerfile` - Container definition optimized for async Python workloads.

## 🛠️ How to Run Locally

You can run the service locally using standard Python tooling or Docker.

**Using Python:**
```bash
pip install -r requirements.txt
uvicorn app.main:app --host localhost --port 8080 --reload
```

**Using Docker:**
```bash
docker build -t prepr-ai-service .
docker run -p 8080:8080 prepr-ai-service
```

Access the UI at: `http://localhost:8080/`

## ☁️ How to Deploy (Infrastructure)

The infrastructure is managed entirely by Terraform.

1. Authenticate with Google Cloud:
   ```bash
   gcloud auth application-default login
   ```
2. Create a `terraform.tfvars` file and define your project details:
   ```hcl
   project_id = "your-gcp-project-id"
   image      = "us-central1-docker.pkg.dev/your-project/prepr-ai-service/api:latest"
   ```
3. Initialize and apply Terraform:
   ```bash
   cd terraform
   terraform init
   terraform apply
   ```

Subsequent application updates are handled automatically by the `.github/workflows/deploy.yml` pipeline upon pushing to `main`.
