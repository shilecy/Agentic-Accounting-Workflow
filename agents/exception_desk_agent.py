# agents/exception_desk_agent.py (FINAL CORRECTED VERSION)

import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
import os
import uuid # <-- Correctly imported
from .utils import initialize_gemini_client, log_audit

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- GLOBAL CONFIGURATION ---
BASE_WEBHOOK_URL = os.getenv("N8N_REVIEW_WEBHOOK_URL", "https://franco-overgenerous-exponentially.ngrok-free.dev/webhook-test")
DEFAULT_REVIEWER_EMAIL = "accounting.lead@yourcompany.com"

class ExceptionDeskAgent:
    def __init__(self, dfs: dict):
        self.dfs = dfs
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)
            
    def ai_root_cause_analysis(self, doc: pd.Series, status: str) -> str:
        """Uses Gemini to provide a detailed root cause and suggested fix (AI REASONING)."""
        if not self.client:
            return f"SIMULATION: Error {status} requires manual intervention."
        
        prompt = (
            f"A document is in exception status. Analyze the status reason and the document data to provide a detailed root cause "
            "and propose a definitive manual fix. The output should be a single, structured paragraph containing the analysis and fix."
            f"Document Data: ID={doc['id']}, Doc Type={doc['doc_type']}, Currency={doc['currency']}, Status={status}."
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip()
        except APIError:
            return "AI Analysis failed to complete."
            
    def log_audit(self, doc_id, action, details):
        audit_log_df = self.dfs['AuditLog']
        new_log = pd.DataFrame([{'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),'actor': 'ExceptionDeskAgent','action': action,'doc_id': doc_id,'details': details}])
        self.dfs['AuditLog'] = pd.concat([audit_log_df, new_log], ignore_index=True)

    def get_reviewer_email(self, doc: pd.Series) -> str: # <-- CORRECT INDENTATION
        """Looks up the counterparty email for routing the exception."""
        # Note: DEFAULT_REVIEWER_EMAIL is now defined above
        if doc['counterparty_type'] == 'vendor':
            master_df = self.dfs['Vendors']
        elif doc['counterparty_type'] == 'customer':
            master_df = self.dfs['Customers']
        else:
            return DEFAULT_REVIEWER_EMAIL
        
        counterparty_id = doc['vendor_customer_id']
        try:
            email = master_df[master_df['id'] == counterparty_id]['email'].iloc[0]
            return email if pd.notna(email) and email else DEFAULT_REVIEWER_EMAIL
        except IndexError:
            return DEFAULT_REVIEWER_EMAIL

    def run(self, is_simulation: bool = False): # <-- CORRECT INDENTATION
        docs_df = self.dfs['Documents']
        # Find all documents that are currently an exception AND are not already pending review
        exceptions = docs_df[
            docs_df['status'].str.contains('Exception', na=False, case=False)
            & (~docs_df['status'].str.contains('REVIEW_PENDING', na=False))
        ]
        
        if exceptions.empty:
            print("Exception Desk: No new documents requiring human review routing.")
            return self.dfs

        print(f"\n--- Exception Desk: Processing {len(exceptions)} documents ---")
        
        for index, doc in exceptions.iterrows():
            doc_id = doc['id']
            status = doc['status']
            doc_number = doc['doc_number']
            
            # 1. AI AGENT ACTION: Perform Root Cause Analysis
            ai_analysis = self.ai_root_cause_analysis(doc, status)
            self.log_audit(doc_id, "AI_ROOT_CAUSE", ai_analysis)
            
            print(f"\n[EXCEPTION: {doc_number}] Status: {status.split(':')[-1].strip()}")
            print(f"AI Analysis:\n{ai_analysis}")
            
            if is_simulation:
                # --- SIMULATION MODE: Interactive Terminal Correction ---
                print("\n*** SIMULATION MODE: MANUAL INTERVENTION ***")
                
                # Example 1: FX Rate Correction (IDR/MYR)
                if 'FX' in status and doc['currency'] == 'IDR':
                    print(f"Detected missing FX rate for IDR. Suggested Fix: {doc_number} (IDR/MYR).")
                    
                    user_input = input("Enter FX Rate to apply (e.g., 0.0003) or 's' to skip: ").strip()
                    
                    if user_input.lower() not in ['s', 'skip']:
                        try:
                            manual_rate = float(user_input)
                            new_base_total = doc['total'] * manual_rate
                            
                            self.dfs['Documents'].loc[index, 'fx_rate'] = manual_rate
                            # We update the original 'total' field just for the demo flow re-entry
                            self.dfs['Documents'].loc[index, 'total'] = new_base_total 
                            self.dfs['Documents'].loc[index, 'status'] = 'ready'
                            
                            self.log_audit(doc_id, "SIM_CORRECTED", f"Fixed missing IDR FX rate: {manual_rate}. Document re-queued.")
                            print(f"  ✅ Document fixed and marked 'ready' for Posting Engine.")
                            continue # Move to the next document
                        except ValueError:
                            print("  ⚠️ Invalid input. Document will remain in Exception status.")
                
                # --- Fallback in Simulation Mode ---
                # If no specific fix was applied, or user skipped, prepare for email routing anyway.
                if 'ready' not in self.dfs['Documents'].loc[index, 'status'].lower():
                    print("  ⏩ No fix applied in simulation. Preparing for external human review link.")
                
            # --- N8N ORCHESTRATION PREPARATION (ALWAYS RUNS UNLESS FIXED) ---
            if 'ready' not in self.dfs['Documents'].loc[index, 'status'].lower():
                reviewer_email = self.get_reviewer_email(doc)
                
                # Generate unique link with a UUID (uuid is now imported)
                unique_id = str(uuid.uuid4())
                # BASE_WEBHOOK_URL is now defined globally
                review_url_approve = f"{BASE_WEBHOOK_URL}/review/approve?doc_id={doc_id}&key={unique_id}"
                review_url_correct = f"{BASE_WEBHOOK_URL}/correct?doc_id={doc_id}&key={unique_id}"
                
                # Combine URLs and analysis for the n8n data
                review_details = (
                    f"**Document**: {doc_number}\n"
                    f"**Counterparty**: {doc['vendor_customer_id']}\n"
                    f"**Reason**: {status.split(':')[-1].strip()}\n"
                    f"**AI Analysis**: {ai_analysis}\n\n"
                    f"**Approve & Post**: {review_url_approve}\n"
                    f"**Needs Correction (Open Editor)**: {review_url_correct}"
                )
                
                # Update Document State for n8n to read
                self.dfs['Documents'].loc[index, 'reviewer_email'] = reviewer_email
                self.dfs['Documents'].loc[index, 'review_url_approve'] = review_url_approve 
                self.dfs['Documents'].loc[index, 'exception_summary'] = review_details
                self.dfs['Documents'].loc[index, 'status'] = 'REVIEW_PENDING' 
                
                self.log_audit(doc_id, "ROUTE_TO_HUMAN", f"Routed to {reviewer_email} for review.")
                print(f"  > Document {doc_number} flagged 'REVIEW_PENDING' and data prepared for email to {reviewer_email}.")
                
        return self.dfs