# agents/reconciliation_agent.py

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

class ReconciliationAgent:
    def __init__(self, dfs: dict):
        self.dfs = dfs
        self.je_counter = len(self.dfs['JournalEntries'])
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)

    def generate_payment_entry(self, date, doc_id, account_dr, account_cr, amount, memo):
        amount = abs(amount) 
        self.je_counter += 2
        return (
            {'date': pd.to_datetime(date).strftime('%Y-%m-%d'), 'je_id': f"JE-{self.je_counter - 1:04d}", 
             'doc_id': doc_id, 'line_no': 0, 'account': account_dr, 'debit': amount, 'credit': 0.0,
             'memo': memo, 'fx_rate': 1.0, 'base_amount': amount},
            {'date': pd.to_datetime(date).strftime('%Y-%m-%d'), 'je_id': f"JE-{self.je_counter:04d}", 
             'doc_id': doc_id, 'line_no': 0, 'account': account_cr, 'debit': 0.0, 'credit': amount,
             'memo': memo, 'fx_rate': 1.0, 'base_amount': amount}
        )
    
    def ai_suggest_match(self, bank_txn: dict, outstanding_docs: pd.DataFrame) -> str:
        """Uses Gemini to suggest a match (doc_number) based on memo and amount difference (AI REASONING)."""
        if not self.client:
            return None
        
        potential_matches = outstanding_docs[['doc_number', 'amount_due', 'due_date']].to_markdown(index=False)
        
        prompt = (
            f"Bank Transaction: Date={bank_txn['date']}, Amount={bank_txn['amount']:.2f}, Memo='{bank_txn['memo']}'.\n"
            "Outstanding Documents:\n"
            f"{potential_matches}\n"
            "Identify the single best matching 'doc_number' from the list. If no good match is found (e.g., amount mismatch > 1%), respond with 'UNMATCHED'."
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            result = response.text.strip()
            return result if result not in ['UNMATCHED', 'NONE'] else None
        except APIError:
            return None 

    def log_audit(self, doc_id, action, details):
        audit_log_df = self.dfs['AuditLog']
        new_log = pd.DataFrame([{'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),'actor': 'ReconciliationAgent','action': action,'doc_id': doc_id,'details': details}])
        self.dfs['AuditLog'] = pd.concat([audit_log_df, new_log], ignore_index=True)

    def run(self):
        bank_feed_df = self.dfs['BankFeed'].copy()
        bank_feed_df['date'] = pd.to_datetime(bank_feed_df['date'], errors='coerce')
        bank_feed_df['guess_doc_number'] = bank_feed_df['guess_doc_number'].astype(str).str.strip()
        new_journal_entries = []
        ap_df = self.dfs['AP'].copy()
        
        # --- 1. Subledger Preparation (Apply CN to INV) ---
        cn_row = ap_df[(ap_df['doc_id'] == 'DOC-CN-0001') & (ap_df['status'] == 'outstanding')]
        inv_row_idx = ap_df[ap_df['doc_id'] == 'DOC-INV-0001'].index
        if not cn_row.empty and not inv_row_idx.empty:
            cn_amount = cn_row['total'].iloc[0]
            ap_df.loc[inv_row_idx, 'amount_due'] += cn_amount 
            ap_df.loc[cn_row.index, 'status'] = 'cleared_applied'
            print(f"Applied CN-2025-0003 ({-cn_amount:.2f}) to INV-2025-00123. New INV due: {ap_df.loc[inv_row_idx, 'amount_due'].iloc[0]:.2f}")

        # --- 2. Bank Feed Matching ---
        for index, bank_txn in bank_feed_df.iterrows():
            date = bank_txn['date']
            
            if pd.isna(date):
                print(f"SKIPPING: Bank Feed transaction at index {index} has an invalid date or format.")
                self.log_audit('N/A', "ERROR", "Bank Feed txn failed due to invalid date/format.")
                continue
            
            guess_doc_number = bank_txn['guess_doc_number']
            amount = bank_txn['amount']
            
            matching_docs = self.dfs['Documents'][self.dfs['Documents']['doc_number'] == guess_doc_number]
            
            if matching_docs.empty:
                # AI AGENT ACTION: Use AI for fuzzy matching if the direct guess fails
                outstanding_subledger = ap_df if amount < 0 else self.dfs['AR']
                # Filter to avoid sending thousands of records to the LLM (e.g., only outstanding)
                outstanding_subledger = outstanding_subledger[outstanding_subledger['status'].isin(['outstanding', 'partial_paid'])]
                
                ai_guess = self.ai_suggest_match(bank_txn.to_dict(), outstanding_subledger)
                
                if ai_guess:
                    guess_doc_number = ai_guess
                    matching_docs = self.dfs['Documents'][self.dfs['Documents']['doc_number'] == guess_doc_number]
                    print(f"FUZZY MATCH: AI suggests {ai_guess} for Bank Memo '{bank_txn['memo']}'.")
                else:
                    print(f"UNMATCHED: {bank_txn['guess_doc_number']} in bank feed. Requires manual review.")
                    self.log_audit('N/A', "UNMATCHED", f"Bank txn failed standard and AI match. Memo: {bank_txn['memo']}")
                    continue
                
            doc_id = matching_docs['id'].iloc[0]
            
            # ... (AP/AR payment logic remains the same as previously provided) ...
            
            # AP Payment (Negative Amount)
            if amount < 0:
                ap_match_idx = ap_df[(ap_df['doc_id'] == doc_id) & (ap_df['amount_due'] > 0.01)].index
                if not ap_match_idx.empty:
                    abs_amount = abs(amount)
                    amount_due = ap_df.loc[ap_match_idx, 'amount_due'].iloc[0]
                    dr_je, cr_je = self.generate_payment_entry(date, doc_id, '2100 Accounts Payable', '1100 Cash/Bank', abs_amount, f"Payment for {guess_doc_number}")
                    new_journal_entries.extend([dr_je, cr_je])
                    
                    new_amount_due = amount_due - abs_amount
                    ap_df.loc[ap_match_idx, 'amount_due'] = new_amount_due
                    status = 'paid' if new_amount_due <= 0.01 else 'partial_paid'
                    ap_df.loc[ap_match_idx, 'status'] = status
                    
                    print(f"MATCH: Paid {abs_amount:.2f} for AP {guess_doc_number}. Status: {status}")
                    self.log_audit(doc_id, "CLEARED_AP", f"Matched bank payment. Status updated to {status}.")
                        
            # AR Collection (Positive Amount)
            elif amount > 0:
                ar_match_idx = self.dfs['AR'][(self.dfs['AR']['doc_id'] == doc_id) & (self.dfs['AR']['amount_due'] > 0.01)].index
                if not ar_match_idx.empty:
                    dr_je, cr_je = self.generate_payment_entry(date, doc_id, '1100 Cash/Bank', '1200 Accounts Receivable', amount, f"Collection for {guess_doc_number}")
                    new_journal_entries.extend([dr_je, cr_je])
                    
                    amount_due = self.dfs['AR'].loc[ar_match_idx, 'amount_due'].iloc[0]
                    new_amount_due = amount_due - amount
                    self.dfs['AR'].loc[ar_match_idx, 'amount_due'] = new_amount_due
                    status = 'paid' if new_amount_due <= 0.01 else 'partial_paid'
                    self.dfs['AR'].loc[ar_match_idx, 'status'] = status
                    
                    print(f"MATCH: Received {amount:.2f} for AR {guess_doc_number}. Status: {status}")
                    self.log_audit(doc_id, "CLEARED_AR", f"Matched bank collection. Status updated to {status}.")

        # --- 3. Finalize Updates ---
        self.dfs['AP'] = ap_df
        self.dfs['JournalEntries'] = pd.concat([self.dfs['JournalEntries'], pd.DataFrame(new_journal_entries)], ignore_index=True)
        return self.dfs