# agents/posting_engine_agent.py

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

class PostingEngineAgent:
    def __init__(self, dfs: dict):
        self.dfs = dfs
        self.je_counter = len(self.dfs['JournalEntries']) 
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)

    def generate_journal_entry(self, date, doc_id, line_no, account, debit, credit, memo, fx_rate=1.0, base_amount=0.0):
        self.je_counter += 1
        return {
            'je_id': f"JE-{self.je_counter:04d}",
            'date': pd.to_datetime(date).strftime('%Y-%m-%d'),
            'doc_id': doc_id, 'line_no': line_no, 'account': account, 'debit': debit, 'credit': credit,
            'memo': memo, 'fx_rate': fx_rate, 'base_amount': base_amount
        }
    
    def ai_verify_posting(self, doc_summary: dict, line_items: pd.DataFrame) -> bool:
        """Uses Gemini to verify the GL hint based on document type and line item description (AI REASONING)."""
        if not self.client:
            return True 
        
        line_data = line_items[['description', 'gl_hint']].to_markdown(index=False)
        
        prompt = (
            "You are an expert auditor. Review the following proposed General Ledger (GL) hints for a document. "
            "Determine if the GL hint is **HIGHLY INAPPROPRIATE** for the document type and description. "
            
            # --- UPDATED INSTRUCTION ---
            "Output only the word 'FALSE' if the GL hint is clearly and dangerously wrong (e.g., using a Revenue account for an Expense). "
            "Otherwise, output 'TRUE' to approve the posting. The vast majority of hints should be TRUE." 
            # --- END UPDATED INSTRUCTION ---
            
            f"Document Type: {doc_summary['doc_type']}, Vendor/Customer: {doc_summary['counterparty_type']}\n"
            f"Proposed Line Items:\n{line_data}"
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            # Fuzzy logic: returns TRUE unless the response explicitly contains 'FALSE' and not 'TRUE'
            response_text = response.text.strip().upper()
            is_verified = 'TRUE' in response_text or 'FALSE' not in response_text
            
            # This line helps debug, but can be removed once fixed
            if not is_verified:
                print(f"    - AI Verification Failed. Response: {response_text[:50]}...")
            
            return is_verified
            
        except APIError:
            return False

    def log_audit(self, doc_id, action, details):
        audit_log_df = self.dfs['AuditLog']
        new_log = pd.DataFrame([{'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),'actor': 'PostingEngineAgent','action': action,'doc_id': doc_id,'details': details}])
        self.dfs['AuditLog'] = pd.concat([audit_log_df, new_log], ignore_index=True)

    def run(self):
        docs_df = self.dfs['Documents'][self.dfs['Documents']['status'] == 'ready']
        line_items_df = self.dfs['LineItems']
        new_journal_entries = []
        new_ap_entries = []
        new_ar_entries = []

        for _, doc in docs_df.iterrows():
            doc_id = doc['id']
            doc_lines = line_items_df[line_items_df['document_id'] == doc_id]

            # --- NEW CRITICAL STEP: Quotation Skip Fallback ---
            # If the ExtractionAgent failed to skip, the PostingAgent MUST do it.
            doc_type = doc['doc_type']
            if doc_type in ['quotation', 'SO']:
                print(f"SKIPPED: Informational document {doc['doc_number']} ({doc_type}). Skip enforced in Posting Agent.")
                self.dfs['Documents'].loc[self.dfs['Documents']['id'] == doc_id, 'status'] = 'skipped'
                self.log_audit(doc_id, "SKIPPED_INFO_DOC", f"Document type '{doc_type}' is informational, skipping GL post.")
                continue # Skip the rest of the posting logic for this document
            # --- End Quotation Skip Fallback ---

            # --- Standard hardcoded posting logic (remains the same) ---
            doc_type = doc['doc_type']
            issue_date = doc['issue_date']
            total = doc['total']
            tax_amount = doc['tax_amount'] if not pd.isna(doc['tax_amount']) else 0.0
            shipping = doc.get('shipping', 0.0)
            due_date = doc.get('due_date')
            counterparty_id = doc['vendor_customer_id']
            fx_rate = doc['fx_rate']
            base_total = doc['base_amount_total']
            
            print(f"Posting {doc_type}: {doc['doc_number']} (Base: {base_total:.2f})")
            
            # ... (JE creation and AP/AR subledger logic remains the same as previously provided) ...
            
            # 1. Vendor Invoice / Bill
            if doc_type in ['invoice', 'utility_bill']:
                # a) Debit: Expense/Asset (Line Items)
                for line_idx, line in doc_lines.iterrows():
                    gl_account = line['gl_hint'].split(' ')[0] 
                    line_base_amount = line['line_total'] * fx_rate
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, line['line_no'], gl_account, line_base_amount, 0.0, f"Expense for {line['description']}", fx_rate, line['line_total']))
                
                # b) Debit: Input Tax
                tax_base_amount = tax_amount * fx_rate
                if tax_base_amount > 0:
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '1400 Input Tax', tax_base_amount, 0.0, f"{doc['tax_label']} Input Tax", fx_rate, tax_amount))
                
                # c) Debit: Shipping Expense
                if shipping > 0:
                    shipping_base = shipping * fx_rate
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '5300 Office Supplies', shipping_base, 0.0, "Shipping Expense", fx_rate, shipping))

                # d) Credit: Accounts Payable
                new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '2100 Accounts Payable', 0.0, base_total, f"AP for {doc['doc_number']}", fx_rate, total))
                
                # e) Update AP Subledger
                new_ap_entries.append({'doc_id': doc_id, 'counterparty_id': counterparty_id, 'total': base_total, 'amount_due': base_total, 'due_date': due_date, 'status': 'outstanding', 'last_reminder_at': None})
                
            # 2. Customer Sales Invoice
            elif doc_type == 'sales_invoice':
                # a) Credit: Sales/Income (Line Items)
                for line_idx, line in doc_lines.iterrows():
                    gl_account = line['gl_hint'].split(' ')[0]
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, line['line_no'], gl_account, 0.0, line['line_total'], f"Sales for {line['description']}"))
                
                # b) Credit: Output Tax
                if tax_amount > 0:
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '2200 Output Tax', 0.0, tax_amount, f"{doc['tax_label']} Output Tax"))
                
                # c) Debit: Accounts Receivable (Total)
                new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '1200 Accounts Receivable', total, 0.0, f"AR for {doc['doc_number']}"))

                # d) Update AR Subledger
                new_ar_entries.append({'doc_id': doc_id, 'counterparty_id': counterparty_id, 'total': total, 'amount_due': total, 'due_date': due_date, 'status': 'outstanding', 'last_reminder_at': None})
                
            # 3. Credit Note 
            elif doc_type == 'credit_note':
                abs_total = abs(total)
                abs_tax_amount = abs(tax_amount)
                
                # a) Credit: Expense/Asset (Reversal)
                for line_idx, line in doc_lines.iterrows():
                    gl_account = line['gl_hint'].split(' ')[0]
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, line['line_no'], gl_account, 0.0, abs(line['line_total']), f"CN Reversal for {line['description']}"))
                
                # b) Credit: Input Tax Reversal
                if tax_amount < 0:
                    new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '1400 Input Tax', 0.0, abs_tax_amount, f"{doc['tax_label']} Input Tax Reversal"))
                
                # c) Debit: Accounts Payable (Total)
                new_journal_entries.append(self.generate_journal_entry(issue_date, doc_id, 0, '2100 Accounts Payable', abs_total, 0.0, f"AP reduction for {doc['doc_number']}"))

                # d) Update AP Subledger 
                new_ap_entries.append({'doc_id': doc_id, 'counterparty_id': counterparty_id, 'total': total, 'amount_due': total, 'due_date': due_date, 'status': 'outstanding', 'last_reminder_at': None})

            # --- UPDATE DATAFRAMES ---
            self.dfs['Documents'].loc[self.dfs['Documents']['id'] == doc_id, 'status'] = 'posted'
            self.log_audit(doc_id, "POSTED", f"Created journal entries.")

        # --- UPDATE DATAFRAMES (Pandas Warning Fixes) ---
    
        # 1. JournalEntries
        if new_journal_entries:
            new_je_df = pd.DataFrame(new_journal_entries)
            if self.dfs['JournalEntries'].empty:
                self.dfs['JournalEntries'] = new_je_df
            else:
                self.dfs['JournalEntries'] = pd.concat([self.dfs['JournalEntries'], new_je_df], ignore_index=True)

        # 2. AP
        if new_ap_entries: 
            new_ap_df = pd.DataFrame(new_ap_entries)
            if self.dfs['AP'].empty:
                self.dfs['AP'] = new_ap_df
            else:
                self.dfs['AP'] = pd.concat([self.dfs['AP'], new_ap_df], ignore_index=True)

        # 3. AR
        if new_ar_entries:
            new_ar_df = pd.DataFrame(new_ar_entries)
            if self.dfs['AR'].empty:
                self.dfs['AR'] = new_ar_df
            else:
                self.dfs['AR'] = pd.concat([self.dfs['AR'], new_ar_df], ignore_index=True)

        return self.dfs