## Agentic Human-In-Loop (HIL) Accounting Workflow

Project Overview

This project demonstrates a multi-agent architecture designed to automate the process of accounting flow.

It implements the Human-in-the-Loop (HIL) paradigm, using a structured workflow orchestrator (n8n) and a Python backend (FastAPI) to ensure data integrity, security, and reviewer-approved resolutions before any final transaction is posted. This ensures that only validated data enters your core accounting system.


## Technology Stack

Language: Python

AI/LLM: Google Gemini API

Web Framework: FastAPI

Workflow Orchestration: n8n (or custom)

Database (PoC): Local CSV files


## Accounting Workflow Stages

The complete accounting flow is a staged pipeline, orchestrated by n8n and executed by the Python/FastAPI backend.

### 1. Ingestion & Parsing:

The workflow is triggered by a new document (e.g., invoice scan/image/pdf file).

### 2. The Classification Agent identifies the document type.

The Extraction Agent extracts all structured data (Vendor, Amount, Date, etc.) using the Gemini model's multi-modality capabilities.

### 3/4. Validation & Exception Detection:

The Validation Agent cross-check vendor registry, recalc totals, infer missing tax, detect duplicates, compute FX conversion, and store normalized values.
If all checks pass, the process skips to step 6 (Posting).
If an exception is detected (e.g., Vendor ID mismatch etc), the transaction is flagged for human review.

### 7. Human-in-the-Loop (HIL) Pause:

The Exception Desk Agent flags low-confidence or inconsistent documents for review.
User can approve or correct extracted values through chat interface (in this case through email).
The n8n Orchestrator send email notification to the Accountant/reviewer to review the flagged documents.
The reviewer approves/fix documents.

The workflow RESUMES.

### 5/6/8. Posting, Reconciliation and Reporting:

The Posting and Reconciliation Agent commits the validated transaction to the core accounting system.

Reporting agent exports all processed data and logged to Excel/CSV, producing Trial Balance, Profit&Loss, Balance Sheet etc and export data to dashboard.


### 1. Environment Setup

Clone the repository:

git clone [https://github.com/YourUsername/Agentic-Accounting-Workflow.git](https://github.com/YourUsername/Agentic-Accounting-Workflow..git)
cd Agentic-Accounting-Workflow


Create a virtual environment:

python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate


Install dependencies:

pip install -r requirements.txt


### 2. Configuration (.env file)

Create a file named .env in the root directory and add your secret key:

Replace YOUR_GEMINI_API_KEY with your actual key
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"

Add other credentials as needed for a production system (e.g., DB credentials)

### 3. FastAPI Execution

Run the FastAPI application using Uvicorn. This will start the server hosting your agent endpoints.

uvicorn agents.main:app --reload

The server will be available at http://127.0.0.1:8000.


Or simply run python -m agents.main

### 4. n8n Workflow - screencast 