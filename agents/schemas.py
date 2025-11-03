# agents/schemas.py

from pydantic import BaseModel, Field, conint
from typing import Literal, Optional, List

# --- NEW VENDOR/CUSTOMER MODEL ---
class VendorCustomer(BaseModel):
    name: str
    registration_number: Optional[str] = None
    phone: Optional[str] = None
    type: Literal['supplier', 'customer'] = Field(description="Is this a supplier (vendor) or a customer?")

# 0. INPUT MODEL FOR THE FASTAPI ENDPOINT (matches the interview JSONs)
class ExtractedDocItem(BaseModel):
    # Core Fields
    doc_type: str
    doc_number: str
    issue_date: str
    due_date: Optional[str] = None
    payment_term: Optional[str] = None
    
    # Nested Object
    vendor_customer: VendorCustomer # <--- This is the new nested model
    
    # Financials
    currency: str
    subtotal: float
    tax_label: Optional[str] = None
    tax_rate: float
    tax_amount: float
    shipping: float = 0.0 # Default based on your data examples
    total: float
    
    # Line Items (uses the existing LineItem schema)
    line_items: List['LineItem'] = Field(
        ..., 
        min_length=1,
        description="List of extracted line items."
    )
    
    extracted_fields_confidence: float

# 1. Schema for Document Classification
class ClassificationResult(BaseModel):
    """Structured output for document classification."""
    doc_type: Literal['invoice', 'quotation', 'bill', 'receipt', 'credit_note', 'delivery_order', 'SO', 'PO', 'other'] = Field(
        description="The recognized type of the accounting document."
    )
    confidence: float = Field(
        description="Confidence score (0.0 to 1.0) for the classification.",
        ge=0.0,
        le=1.0
    )

# 2. Schema for Line Item Extraction
class LineItem(BaseModel):
    """Structured output for a single line item."""
    description: str = Field(description="Description of the product or service.")
    qty: float = Field(description="Quantity.")
    uom: str = Field(description="Unit of measurement (e.g., pcs, package, bill).")
    unit_price: float = Field(description="Price per unit.")
    line_total: float = Field(description="Total amount for this line (qty * unit_price).")
    gl_hint: str = Field(description="Suggested general ledger account code and name (e.g., '5100 COGS').")

# 3. Schema for AI Extraction
class ExtractionResult(BaseModel):
    """Structured output for key field and line item extraction."""
    doc_number: str = Field(description="Document number.")
    issue_date: str = Field(description="Issue date (YYYY-MM-DD format).")
    due_date: Optional[str] = Field(description="Due date (YYYY-MM-DD format).")
    payment_term: Optional[str] = Field(description="Payment term (e.g., 'Net 30').")
    
    vendor_customer_name: str = Field(description="Name of the vendor or customer.")
    registration_number: Optional[str] = Field(description="Tax or corporate registration number.")
    
    currency: str = Field(description="Currency code (e.g., MYR, USD).")
    subtotal: float = Field(description="Total before tax and shipping.")
    tax_label: Optional[str] = Field(description="Tax label (e.g., SST, VAT, GST).")
    tax_rate: float = Field(description="Applicable tax rate (e.g., 0.08 for 8%).")
    tax_amount: float = Field(description="Total tax amount.")
    shipping: float = Field(description="Shipping or handling amount (0 if none).")
    total: float = Field(description="Grand total amount (subtotal + tax + shipping).")
    
    line_items: List[LineItem] = Field(
        ..., 
        min_length=1,
        description="List of extracted line items."
    )
    
    extracted_fields_confidence: float = Field(
        description="Overall confidence score for the extraction (0.0 to 1.0).",
        ge=0.0,
        le=1.0
    )