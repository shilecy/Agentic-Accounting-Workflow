# agents/classification_agent.py

import os
import json
from google import genai
from google.genai import types
from google.genai.errors import APIError
from dotenv import load_dotenv
from .schemas import ClassificationResult 
from .utils import initialize_gemini_client, log_audit

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class ClassificationAgent:
    def __init__(self, dfs: dict):
        self.dfs = dfs
        # Initialize the Gemini Client with the correct key
        self.client = initialize_gemini_client(self.__class__.__name__)
 
    def classify_document(self, doc_content: str) -> dict:
        """Uses Gemini 2.5 Flash for classification (CORE AI LOGIC)."""
        if not self.client:
            return {'doc_type': 'invoice', 'confidence': 0.95}

        prompt = (
            "Analyze the following document content to determine its accounting type. "
            "Content:\n---\n"
            f"{doc_content[:2000]}..."
        )
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ClassificationResult,
                )
            )
            return json.loads(response.text)
        except APIError as e:
            print(f"Gemini API Error during classification: {e}")
            return {'doc_type': 'other', 'confidence': 0.0}

    def run(self):
        # Full classification logic would iterate over Intake documents here
        return self.dfs