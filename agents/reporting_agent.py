# agents/reporting_agent.py

import pandas as pd
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from .utils import initialize_gemini_client, log_audit

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class ReportingAgent:
    def __init__(self, dfs: dict, outputs_dir: str):
        self.dfs = dfs
        self.outputs_dir = outputs_dir
        self.coas = self.dfs['ChartOfAccounts'].set_index('account')
        self.journals = self.dfs['JournalEntries']
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)

    def ai_generate_commentary(self, report_summary: str) -> str:
        """Uses Gemini to provide commentary/insights on the financial results (AI REASONING)."""
        if not self.client:
            return "Financial Commentary: Generated in Simulation Mode."
        
        prompt = (
            "Analyze the following financial summary data. Provide a brief, insightful commentary (max 3 sentences) on the company's performance and financial health. "
            "Focus on key takeaways, such as profit margin, cash position, or major expense categories."
            f"Financial Summary:\n{report_summary}"
        )
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip()
        except APIError:
            return "AI Commentary generation failed."

    def generate_trial_balance(self):
        """Calculates and saves the Trial Balance."""
        
        tb = self.journals.groupby('account').agg(
            total_debit=('debit', 'sum'),
            total_credit=('credit', 'sum')
        ).fillna(0)
        
        tb = tb.merge(self.coas, left_index=True, right_index=True, how='left')
        
        def calculate_balance(row):
            if row['type'] in ['Asset', 'Expense']: return row['total_debit'] - row['total_credit']
            elif row['type'] in ['Liability', 'Income']: return row['total_credit'] - row['total_debit']
            return row['total_debit'] - row['total_credit']

        tb['balance'] = tb.apply(calculate_balance, axis=1)
        
        final_tb = tb[['type', 'total_debit', 'total_credit', 'balance']].reset_index()
        final_tb.columns = ['Account', 'Type', 'Total Debit (Base)', 'Total Credit (Base)', 'Balance (Base)']
        
        tb_path = os.path.join(self.outputs_dir, "REPORT_Trial_Balance.csv")
        final_tb.to_csv(tb_path, index=False)
        self.log_audit("N/A", "REPORT_GEN", "Generated Trial Balance.")
        print(f"  - Generated Trial Balance at {tb_path}")
        return final_tb

    def generate_financial_summaries(self, tb_df: pd.DataFrame):
        """Generates P&L and Balance Sheet summaries."""
        
        pl_accounts = tb_df[tb_df['Type'].isin(['Income', 'Expense'])].copy()
        total_income = pl_accounts[pl_accounts['Type'] == 'Income']['Balance (Base)'].sum()
        total_expense = pl_accounts[pl_accounts['Type'] == 'Expense']['Balance (Base)'].sum()
        net_profit = total_income - total_expense

        pl_summary = pd.DataFrame([
            {'Metric': 'Total Income', 'Amount': total_income},
            {'Metric': 'Total Expense', 'Amount': total_expense},
            {'Metric': 'Net Profit (Pre-Tax)', 'Amount': net_profit}
        ])
        pl_path = os.path.join(self.outputs_dir, "REPORT_PL_Summary.csv")
        pl_summary.to_csv(pl_path, index=False)
        print(f"  - Generated P&L Summary at {pl_path}")

        bs_accounts = tb_df[tb_df['Type'].isin(['Asset', 'Liability', 'Equity'])].copy()
        total_assets = bs_accounts[bs_accounts['Type'] == 'Asset']['Balance (Base)'].sum()
        total_liabilities = bs_accounts[bs_accounts['Type'] == 'Liability']['Balance (Base)'].sum()
        total_equity_calc = total_assets - total_liabilities
        
        bs_summary = pd.DataFrame([
            {'Metric': 'Total Assets', 'Amount': total_assets},
            {'Metric': 'Total Liabilities', 'Amount': total_liabilities},
            {'Metric': 'Calculated Equity (A-L)', 'Amount': total_equity_calc}
        ])
        bs_path = os.path.join(self.outputs_dir, "REPORT_BS_Summary.csv")
        bs_summary.to_csv(bs_path, index=False)
        print(f"  - Generated Balance Sheet Summary at {bs_path}")

        # AI AGENT ACTION: Generate Commentary
        report_summary = pl_summary.to_markdown() + "\n" + bs_summary.to_markdown()
        commentary = self.ai_generate_commentary(report_summary)
        
        commentary_path = os.path.join(self.outputs_dir, "REPORT_AI_Commentary.txt")
        with open(commentary_path, 'w') as f:
            f.write("--- AI Financial Commentary ---\n")
            f.write(commentary)
        print(f"  - Generated AI Commentary at {commentary_path}")

    def generate_dashboard_data(self):
        """Generates transactional data summarized by month for dashboard visualizations."""
        
        journals = self.journals.copy()
        
        # Ensure date is datetime object
        journals['date'] = pd.to_datetime(journals['date'])
        
        # Create Period Key for Grouping
        journals['period'] = journals['date'].dt.to_period('M')
        
        # Monthly Journal Entry Totals (for activity dashboards)
        monthly_activity = journals.groupby('period').agg(
            total_debits=('debit', 'sum'),
            total_credits=('credit', 'sum'),
            count_je=('je_id', 'nunique')
        ).reset_index()
        monthly_activity['period'] = monthly_activity['period'].astype(str)
        
        activity_path = os.path.join(self.outputs_dir, "DASHBOARD_Monthly_Activity.csv")
        monthly_activity.to_csv(activity_path, index=False)
        print(f"  - Generated Monthly Activity Data at {activity_path}")
        self.log_audit("N/A", "REPORT_GEN", "Generated Monthly Dashboard Data.")

    def run(self):
        """Generates all required financial reports and dashboard data."""
        print("\n8. Reporting: Generating Financial Statements and Dashboard Data...")
        
        if self.journals.empty:
            print("  - WARNING: No Journal Entries found. Skipping report generation.")
            return self.dfs

        # 8.1 Trial Balance
        tb_df = self.generate_trial_balance()
        
        # 8.2 Summaries (P&L and Balance Sheet + AI Commentary)
        self.generate_financial_summaries(tb_df)
        
        # 8.3 Dashboard Data (Monthly/Periodical Summary)
        self.generate_dashboard_data()

        return self.dfs

    def log_audit(self, doc_id, action, details):
        audit_log_df = self.dfs['AuditLog']
        new_log = pd.DataFrame([{'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),'actor': 'ReportingAgent','action': action,'doc_id': doc_id,'details': details}])
        self.dfs['AuditLog'] = pd.concat([audit_log_df, new_log], ignore_index=True)