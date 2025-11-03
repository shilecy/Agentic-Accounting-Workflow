# agents/utils.py

import os
import pandas as pd
from dotenv import load_dotenv
from google import genai

# Load environment variables once
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATA_DIR = os.getenv("DATA_DIR", "../data")
OUTPUTS_DIR = os.getenv("OUTPUTS_DIR", "../outputs")
LOGS_DIR = os.getenv("LOGS_DIR", "../logs") # Used for creating the directory


def initialize_gemini_client(agent_name: str) -> genai.Client | None:
    """Initializes the Gemini client or returns None if the API key is missing."""
    if not GEMINI_API_KEY:
        print(f"WARNING: {agent_name} is running in SIMULATION mode. GEMINI_API_KEY is not set.")
        return None
    try:
        # Client initialization is non-blocking but might fail later.
        # We proceed and rely on try/except blocks in agent logic for API failures.
        client = genai.Client(api_key=GEMINI_API_KEY)
        return client
    except Exception as e:
        print(f"ERROR: Failed to initialize Gemini client for {agent_name}. Running in simulation mode. Error: {e}")
        return None

def log_audit(dfs: dict, actor: str, doc_id: str, action: str, details: str):
    """
    Standardized function to log an activity into the AuditLog DataFrame.

    Args:
        dfs (dict): The dictionary of all project DataFrames.
        actor (str): The name of the agent/module performing the action.
        doc_id (str): The ID of the document or transaction affected.
        action (str): The specific action performed (e.g., 'POSTED', 'AI_EXCEPTION_ANALYSIS').
        details (str): Detailed notes on the outcome or decision.
    """
    audit_log_df = dfs.get('AuditLog', pd.DataFrame())
    
    # Define the structure if the DataFrame is empty (e.g., first run)
    if audit_log_df.empty:
        audit_log_df = pd.DataFrame(columns=['timestamp', 'actor', 'action', 'doc_id', 'details'])

    new_log = pd.DataFrame([{
        'timestamp': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
        'actor': actor,
        'action': action,
        'doc_id': doc_id,
        'details': details
    }])
    
    # Concatenate and update the DataFrame in the dictionary
    dfs['AuditLog'] = pd.concat([audit_log_df, new_log], ignore_index=True)

def load_dataframes():
    """Loads all CSV data into a dictionary of DataFrames."""
    dfs = {}
    # DATA_DIR must be defined globally or passed in
    csv_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    for file_name in csv_files:
        key = file_name.replace('.csv', '')
        file_path = os.path.join(DATA_DIR, file_name)
        
        # Files that start empty and will be appended to
        is_transactional_file = key in ['JournalEntries', 'AP', 'AR', 'AuditLog']
        
        # Check if file is missing, or exists but is effectively empty (less than 100 bytes)
        if is_transactional_file and (not os.path.exists(file_path) or os.path.getsize(file_path) < 100):
            
            # 1. Attempt to read header only (if file contains only headers)
            try:
                df = pd.read_csv(file_path).head(0)
            except pd.errors.EmptyDataError:
                # 2. If the file is truly 0 bytes, manually define columns
                if key == 'JournalEntries':
                    df = pd.DataFrame(columns=['je_id', 'date', 'doc_id', 'line_no', 'account', 'debit', 'credit', 'memo', 'fx_rate', 'base_amount'])
                elif key == 'AP':
                    df = pd.DataFrame(columns=['doc_id', 'counterparty_id', 'total', 'amount_due', 'due_date', 'status', 'last_reminder_at'])
                elif key == 'AR':
                    df = pd.DataFrame(columns=['doc_id', 'counterparty_id', 'total', 'amount_due', 'due_date', 'status', 'last_reminder_at'])
                elif key == 'AuditLog':
                    df = pd.DataFrame(columns=['timestamp', 'actor', 'action', 'doc_id', 'details'])
                else:
                    # Fallback for unexpected case, should not happen here
                    df = pd.DataFrame() 
        else:
            # For all other files (COA, Documents, BankFeed, etc.), read normally
            df = pd.read_csv(file_path)
            
        dfs[key] = df
        print(f"Loaded {file_name} with {len(dfs[key])} records.")
    return dfs

def save_dataframes(dfs):
    """Saves updated DataFrames (AuditLog, Subledgers, JEs) back to the outputs directory."""
    print("\n--- Saving Updated DataFrames (Dashboard Source Data) ---")    
    # Define which keys to save
    keys_to_save = ['JournalEntries', 'AP', 'AR', 'AuditLog', 'Documents']
    
    for key, df in dfs.items():
        # Only save core transactional and audit data for dashboard/persistence
        if key in keys_to_save:
            
            if key == 'AuditLog':
                # Use the dedicated LOGS_DIR for the AuditLog
                output_dir = LOGS_DIR
            else:
                # Use the default OUTPUTS_DIR for all other files
                output_dir = OUTPUTS_DIR
                
            # Ensure the correct directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Construct the final path
            output_path = os.path.join(output_dir, f"{key}_updated.csv")
   
            df.to_csv(output_path, index=False)
            print(f"Saved {key} to {output_path}")