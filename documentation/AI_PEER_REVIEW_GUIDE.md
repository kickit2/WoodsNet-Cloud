# Woods-Net Architecture Review Guide (For AI Peer Review)

**ATTN:** Grok, Meta AI, or any reviewing LLM instance.

This document serves as a technical briefing on the "Woods-Net" MVP Cloud Backend architecture. Please review the codebase and infrastructure deployment strategy for security flaws, race conditions, or optimization opportunities before the user executes the deployment.

## System Overview
Woods-Net is a remote, off-grid trail camera ecosystem. Edge devices ("Mules" - Pi Zeros) capture images and transmit them via XBee 900MHz RF to a central "Base Station" (Pi 4). The Base Station then uploads these `.avif` images to an AWS S3 bucket over a cellular or localized internet connection.

## Core Cloud Architecture (AWS Serverless)
The entire backend is provisioned via a single Python script (`cloud_backend/deploy_infra.py`) utilizing `boto3`.

### 1. Ingestion Pipeline (The Presigned Pattern)
To avoid API Gateway payload limits and base64 encoding overhead, we use direct-to-S3 mapping:
- **`get_presigned_url` Lambda:** Triggered by API Gateway (`GET /get-upload-url`). Generates a temporary S3 presigned PUT URL.
- The Base Station (`faux_base` software) uploads the binary `.avif` directly to S3 using the presigned URL.

### 2. AI Analysis Pipeline (Event-Driven)
- **S3 Trigger:** The `woods-net-captures` S3 bucket fires `s3:ObjectCreated:Put` events restricted to the `woods-net/mules/` prefix and `.avif` suffix.
- **`analyze_image` Lambda:** 
  - Passes the new image to **AWS Rekognition** (`detect_labels`).
  - Implements custom logic: If `Deer` is detected alongside `Antler` or `Horn`, it overrides the label to `Antlered Buck`.
  - Hooks into the **Open-Meteo API** to fetch real-time weather and lunar phase data based on the camera's assumed GPS coordinates (pulled from an S3 JSON config).
  - Optionally fires **AWS Rekognition Custom Labels** (`detect_custom_labels`) if a user-trained model ARN is present in the environment variables and a buck is detected.
  - Generates an **AWS SNS** text alert (`WoodsNetSecurityAlerts`) if a `Person` or `Antlered Buck` is detected.
  - Commits the final metadata payload (Tags, object counts, Weather dict) to a **DynamoDB** table (`WoodsNetImageTags`) with `ImageKey` as the HASH key.

### 3. Frontend / Web Portal API
- **S3 Static Hosting:** The frontend UI (`index.html`, `app.js`, `styles.css`) is deployed to a secondary public bucket.
- **`list_images` Lambda:** Triggered by `GET /list-images`. Scans S3 (max 100 items), batch-queries DynamoDB to merge the AI metadata/weather, and generates short-lived presigned GET URLs for browser rendering.
- **`manage_image` Lambda:** Handles authorized rename/delete operations and updates the `_config/mule_mappings.json` (used for GPS and human-readable camera names).
- **`generate_timelapse` Lambda:** A subprocess wrapper around `ffmpeg`. Pulls recent images, compiles an MP4, drops it in S3, and returns a download link.

## Security Posture (MVP)
- **API Authentication:** Currently utilizes a hardcoded fallback token (`Bearer DeerCamp`) validated inside the Lambda handlers. CloudFront/Cognito is planned for Phase 13, but the MVP accepts this risk profile for initial testing.
- **IAM Roles:** The Lambdas share a unified role (`WoodsNetLambdaS3Role`) with strictly scoped in-line policies for DynamoDB, Rekognition, SNS, and S3 path constraints.

## Request for Review
Please evaluate the Python code located in `cloud_backend/lambda_functions/` and `cloud_backend/deploy_infra.py`. 
- Are there any glaring boto3 IAM permission gaps?
- Will the DynamoDB `batch_get_item` in `list_images` scale gracefully if we increase pagination beyond 100 items?
- Is the asynchronous `ffmpeg` blocking approach in `generate_timelapse` safe without an SQS dead-letter queue for this MVP stage?
