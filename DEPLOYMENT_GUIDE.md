## News Tracker - Cloud Run Deployment Guide (GCP)

This guide documents the exact steps to deploy this repository to Google Cloud Run for the project `news-tracker-daily` in region `europe-west1`.

### Prerequisites
- Google Cloud SDK installed and authenticated: `gcloud auth login`
- You are logged into the correct account and project: `gcloud config set project news-tracker-daily`
- Optional: a `.env` file at the repo root (used by the script to seed secrets)

Required secrets (can be created by the script or manually):
- `gemini-api-key`: your Gemini API key
- `newsletter-recipient`: recipient email address for the newsletter
- Optional: `gmail-credentials`: your Gmail OAuth client JSON (if using Gmail API)

### One-command deployment (recommended)
From the repo root:

```bash
cd /Users/pierrehaas/Desktop/Projects/news-tracker-2
./deploy.sh news-tracker-daily europe-west1
```

What the script does:
- Sets the project and enables required APIs
- Creates/updates secrets from `.env` if present
- Creates/updates a verification token secret
- Builds and pushes the container image to `gcr.io/news-tracker-daily/news-tracker-latest:latest`
- Updates a deployment YAML and deploys the Cloud Run service `news-tracker-latest`
- Grants IAM so the runtime service account can read Secret Manager
- Creates/updates a Cloud Scheduler job to POST `/run-pipeline` daily at 08:00 Europe/Paris

After deployment:
```bash
SERVICE_URL=$(gcloud run services describe news-tracker-latest \
  --region=europe-west1 --format='value(status.url)')
echo $SERVICE_URL

# Health check
curl "$SERVICE_URL/"

# Trigger the full pipeline (long-running)
curl -X POST "$SERVICE_URL/run-pipeline"

# Verify/create the daily Cloud Scheduler job (08:00 Europe/Paris)
gcloud run services add-iam-policy-binding news-tracker-latest \
  --region=europe-west1 \
  --member=serviceAccount:news-tracker-daily@appspot.gserviceaccount.com \
  --role=roles/run.invoker \
  --project=news-tracker-daily

gcloud scheduler jobs create http news-tracker-latest-daily \
  --location=europe-west1 \
  --schedule="0 8 * * *" \
  --time-zone="Europe/Paris" \
  --http-method=POST \
  --uri="${SERVICE_URL}/run-pipeline" \
  --oidc-service-account-email=news-tracker-daily@appspot.gserviceaccount.com \
  --headers="Content-Type=application/json" \
  --message-body='{"trigger":"scheduler"}' \
  --project=news-tracker-daily || true

# Manage job
gcloud scheduler jobs describe news-tracker-latest-daily --location=europe-west1 --project=news-tracker-daily
gcloud scheduler jobs run news-tracker-latest-daily --location=europe-west1 --project=news-tracker-daily
```

To allow public (unauthenticated) access:
```bash
gcloud run services add-iam-policy-binding news-tracker-latest \
  --region europe-west1 \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --project news-tracker-daily
```

### Manual deployment (advanced)
Use this if you prefer not to use `deploy.sh`.

1) Set project and enable APIs
```bash
gcloud config set project news-tracker-daily
gcloud services enable cloudbuild.googleapis.com run.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com \
  gmail.googleapis.com generativelanguage.googleapis.com cloudfunctions.googleapis.com
```

2) Create secrets (idempotent examples)
```bash
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- || \
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key --data-file=-

echo -n "recipient@example.com" | gcloud secrets create newsletter-recipient --data-file=- || \
echo -n "recipient@example.com" | gcloud secrets versions add newsletter-recipient --data-file=-

# Optional Gmail OAuth credentials
# gcloud secrets create gmail-credentials --data-file=credentials.json || \
# gcloud secrets versions add gmail-credentials --data-file=credentials.json

# Verification token for security (optional but recommended)
openssl rand -hex 32 | gcloud secrets create cloud-run-verify-token --data-file=- || true
```

3) Build and push the container image
```bash
IMAGE_NAME=gcr.io/news-tracker-daily/news-tracker-latest
gcloud builds submit --tag "$IMAGE_NAME" .
```

4) Deploy Cloud Run
The repository includes a ready-to-use `cloud-run-service.yaml` that already targets:
- Service: `news-tracker-latest`
- Project: `news-tracker-daily`
- Image: `gcr.io/news-tracker-daily/news-tracker-latest:latest`
- Service account: `news-tracker-daily@appspot.gserviceaccount.com`

Grant Secret Manager access to the service account once:
```bash
gcloud projects add-iam-policy-binding news-tracker-daily \
  --member=serviceAccount:news-tracker-daily@appspot.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor --quiet
```

Deploy the service:
```bash
gcloud run services replace cloud-run-service.yaml \
  --region=europe-west1 --project=news-tracker-daily
```

Retrieve the service URL and test:
```bash
SERVICE_URL=$(gcloud run services describe news-tracker-latest \
  --region=europe-west1 --format='value(status.url)')
echo $SERVICE_URL
curl "$SERVICE_URL/"
```

5) (Optional) Make public and set up Cloud Scheduler
```bash
# Public
gcloud run services add-iam-policy-binding news-tracker-latest \
  --region europe-west1 \
  --member="allUsers" \
  --role="roles/run.invoker" \
  --project news-tracker-daily

# Scheduler: trigger daily at 08:00 Europe/Paris
gcloud scheduler jobs create http news-tracker-latest-daily \
  --location=europe-west1 \
  --schedule="0 8 * * *" \
  --time-zone="Europe/Paris" \
  --http-method=POST \
  --uri="${SERVICE_URL}/run-pipeline"

# Scheduler management
gcloud scheduler jobs describe news-tracker-latest-daily --location=europe-west1 --project=news-tracker-daily
gcloud scheduler jobs run news-tracker-latest-daily --location=europe-west1 --project=news-tracker-daily
```

### Troubleshooting
- Secret access denied: ensure the runtime service account has `roles/secretmanager.secretAccessor`.
- 404 after deploy: confirm service name `news-tracker-latest` and region `europe-west1`.
- Long request timeouts: Cloud Run default timeout is increased in the YAML to 3600s.
- Memory OOM: increase `spec.template.spec.containers[].resources.limits.memory` in `cloud-run-service.yaml` and redeploy.

### Useful commands
```bash
# Logs (recent requests)
gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=news-tracker-latest' \
  --limit=50 --project=news-tracker-daily --format='value(timestamp,textPayload)'

# Describe service
gcloud run services describe news-tracker-latest --region=europe-west1 --project=news-tracker-daily

# Trigger pipeline manually
curl -X POST "$SERVICE_URL/run-pipeline"

# Run the scheduler job now
gcloud scheduler jobs run news-tracker-latest-daily --location=europe-west1 --project=news-tracker-daily
```


