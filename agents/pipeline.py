from .ingestion_agent import IngestionAgent
from .classification_agent import ClassificationAgent
from .extraction_agent import ExtractionAgent
from .validation_agent import ValidationAgent
from .exception_desk_agent import ExceptionDeskAgent
from .posting_engine_agent import PostingEngineAgent
from .reconciliation_agent import ReconciliationAgent
from .reporting_agent import ReportingAgent
from .utils import load_dataframes, save_dataframes
import os
import pandas as pd
from .utils import OUTPUTS_DIR

async def run_async_pipeline(items):
    print("\n🚀 Starting AI pipeline for interview items (Bypassing Ingestion/Extraction)...")
    
    dfs = load_dataframes()

    new_document_records = []
    new_line_item_records = []
    
    # Find the maximum existing LineItems.csv index to start new IDs from
    existing_line_count = len(dfs.get('LineItems', []))
    current_line_index = 0 

    # Convert Pydantic objects back to dictionary format for DataFrame
    for item in items:
        # We'll use the doc_number as the unique ID for the Documents DF
        doc_id = item.doc_number 
        
        # --- 1. Populate Documents DataFrame ---
        new_document_records.append({
            # Match the Documents.csv columns structure
            'id': doc_id, # Using doc_number as the temporary internal ID
            'doc_type': item.doc_type,
            'doc_number': item.doc_number,
            'vendor_customer_name': item.vendor_customer.name, # FLATTENED NESTED FIELD
            'counterparty_type': item.vendor_customer.type,     # FLATTENED NESTED FIELD
            'issue_date': item.issue_date,
            'due_date': item.due_date,
            'payment_term': item.payment_term,
            'currency': item.currency,
            'subtotal': item.subtotal,
            'tax_label': item.tax_label,
            'tax_rate': item.tax_rate,
            'tax_amount': item.tax_amount,
            'shipping': item.shipping,
            'total': item.total,
            'amount_due': item.total, # Start with full amount due
            'status': 'EXTRACTED', # Start status is Extracted
            'confidence': item.extracted_fields_confidence,
            'source': 'n8n_interview_json', # Mark the source
            'file_url': f"storage/{doc_id}.json", # Placeholder file URL
        })
        
        # --- 2. Populate LineItems DataFrame ---
        for i, line in enumerate(item.line_items):
            current_line_index += 1
            new_line_item_records.append({
                'document_id': doc_id, # Link back to the Document
                'line_no': i + 1, # Line number within the document
                'description': line.description,
                'qty': line.qty,
                'uom': line.uom,
                'unit_price': line.unit_price,
                'line_total': line.line_total,
                'gl_hint': line.gl_hint,
                # 'discount' is missing from interview data, assume 0 or handle in agent
                'discount': 0, 
            })

    # Update the Documents DataFrame (crucial step for the subsequent agents)
    dfs['Documents'] = pd.concat([dfs.get('Documents', pd.DataFrame()), pd.DataFrame(new_document_records)], ignore_index=True)
    dfs['LineItems'] = pd.concat([dfs.get('LineItems', pd.DataFrame()), pd.DataFrame(new_line_item_records)], ignore_index=True)
    
    print(f"Loaded {len(new_document_records)} documents and {len(new_line_item_records)} line items into DataFrames.")


    # 1️⃣-3️⃣ Ingestion/Classification/Extraction (BYPASSED)
    print("1-3. Ingestion/Classification/Extraction: Data loaded directly from interview JSONs.")
    
    # 4️⃣ Validation
    validation = ValidationAgent(dfs)
    dfs = validation.run() 
    # ... (Rest of the pipeline remains the same) ...
    print("4. Validation: Documents enriched and AI checked.")

    # 5️⃣ Exception Desk
    exceptions = ExceptionDeskAgent(dfs)
    dfs = exceptions.run()
    print("5. Exception Desk: AI-guided human review/correction completed.")

    # 6️⃣ Posting Engine
    posting = PostingEngineAgent(dfs)
    dfs = posting.run()
    print("6. Posting: Journal Entries created and AR/AP initialized (AI-verified).")

    # 7️⃣ Reconciliation
    recon = ReconciliationAgent(dfs)
    dfs = recon.run()
    print("7. Reconciliation: Bank Feed matched and AR/AP balances updated (AI-assisted).")

    # 8️⃣ Reporting
    reporting = ReportingAgent(dfs, OUTPUTS_DIR)
    dfs = reporting.run()
    print("8. Reporting: Financial reports and Dashboard data generated.")

    save_dataframes(dfs)

    # 🛑 START OF NEW LOGIC (Must be here, after all agents run) 🛑
    
    # 1. Look for any document that ended the Exception Desk run with 'REVIEW_PENDING' status
    exception_doc_series = None # Initialize outside the if/else

    exception_doc = dfs['Documents'][dfs['Documents']['status'] == 'REVIEW_PENDING']

    if not exception_doc.empty:
        # Document found in correct status - use its data
        exception_doc_series = exception_doc.iloc[0]
        print(f"**RETURNING LIVE EXCEPTION DATA: {exception_doc_series.get('doc_number')}**")
    
    # --- TEMPORARY DEBUG/FALLBACK LOGIC ---
    else:
        print("WARNING: REVIEW_PENDING not found. Forcing return of first document data for debug.")
        # Grab the first document for debugging
        exception_doc_series = dfs['Documents'].iloc[0]
    
    # 🛑 CRITICAL FIX: Convert NaNs to None before to_dict()
    # Apply fix to the Series before converting to dictionary
    exception_data = exception_doc_series.where(exception_doc_series.notna(), None).to_dict()
    # Force the URL and email data if the agent logic didn't set it (for safety)
    if exception_data.get('review_url_approve') is None:
        base_url = os.getenv("N8N_REVIEW_WEBHOOK_URL", "http://localhost:5678/webhook/review")
        exception_data['review_url_approve'] = 'f"{base_url}/approve?doc_id=INV-ID-7788&key=DEBUG_FIXED'
        exception_data['reviewer_email'] = 'ssahila007@gmail.com'
        exception_data['doc_number'] = 'INV-ID-7788'
        exception_data['exception_summary'] = exception_data.get('exception_summary', 'DEBUG: FORCED EXCEPTION DATA RETURN')

    print(f"**FORCING DEBUG EXCEPTION DATA: {exception_data.get('doc_number')}**")
    return exception_data