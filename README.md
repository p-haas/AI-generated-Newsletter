# News Tracker

Automate the creation of a daily newsletter from the last 24 hours of Gmail activity. News Tracker ingests recent messages, uses Gemini 2.5 models to identify and extract news stories, deduplicates overlapping coverage, and delivers a polished HTML digest either locally or through a Google Cloud Run deployment.

<p align="center">
  <em>Build once, deploy anywhere: from a developer laptop to a production-ready Cloud Run service.</em>
</p>

---

## Table of Contents

1. [Features](#features)
2. [System Overview](#system-overview)
3. [Repository Structure](#repository-structure)
4. [Getting Started](#getting-started)
5. [Local Development Workflow](#local-development-workflow)
6. [Configuration Reference](#configuration-reference)
7. [Deployment to Google Cloud Run](#deployment-to-google-cloud-run)
8. [Operational Guidance](#operational-guidance)
9. [Troubleshooting](#troubleshooting)
10. [Roadmap](#roadmap)
11. [Contributing](#contributing)
12. [License](#license)

---

## Features

- **End-to-end orchestration** – [`main.py`](./main.py) ties together authentication, email retrieval, LLM-driven classification, news extraction, deduplication, newsletter templating, and email delivery.
- **Multi-account Gmail support** – Configure and authenticate any number of Gmail inboxes via [`utils/settings.py`](./utils/settings.py) and [`utils/auth.py`](./utils/auth.py).
- **Gemini-native processing** – Gemini 2.5 Flash Lite powers classification and extraction, while Gemini 2.5 Flash handles deduplication and Gemini 2.5 Pro organises the final digest.
- **Production-ready templating** – [`templates/newsletter.html`](./templates/newsletter.html) and supporting utilities in [`utils/newsletter`](./utils/newsletter) produce sanitised, mobile-friendly HTML.
- **Cloud-friendly interface** – A Functions Framework HTTP handler enables Cloud Run deployments with a single entrypoint alongside the interactive CLI experience.
- **Deployment artefacts included** – Use [`deploy.sh`](./deploy.sh), [`cloud-run-service.yaml`](./cloud-run-service.yaml), and the detailed [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) to ship the pipeline to production.

## System Overview

| Capability | Description |
|------------|-------------|
| **Authentication** | OAuth 2.0 desktop credentials are exchanged for tokens via [`utils/auth.py`](./utils/auth.py). Production deployments optionally load secrets from Google Secret Manager. |
| **Email retrieval & classification** | [`utils/email_processing.py`](./utils/email_processing.py) fetches messages from the last 24 hours, normalises content, and identifies newsworthy emails using Gemini structured output schemas defined in [`utils/models.py`](./utils/models.py). |
| **Story extraction & deduplication** | [`utils/news_extraction.py`](./utils/news_extraction.py) breaks newsletters into discrete stories, while [`utils/news_deduplication.py`](./utils/news_deduplication.py) groups overlapping content with concurrency-aware helpers tuned for Cloud Run. |
| **Newsletter assembly** | [`utils/newsletter`](./utils/newsletter) orchestrates content curation, fallbacks, templating, and delivery through [`utils/newsletter/sender.py`](./utils/newsletter/sender.py). |
| **Interfaces** | The CLI (`python main.py`) and HTTP handler (`main_handler`) expose the same pipeline for local automation or Cloud Run invocations. |

## Repository Structure

```
news-tracker-2/
├── main.py                   # CLI entrypoint + Cloud Run HTTP handler
├── requirements.txt          # Python dependencies (Gmail, Gemini, GCP SDKs)
├── utils/
│   ├── auth.py               # Multi-account Gmail authentication helpers
│   ├── email_processing.py   # Email retrieval + Gemini classification
│   ├── news_extraction.py    # News item extraction with rate limiting
│   ├── news_deduplication.py # Similarity grouping + category helpers
│   ├── newsletter/           # Categorisation, templating, and email sending
│   ├── logging_utils.py      # Structlog configuration
│   ├── llm.py                # Gemini SDK wrapper
│   └── settings.py           # Shared configuration and Secret Manager access
├── templates/                # Jinja template + CSS for the newsletter
├── sample_data/              # Example JSON payloads for offline previewing
├── deploy.sh                 # One-command Cloud Run deployment helper
├── cloud-run-service.yaml    # Baseline Cloud Run service specification
├── DEPLOYMENT_GUIDE.md       # Detailed deployment walkthrough
└── PROJECT_ROADMAP.md        # Feature roadmap and open work
```

## Getting Started

### Prerequisites

- Python **3.11+** (virtual environments recommended).
- A Google Cloud project with the Gmail API, Secret Manager, Cloud Run, Cloud Scheduler, and Gemini API enabled for deployments.
- A Gemini API key with access to the 2.5 model family.
- Gmail OAuth 2.0 desktop credentials (`credentials.json`) for each inbox you want to process.
- (Optional) Google Secret Manager secrets to store runtime credentials when deploying to Cloud Run.

### Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Local Development Workflow

1. **Configure environment variables** – Create a `.env` file at the repository root or export variables in your shell. Minimum values:
   ```bash
   GEMINI_API_KEY=your_gemini_api_key
   NEWSLETTER_RECIPIENT=recipient@example.com
   ```
   Additional options are documented in [`utils/settings.py`](./utils/settings.py).

2. **Provide Gmail credentials** – Place `credentials.json` in the project root. Adjust account configuration in [`utils/settings.py`](./utils/settings.py) to match your desired inboxes and secret IDs.

3. **Generate local OAuth tokens** – Run the CLI and choose the `run` command. The first execution triggers a browser flow for each configured account and stores tokens as `token_account*.pickle` files (or in Secret Manager when configured).

4. **Execute the pipeline** –
   ```bash
   python main.py
   # follow the interactive prompts to run the pipeline or trigger the HTTP server
   ```
   The CLI surfaces progress updates, including counts of processed emails, extracted stories, and final categories. The resulting newsletter is sent to the configured recipient.

5. **Experiment offline** – Use [`sample_data/test_newsletter.json`](./sample_data/test_newsletter.json) with helpers from [`utils/newsletter`](./utils/newsletter) to inspect rendering logic without accessing live inboxes.

## Configuration Reference

- **Environment variables** – See [`utils/settings.py`](./utils/settings.py) for available toggles (e.g., account labels, Secret Manager IDs, concurrency limits, Gemini model choices).
- **LLM tuning** – [`utils/models.py`](./utils/models.py) defines structured prompts and schemas for the Gemini calls. Adjust thresholds or prompts to match your editorial preferences.
- **Logging** – [`utils/logging_utils.py`](./utils/logging_utils.py) configures structured logging via `structlog`. Override levels or formats before deployment if needed.

## Deployment to Google Cloud Run

1. **Prepare infrastructure**
   - Update project IDs, regions, and service names in [`deploy.sh`](./deploy.sh) and [`cloud-run-service.yaml`](./cloud-run-service.yaml).
   - Provision a Google Artifact Registry repository (or use Docker Hub) for container images.
   - Create Secret Manager entries for the Gemini API key, newsletter recipient, Gmail OAuth tokens, and optional verification tokens.

2. **Build & deploy**
   ```bash
   ./deploy.sh
   ```
   The script builds the container image, pushes it to Artifact Registry, deploys the Cloud Run service, and configures environment variables and secrets. Adjust the script for your organisation's CI/CD practices.

3. **Schedule automated runs**
   - Follow [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md) to connect Cloud Scheduler or other automation tooling to the `POST /run-pipeline` endpoint.
   - Confirm the service account has `roles/secretmanager.secretAccessor`, `roles/run.invoker`, and any required Gmail API scopes.

### HTTP Endpoints

- `GET /` – Health check used by Cloud Run revisions.
- `POST /run-pipeline` – Trigger the full newsletter generation workflow. Requires authentication if you configure an optional verification token.

## Operational Guidance

- **Monitoring** – Cloud Run logs include structured fields emitted by `structlog`. Use Cloud Logging queries to track pipeline health, counts, and LLM usage.
- **Cost control** – Gemini usage is the primary cost driver. Tune model selections and concurrency limits in [`utils/settings.py`](./utils/settings.py) to balance throughput and expense.
- **Security** – Never commit credentials. Use Secret Manager or local `.env` files that are excluded from version control. Rotate API keys and OAuth tokens regularly.

## Troubleshooting

- Ensure `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) is available in the environment before invoking any Gemini-backed utilities.
- Confirm Gmail OAuth credentials are valid and the Gmail API is enabled on your Google Cloud project.
- Production deployments require the Cloud Run service account to access Secret Manager. Review IAM policies outlined in [`DEPLOYMENT_GUIDE.md`](./DEPLOYMENT_GUIDE.md).
- If duplicate stories appear, adjust similarity thresholds in [`utils/news_deduplication.py`](./utils/news_deduplication.py).

## Roadmap

Future enhancements—such as richer summaries, historical archiving, editorial controls, and automated testing—are tracked in [`PROJECT_ROADMAP.md`](./PROJECT_ROADMAP.md). Contributions are welcome.

## Contributing

Issues and pull requests are encouraged. If you plan a significant change, open an issue first so we can discuss the approach. Please ensure your submissions adhere to the project's coding style and include sufficient documentation or tests when applicable.

## License

This project currently does not include an explicit license. If you intend to use News Tracker in production, open an issue to discuss licensing options or add an appropriate open-source license file.

---

> **Disclaimer:** This repository does not include production credentials or an active Cloud Run deployment. Provision your own infrastructure, secrets, and environment variables before running the automated newsletter end to end.
