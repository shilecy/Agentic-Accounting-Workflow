# agents/validation_agent.py

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
import os
from .utils import initialize_gemini_client, log_audit

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class ValidationAgent:
    def __init__(self, dfs: dict):
        self.dfs = dfs
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)

    def get_fx_rate(self, date_str, from_currency, to_currency='MYR'):
        if from_currency == to_currency:
            return 1.0
        
        fx_df = self.dfs['FXRates']
        fx_df['date'] = pd.to_datetime(fx_df['date'], format='%d/%m/%Y', errors='coerce')
        doc_date = pd.to_datetime(date_str, format='%d/%m/%Y', errors='coerce')
        
        if pd.isna(doc_date):
             return None 
        
        pair = f"{from_currency}/{to_currency}"
        rate_row = fx_df[
            (fx_df['pair'] == pair) & 
            (fx_df['date'] <= doc_date)
        ].sort_values(by='date', ascending=False).head(1)
        
        if not rate_row.empty:
            return rate_row['rate'].iloc[0]
        return None 
    
    def ai_analyze_exception(self, document_data: dict, error_message: str) -> str:
        """Uses Gemini to analyze a validation failure (AI REASONING)."""
        if not self.client:
            return "FIX: Exception requires manual review (Simulation Mode)."
        
        prompt = (
            "You are a senior accounting analyst. Analyze the document data and the error to determine the root cause "
            "and suggest the required manual action. The output **MUST be a single, concise recommendation**, "
            "and **MUST be prefixed with 'FIX: '**. Do not add any other text, explanation, or punctuation."
            "The fix should be highly specific to the missing data (e.g., 'FIX: Look up 2025-10-05 IDR/MYR rate').\n"
            f"Validation Error: {error_message}\n"
            f"Document Data: {document_data}" # Ensure full data is passed if available
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0 
                )
            )
            return response.text.strip()
        except APIError:
            return "FIX: AI Analysis Failed."

    def log_audit(self, doc_id, action, details):
        audit_log_df = self.dfs['AuditLog']
        new_log = pd.DataFrame([{'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),'actor': 'ValidationAgent','action': action,'doc_id': doc_id,'details': details}])
        self.dfs['AuditLog'] = pd.concat([audit_log_df, new_log], ignore_index=True)

    def run(self):
        docs_df = self.dfs['Documents']
        
        if 'fx_rate' not in docs_df.columns: docs_df['fx_rate'] = 1.0
        if 'base_amount_total' not in docs_df.columns: docs_df['base_amount_total'] = docs_df['total']
            
        for index, row in docs_df.iterrows():
            if row['status'] == 'ready':
                # --- AI/Rule-based Enrichment/Validation ---
                if row['currency'] != 'MYR':
                    rate = self.get_fx_rate(row['issue_date'], row['currency'])
                    
                    if rate is not None:
                        docs_df.loc[index, 'fx_rate'] = rate
                        docs_df.loc[index, 'base_amount_total'] = row['total'] * rate
                    else:
                        error_msg = f"No FX rate found for {row['currency']} on {row['issue_date']}. Base total cannot be calculated."
                        
                        # AI AGENT ACTION: Analyze the exception
                        ai_recommendation = self.ai_analyze_exception(row.to_dict(), error_msg)
                        
                        print(f"!! EXCEPTION: No FX rate found for {row['currency']} on {row['issue_date']}. Setting status to 'Exception'.")
                        docs_df.loc[index, 'status'] = f'Exception: FX - {ai_recommendation.replace("FIX: ", "")[:50]}'
                        self.log_audit(row['id'], "AI_EXCEPTION_ANALYSIS", ai_recommendation)
                        
        self.dfs['Documents'] = docs_df
        return self.dfs