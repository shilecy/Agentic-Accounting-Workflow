# agents/ingestion_agent.py

import os
import json
import pandas as pd
import requests # Need this for document downloading
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from typing import List, Dict, Any, Optional
from .schemas import ExtractedDocItem
from .utils import initialize_gemini_client, log_audit 
# You will also need to import the ClassificationAgent and its schemas later

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- MERGED AND CORRECTED CLASS DEFINITION ---

class IngestionAgent:
    
    # 1. Constructor: Initialize with dataframes (dfs) and client
    def __init__(self, dfs: Optional[dict] = None):
        self.dfs = dfs if dfs is not None else {}
        self.data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        self.client = initialize_gemini_client(self.__class__.__name__)
        
    
    # 2. ASYNCHRONOUS ENTRY POINT (For n8n/FastAPI)
    # --- FIX: Update the type hint to use the new schema ---
    async def process_input(self, items: List[ExtractedDocItem]) -> List[Dict[str, Any]]:
        """
        Receives input from the n8n HTTP Request, downloads the document,
        and orchestrates the start of the downstream pipeline.
        """
        print(f"[{self.__class__.__name__}] Starting ingestion for {len(items)} items...")
        
        # NOTE: This agent is now largely skipped in your 'interview data' pipeline, 
        # but the method structure must remain for the orchestrator.
        
        workflow_results = []
        
        for item in items:
            # We use doc_number from the ExtractedDocItem as the ID
            doc_id = item.doc_number 
            
            # Since the data is pre-extracted, we skip the real download, 
            # and simulate the successful ingestion required by the next agent.
            
            local_path = f"/tmp/{doc_id}.json" # Simulate path to the JSON file content
            os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
            
            workflow_results.append({
                "document_id": doc_id,
                "status": "INGESTION_COMPLETE",
                "local_path": local_path # Pass the simulated path
            })
            log_audit(doc_id, "INGESTION", "SUCCESS", "Bypassed actual download (interview data).")
            
        return workflow_results

    # 3. HELPER METHOD: Asynchronous Download (Kept for completeness, but not used now)
    async def _async_download_document(self, url: str, doc_id: str) -> str:
        # Note: You should use `asyncio.to_thread` for blocking requests.get in a real app.
        if "example.com" in url:
            local_path = f"/tmp/{doc_id}_download.pdf"
            print(f"Simulating download from {url} to {local_path}")
            os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
            with open(local_path, "w") as f:
                f.write(f"Dummy content for {doc_id}")
            return local_path
        
        raise ValueError(f"Invalid or unsupported document URL: {url}")
    
    # 4. AI Sanitation Check (Keep this logic)
    def ai_sanitize_hash(self, file_content_snippet: str) -> str:
        """Uses AI to confirm content is a relevant financial document (AI REASONING)."""
        # ... (Your existing logic for AI sanitation goes here) ...
        if not self.client:
             return "YES" # Simulation mode assumes relevant
        # ... (rest of your AI logic) ...
        prompt = f"Analyze the following text snippet. Is the content likely from a valid financial document (e.g., invoice, receipt) and not noise or a blank page? Output only 'YES' or 'NO'."
        try:
             response = self.client.models.generate_content(
                 model='gemini-2.5-flash',
                 contents=prompt
             )
             return response.text.strip().upper()
        except APIError:
             return "API_FAIL"

    # 5. SIMULATION METHOD (Keep this logic)
    def simulate_intake(self):
        """Simulates the intake process, including an AI sanitation check on new documents."""
        # ... (Your existing simulate_intake logic goes here) ...
        json_files = [f for f in os.listdir(self.data_dir) if f.endswith('.json') and 'example' not in f]
        
        new_intake_data = []
        for file_name in json_files:
            # Simulated AI check (using file name as snippet for simplicity)
            ai_status = self.ai_sanitize_hash(file_name)
            
            if ai_status == 'YES':
                 new_intake_data.append({
                     'source': 'simulated_scan',
                     'sender': 'assessment_data',
                     'received_at': pd.Timestamp.now().strftime('%Y-%m-%dT%H:%M:%S'),
                     'file_url': f"storage/{file_name}",
                     'hash_sha256': file_name.replace('.json', ''),
                     'doc_status': 'RECEIVED'
                 })
            
        intake_df = self.dfs['Intake']
        # Note: In a real system, you'd load the full file here.
        self.dfs['Intake'] = pd.concat([intake_df, pd.DataFrame(new_intake_data)], ignore_index=True)
        return new_intake_data


    # 6. RUN METHOD (Keep this logic)
    def run(self):
        """Standard run method for agentic loop if not triggered by FastAPI."""
        return self.dfs