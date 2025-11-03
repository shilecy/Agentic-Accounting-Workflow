# agents/main.py

import os
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from typing import List
# --- 1. SCHEMA IMPORT CHANGE ---
from .schemas import ExtractedDocItem 
from pydantic import BaseModel

# Import ALL Agents
from .ingestion_agent import IngestionAgent
from .classification_agent import ClassificationAgent
from .extraction_agent import ExtractionAgent
from .validation_agent import ValidationAgent
from .exception_desk_agent import ExceptionDeskAgent
from .posting_engine_agent import PostingEngineAgent
from .reconciliation_agent import ReconciliationAgent
from .reporting_agent import ReportingAgent
from .pipeline import run_async_pipeline
from .utils import load_dataframes, save_dataframes
from .utils import DATA_DIR, OUTPUTS_DIR, LOGS_DIR

app = FastAPI(
    title="AI Agent Orchestration API",
    description="Endpoint for n8n to trigger the document processing workflow."
)

class WorkflowRequest(BaseModel):
    mode: str = "full"  # future usage if needed

@app.post("/api/v1/trigger_workflow")
async def trigger_workflow(_payload: WorkflowRequest):
    # --- 3. REFINED LOGIC TO LOAD INTERVIEW JSONS ---
    print("🔗 n8n triggered workflow. Loading interview data...")

    import glob, json, os
    # Assuming interview JSONs are in the data directory
    BASE = os.path.join(os.path.dirname(__file__), "..", "data")
    doc_files = glob.glob(f"{BASE}/*.json")

    items = []
    for f in doc_files:
        # Skip example files if they exist
        if 'example' not in os.path.basename(f):
            with open(f) as fp:
                doc = json.load(fp)
            items.append(doc)

    print(f"📄 Loaded {len(items)} interview documents for processing (Bypassing OCR).")

    # Convert loaded dictionaries to Pydantic objects using the new schema
    objects = [ExtractedDocItem(**i) for i in items] # <--- Use ExtractedDocItem

    # ✅ PROCESS REAL INTERVIEW DATA by delegating to pipeline.py
    final_result = await run_async_pipeline(objects)

    # RETURN the final result, which should be the exception_data dictionary
    return final_result

@app.get("/webhook-test/review/approve")
def resolve_approval(doc_id: str, key: str):
    # This function should update the document status in your system.
    # We will assume a simple DataFrame update for the demo:
    
    # 1. Load the latest dataframes (specifically Documents.csv)
    dfs = load_dataframes()
    docs_df = dfs['Documents']
    
    # 2. Find the row matching the doc_id and having the REVIEW_PENDING status
    # (Optional: Add 'key' validation here for security)
    match_index = docs_df[
        (docs_df['id'] == doc_id) & 
        (docs_df['status'] == 'REVIEW_PENDING')
    ].index
    
    if not match_index.empty:
        # 3. Update the status to 'ready' for the Posting Agent to pick up
        docs_df.loc[match_index, 'status'] = 'READY'
        
        # 4. Log and Save the updated dataframe state
        print(f"✅ Webhook Resolution: Document {doc_id} status set to 'READY'.")
        # You need to call save_dataframes from utils.py here
        save_dataframes(dfs)
        
        return {"status": "success", "message": f"Document {doc_id} approved and marked 'READY'."}
    
    raise HTTPException(status_code=404, detail="Document not found or status already changed.")

def run_flow():
    """Defines and executes the end-to-end accounting flow."""
    print("--- Starting AI Agentic Accounting Flow ---")
    dfs = load_dataframes()
    
    # 0. Initialize Agents (The flow assumes Intake data is pre-populated in Documents/LineItems/Intake for brevity)
    ingestion = IngestionAgent(dfs)
    
    # 1. Intake
    ingestion.simulate_intake()
    print("\n1. Intake: Documents logged for processing.")
    
    # 2 & 3. Classification & Extraction (Skipped, using pre-loaded data for speed)
    print("2 & 3. Classification & Extraction: Using pre-loaded Documents/LineItems.")

    # 4. Validation & Enrichment (AI Reasoning on Exceptions)
    validation = ValidationAgent(dfs)
    dfs = validation.run()
    print("\n4. Validation: Documents enriched and AI checked for exceptions.")

    # 7. Exceptions Desk (AI Root Cause Analysis & Fix Suggestion)
    exceptions_desk = ExceptionDeskAgent(dfs)
    dfs = exceptions_desk.run()
    print("\n7. Exceptions Desk: AI-guided human review/correction completed.")

    # 5. Posting Engine (AI Verification of GL Logic)
    posting = PostingEngineAgent(dfs)
    dfs = posting.run()
    print("\n5. Posting: Journal Entries created and AR/AP initialized (AI-verified).")

    # 6. Reconciliation & Lifecycle (AI Intelligent Matching)
    reconciliation = ReconciliationAgent(dfs)
    dfs = reconciliation.run()
    print("\n6. Reconciliation: Bank Feed matched and AR/AP balances updated (AI-assisted).")
    
    # 8. Reporting & Exports (Generates required financial reports)
    reporting = ReportingAgent(dfs, OUTPUTS_DIR)
    dfs = reporting.run()
    print("\n8. Reporting: Financial reports and Dashboard data generated.")

    save_dataframes(dfs)
    print("\n--- Flow Completed Successfully ---")

if __name__ == "__main__":
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True) # Ensure LOGS_DIR exists for system logging
    run_flow()