#!/bin/bash

# News Tracker - Google Cloud Functions Framework Deployment Script
# This script deploys the news tracker to Google Cloud Run using Functions Framework

set -e  # Exit on any error

# Configuration
PROJECT_ID=${1:-"news-tracker-daily"}
REGION=${2:-"europe-west1"}
SERVICE_NAME="news-tracker-latest"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 News Tracker - Functions Framework Deployment${NC}"
echo "=================================="
echo "Project ID: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo "Framework: Google Cloud Functions Framework"
echo "=================================="

# Check if required files exist
echo -e "\n${YELLOW}📋 Checking required files...${NC}"
required_files=("main.py" "requirements.txt" "Dockerfile")
for file in "${required_files[@]}"; do
    if [[ ! -f "$file" ]]; then
        echo -e "${RED}❌ Missing required file: $file${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Found: $file${NC}"
done

# Ensure utils directory exists
if [[ ! -d "utils" ]]; then
    echo -e "${RED}❌ Missing required directory: utils/${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Found: utils/${NC}"

# Ensure templates directory and key files exist
if [[ ! -d "templates" ]]; then
    echo -e "${RED}❌ Missing required directory: templates/${NC}"
    echo -e "${RED}   The Dockerfile copies templates/, and the app requires newsletter.html${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Found: templates/${NC}"

if [[ ! -f "templates/newsletter.html" ]]; then
    echo -e "${RED}❌ Missing required template: templates/newsletter.html${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Found: templates/newsletter.html${NC}"

# Determine project number and default compute service account
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Check if gcloud is installed and authenticated
echo -e "\n${YELLOW}🔐 Checking Google Cloud authentication...${NC}"
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}❌ gcloud CLI not found. Please install Google Cloud SDK.${NC}"
    exit 1
fi

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n1 > /dev/null; then
    echo -e "${RED}❌ Not authenticated with Google Cloud. Run 'gcloud auth login'${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Google Cloud authentication verified${NC}"

# Set the project
echo -e "\n${YELLOW}🎯 Setting project...${NC}"
gcloud config set project "${PROJECT_ID}"

# Enable required APIs
echo -e "\n${YELLOW}🔧 Enabling required APIs...${NC}"
apis=(
    "cloudbuild.googleapis.com"
    "run.googleapis.com"
    "cloudscheduler.googleapis.com"
    "secretmanager.googleapis.com"
    "gmail.googleapis.com"
    "generativelanguage.googleapis.com"
    "cloudfunctions.googleapis.com"
)

for api in "${apis[@]}"; do
    echo "Enabling ${api}..."
    gcloud services enable "${api}" --quiet
done

echo -e "${GREEN}✅ APIs enabled (including Cloud Functions for Functions Framework)${NC}"

# Create secrets from .env file
echo -e "\n${YELLOW}🔐 Setting up secrets...${NC}"
if [[ -f ".env" ]]; then
    # Read .env file and create secrets
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ $key =~ ^[[:space:]]*# ]] && continue
        [[ -z $key ]] && continue
        
        # Remove quotes from value
        value=$(echo "$value" | sed 's/^["'\'']//' | sed 's/["'\'']$//')
        
        if [[ -n $value ]]; then
            secret_name=$(echo "$key" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
            echo "Creating secret: ${secret_name}"
            
            # Check if secret exists
            if gcloud secrets describe "${secret_name}" --quiet 2>/dev/null; then
                echo "Secret ${secret_name} exists, adding new version..."
                echo -n "$value" | gcloud secrets versions add "${secret_name}" --data-file=-
            else
                echo "Creating new secret: ${secret_name}"
                echo -n "$value" | gcloud secrets create "${secret_name}" --data-file=-
            fi
        fi
    done < .env
    echo -e "${GREEN}✅ Secrets created from .env file${NC}"
else
    echo -e "${YELLOW}⚠️ No .env file found. You'll need to create secrets manually.${NC}"
fi

# Create cloud-run-verify-token secret for security
echo -e "\n${YELLOW}🔒 Creating verification token...${NC}"
VERIFY_TOKEN=$(openssl rand -hex 32)
if gcloud secrets describe "cloud-run-verify-token" --quiet 2>/dev/null; then
    echo -n "$VERIFY_TOKEN" | gcloud secrets versions add "cloud-run-verify-token" --data-file=-
else
    echo -n "$VERIFY_TOKEN" | gcloud secrets create "cloud-run-verify-token" --data-file=-
fi
echo -e "${GREEN}✅ Verification token created${NC}"

# Upload Gmail credentials if available
echo -e "\n${YELLOW}📧 Setting up Gmail credentials...${NC}"
if [[ -f "credentials.json" ]]; then
    if gcloud secrets describe "gmail-credentials" --quiet 2>/dev/null; then
        gcloud secrets versions add "gmail-credentials" --data-file="credentials.json"
    else
        gcloud secrets create "gmail-credentials" --data-file="credentials.json"
    fi
    echo -e "${GREEN}✅ Gmail credentials uploaded${NC}"
else
    echo -e "${YELLOW}⚠️ No credentials.json found. You'll need to upload it manually to Secret Manager.${NC}"
fi

# Upload Gmail account tokens if available
echo -e "\n${YELLOW}📨 Uploading Gmail account token pickles (if present)...${NC}"
for idx in 1 2; do
    TOKEN_FILE="token_account${idx}.pickle"
    SECRET_NAME="gmail-token-account${idx}"
    if [[ -f "${TOKEN_FILE}" ]] && [[ -s "${TOKEN_FILE}" ]]; then
        echo "Uploading ${TOKEN_FILE} to Secret Manager as ${SECRET_NAME}..."
        if gcloud secrets describe "${SECRET_NAME}" --quiet 2>/dev/null; then
            gcloud secrets versions add "${SECRET_NAME}" --data-file="${TOKEN_FILE}"
        else
            gcloud secrets create "${SECRET_NAME}" --data-file="${TOKEN_FILE}"
        fi
        echo -e "${GREEN}✅ Uploaded ${TOKEN_FILE}${NC}"
    else
        echo -e "${YELLOW}⚠️ ${TOKEN_FILE} not found or empty; skipping${NC}"
    fi
done

# Build and push Docker image
echo -e "\n${YELLOW}🐳 Building Docker image...${NC}"
gcloud builds submit --tag "${IMAGE_NAME}" .
echo -e "${GREEN}✅ Docker image built and pushed${NC}"

# Update cloud-run-service.yaml with correct settings
echo -e "\n${YELLOW}📝 Updating service configuration for Functions Framework...${NC}"
cp cloud-run-service.yaml cloud-run-service-deployed.yaml

# Portable in-place replacements using Perl (works on macOS and Linux)
perl -pi -e "s|gcr.io/certain-gearbox-464614-q4/news-tracker:latest|${IMAGE_NAME}:latest|g" cloud-run-service-deployed.yaml
# Replace service name by matching the whole line to avoid double replacement
perl -0777 -pe "s/^\s*name:\s*(news-tracker|news-tracker-latest)\s*$/  name: ${SERVICE_NAME}/m" -i cloud-run-service-deployed.yaml
perl -pi -e "s|value: \"certain-gearbox-464614-q4\"|value: \"${PROJECT_ID}\"|g" cloud-run-service-deployed.yaml

# Pre-grant IAM so first revision can access secrets
echo -e "\n${YELLOW}🔐 Pre-granting Secret Manager access to runtime service accounts...${NC}"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"

# Also grant to App Engine default as a fallback
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${PROJECT_ID}@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" || true

# Deploy to Cloud Run with Functions Framework
echo -e "\n${YELLOW}🚀 Deploying Functions Framework app to Cloud Run...${NC}"
gcloud run services replace cloud-run-service-deployed.yaml --region="${REGION}"

# Get the service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format="value(status.url)")
echo -e "${GREEN}✅ Service deployed at: ${SERVICE_URL}${NC}"

# Set up Cloud Scheduler
echo -e "\n${YELLOW}⏰ Setting up Cloud Scheduler...${NC}"

# Create scheduler job for daily newsletter
SCHEDULER_JOB_NAME="news-tracker-daily"
CRON_SCHEDULE="0 8 * * *"  # Daily at 8 AM

# Get service account email for Cloud Run
SERVICE_ACCOUNT=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format="value(spec.template.spec.serviceAccountName)")
if [[ -z "$SERVICE_ACCOUNT" ]]; then
    SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"
fi

# Delete existing job if it exists
if gcloud scheduler jobs describe "${SCHEDULER_JOB_NAME}" --location="${REGION}" --quiet 2>/dev/null; then
    echo "Deleting existing scheduler job..."
    gcloud scheduler jobs delete "${SCHEDULER_JOB_NAME}" --location="${REGION}" --quiet
fi

# Create new scheduler job
echo "Creating daily scheduler job..."
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
    --location="${REGION}" \
    --schedule="${CRON_SCHEDULE}" \
    --uri="${SERVICE_URL}/run-pipeline" \
    --http-method=POST \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" \
    --headers="Content-Type=application/json" \
    --message-body='{"trigger":"scheduler"}' \
    --time-zone="Europe/Paris"

echo -e "${GREEN}✅ Cloud Scheduler job created${NC}"

# Set up IAM permissions
echo -e "\n${YELLOW}🔐 Setting up IAM permissions...${NC}"

# Allow Cloud Scheduler to invoke Cloud Run
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/run.invoker" \
    --region="${REGION}"

# Allow runtime service account(s) to access secrets (bind both App Engine default and Compute default)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"

echo -e "${GREEN}✅ IAM permissions configured${NC}"

# Clean up temporary files
rm -f cloud-run-service-deployed.yaml

# Final summary
echo -e "\n${GREEN}🎉 Functions Framework Deployment Complete!${NC}"
echo "=================================="
echo -e "Service URL: ${BLUE}${SERVICE_URL}${NC}"
echo -e "Health Check: ${BLUE}${SERVICE_URL}/${NC}"
echo -e "Pipeline Trigger: ${BLUE}${SERVICE_URL}/run-pipeline${NC}"
echo -e "Scheduler: Daily at 8 AM (${CRON_SCHEDULE})"
echo -e "Framework: Google Cloud Functions Framework"
echo ""
echo -e "${YELLOW}📋 Next Steps:${NC}"
echo "1. Test the deployment: curl ${SERVICE_URL}/"
echo "2. Trigger pipeline manually: curl -X POST ${SERVICE_URL}/run-pipeline"
echo "3. Check Cloud Scheduler in the GCP Console"
echo "4. Monitor logs: gcloud logs tail /projects/${PROJECT_ID}/logs/run.googleapis.com%2Frequests"
echo ""
echo -e "${YELLOW}💡 Useful Commands:${NC}"
echo "• View logs: gcloud logs tail /projects/${PROJECT_ID}/logs/run.googleapis.com%2Frequests"
echo "• Update service: gcloud run services replace cloud-run-service.yaml --region=${REGION}"
echo "• Trigger manually: gcloud scheduler jobs run ${SCHEDULER_JOB_NAME} --location=${REGION}"
echo "• Local testing: functions-framework --target=main_handler --debug" 