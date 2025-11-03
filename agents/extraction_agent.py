# agents/extraction_agent.py

import os
import json
from google import genai
from google.genai import types
from google.genai.errors import APIError
from dotenv import load_dotenv
from .schemas import ExtractionResult 
import pandas as pd
from .utils import initialize_gemini_client, log_audit

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class ExtractionAgent:
    def __init__(self, dfs: dict):
        self.dfs = dfs
        self.coas = dfs.get('ChartOfAccounts', pd.DataFrame())
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)
        
    def extract_fields(self, doc_content: str, doc_type: str) -> dict:
        """Uses Gemini 2.5 Flash for key field and line item extraction (CORE AI LOGIC)."""
        if not self.client:
            # Simulation returns sample data structure
            try:
                # NOTE: Ensure 'INV-2025-00123.json' exists in your data folder
                with open(os.path.join(os.path.dirname(__file__), '..', 'data', 'INV-2025-00123.json'), 'r') as f:
                    return json.load(f)
            except FileNotFoundError:
                 print("WARNING: Simulation mode sample JSON not found. Returning minimal structure.")
                 return {'extracted_fields_confidence': 0.0, 'line_items': []}

        coas_list = self.coas['account'].tolist()
        
        prompt = (
            f"Extract all key fields and line items from the '{doc_type}' document. "
            "IMPORTANT: Provide 'gl_hint' by selecting the most appropriate General Ledger account code and name from this list: "
            f"{coas_list}. The format must be 'CODE NAME' (e.g., '5100 COGS'). "
            "Ensure the output strictly adheres to the requested JSON schema.\n"
            "Document Content:\n---\n"
            f"{doc_content}"
        )
        
        try:
            # NOTE: response_schema=ExtractionResult requires the schema to be defined/imported
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractionResult, 
                )
            )
            return json.loads(response.text)
        except APIError as e:
            print(f"Gemini API Error during extraction: {e}")
            return {'extracted_fields_confidence': 0.0}

    def run(self):
        documents_df = self.dfs['Documents']
        line_items_df = self.dfs['LineItems']
        new_line_items = []
        
        # Only process documents that are ready
        for index, doc in documents_df[documents_df['status'] == 'ready'].iterrows():
            doc_id = doc['id']
            doc_type = doc['doc_type']

            # --- 1. EARLY SKIP CHECK: Non-posting documents (e.g., Quotations) ---
            if doc_type in ['quotation', 'SO']: 
                # Use .loc with the current index on the local copy
                documents_df.loc[index, 'status'] = 'skipped' 

                log_audit(self.dfs, self.__class__.__name__, doc_id, "SKIPPED_INFO_DOC", 
                        f"Document type '{doc_type}' is informational and skipped before extraction.")
                print(f"SKIPPED: Document {doc_id} ({doc_type}) is informational. Skipped extraction.")
                continue # Skip the rest of the loop for this document
            
            # --- 2. LOAD CONTENT (Placeholder for actual file reading) ---
            # NOTE: You'll need to read the actual document content (e.g., PDF text) here.
            # For simulation, we use a placeholder:
            doc_content = f"Content for {doc_id} of type {doc_type}..."

            # --- 3. PERFORM EXTRACTION ---
            print(f"Extracting fields for {doc_id} ({doc_type})...")
            try:
                extraction_data = self.extract_fields(doc_content, doc_type)
                
                # Check for successful extraction
                confidence = extraction_data.get('extracted_fields_confidence', 0.0)
                if not extraction_data or confidence < 0.1:
                    raise ValueError("AI returned insufficient or low-confidence data.")

                # --- 4. UPDATE Documents DATAFRAME (Header Fields) ---
                documents_df.loc[index, 'status'] = 'extracted'
                documents_df.loc[index, 'confidence'] = confidence
                
                # Update other header fields in documents_df if extraction_data contains them
                # Example: documents_df.loc[index, 'total'] = extraction_data.get('total')


                # --- 5. COLLECT Line Items ---
                for line_no, line in enumerate(extraction_data.get('line_items', [])):
                    new_line_items.append({
                        'document_id': doc_id,
                        'line_no': line_no + 1,
                        'description': line.get('description', 'N/A'),
                        'quantity': line.get('quantity', 0),
                        'unit_price': line.get('unit_price', 0.0),
                        'amount': line.get('amount', 0.0),
                        'gl_hint': line.get('gl_hint', '5000 Consulting Exp'),
                    })
                
                log_audit(self.dfs, self.__class__.__name__, doc_id, "FIELDS_EXTRACTED", 
                          f"Extraction complete. Confidence: {documents_df.loc[index, 'confidence']:.2f}")

            except Exception as e:
                # --- 6. HANDLE EXTRACTION EXCEPTION ---
                documents_df.loc[index, 'status'] = 'Exception'
                log_audit(self.dfs, self.__class__.__name__, doc_id, "EXTRACTION_ERROR", 
                          f"Extraction failed. Rerouted to Exception Desk. Error: {e}")
                print(f"!! EXTRACTION EXCEPTION: {doc_id} failed. Rerouting.")

        # --- 7. FINALIZE LineItems DATAFRAME ---
        if new_line_items:
            # Check for FutureWarning conditions before concatenating
            if line_items_df.empty:
                 self.dfs['LineItems'] = pd.DataFrame(new_line_items)
            else:
                 self.dfs['LineItems'] = pd.concat([line_items_df, pd.DataFrame(new_line_items)], ignore_index=True)
            
        self.dfs['Documents'] = documents_df
        return self.dfs