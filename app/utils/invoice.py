# app/invoice.py
import os
import logging
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP

import requests
from fastapi import APIRouter, Body, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, Flowable
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "generated_pdfs")
DEFAULT_TIMEOUT = 6
DEFAULT_CURRENCY = "$"

# Ensure PDF directory exists
os.makedirs(PDF_DIR, exist_ok=True)


class InvoiceGenerationError(Exception):
    """Custom exception for invoice generation errors."""
    pass


# Pydantic Models
class InvoiceItem(BaseModel):
    """Model for invoice line items."""
    name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = Field(default=0, ge=0)
    unit_price: Optional[float] = Field(default=0, ge=0)
    total: Optional[float] = Field(default=None, ge=0)


class InvoicePayload(BaseModel):
    """Model for invoice payload data."""
    # Required fields
    invoice_number: str = Field(..., min_length=1)
    
    # Company information
    company_name: Optional[str] = None
    company_address: Optional[str] = None
    company_email: Optional[str] = None  # Using str instead of EmailStr to avoid email-validator dependency
    company_phone: Optional[str] = None
    company_logo_url: Optional[str] = None
    logo_url: Optional[str] = None  # Alternative field name
    
    # Client information
    client_name: Optional[str] = None
    client_address: Optional[str] = None
    client_email: Optional[str] = None  # Using str instead of EmailStr
    
    # Invoice metadata
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = Field(default="$", max_length=10)
    tax_rate: Optional[float] = Field(default=0, ge=0, le=1)
    
    # Invoice items
    items: Optional[List[InvoiceItem]] = Field(default_factory=list)
    
    # Additional information
    notes: Optional[str] = None
    terms: Optional[str] = None
    
    # Payment information
    payment_info_checks: Optional[str] = None
    payment_info_paypal: Optional[str] = None
    payment_info_venmo: Optional[str] = None
    payment_info_cashapp: Optional[str] = None
    payment_info_zelle: Optional[str] = None


class InvoiceCalculator:
    """Handles invoice calculations with precision."""
    
    @staticmethod
    def calculate_totals(items: List[Dict[str, Any]], tax_rate: float) -> Tuple[Decimal, Decimal, Decimal]:
        subtotal = Decimal('0')
        
        for item in items:
            # Calculate item total if not provided
            item_total = item.get("total")
            if item_total is None:
                quantity = Decimal(str(item.get("quantity", 0)))
                unit_price = Decimal(str(item.get("unit_price", 0)))
                item_total = quantity * unit_price
            
            subtotal += Decimal(str(item_total))
        
        tax_amount = subtotal * Decimal(str(tax_rate))
        grand_total = subtotal + tax_amount
        
        # Round to 2 decimal places
        subtotal = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        tax_amount = tax_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        grand_total = grand_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        return subtotal, tax_amount, grand_total


class ImageHandler:
    """Handles image fetching and processing for invoices."""
    
    @staticmethod
    def fetch_image_bytes(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[BytesIO]:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return BytesIO(response.content)
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch image from {url}: {e}")
            return None
    
    @staticmethod
    def create_image(source: Optional[str], width: float, height: float) -> Optional[Image]:
        if not source:
            return None
        
        try:
            if source.startswith(("http://", "https://")):
                image_bytes = ImageHandler.fetch_image_bytes(source)
                if image_bytes:
                    return Image(image_bytes, width=width, height=height)
            elif os.path.exists(source):
                return Image(source, width=width, height=height)
        except Exception as e:
            logger.warning(f"Failed to create image from {source}: {e}")
        
        return None


class CurrencyFormatter:
    """Handles currency formatting."""
    
    @staticmethod
    def format_money(amount: float | Decimal, currency: str = DEFAULT_CURRENCY) -> str:
        if isinstance(amount, Decimal):
            amount = float(amount)
        
        return f"{currency}{amount:,.2f}"


class InvoiceStyleManager:
    """Manages PDF styles and formatting."""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._create_custom_styles()
    
    def _create_custom_styles(self):
        """Create custom paragraph styles."""
        self.normal = self.styles["Normal"]
        self.normal.spaceAfter = 6
        
        self.small_bold = ParagraphStyle(
            "small_bold", 
            parent=self.normal, 
            fontSize=9,
            fontName="Helvetica-Bold"
        )
        
        self.right_small = ParagraphStyle(
            "right_small", 
            parent=self.normal, 
            alignment=2,  # Right alignment
            fontSize=10
        )
        
        self.invoice_title_style = ParagraphStyle(
            "invoice_title_style",
            parent=self.styles["h1"],
            fontSize=36,
            fontName="Helvetica-Bold", # Using Helvetica-Bold for a strong, clear title
            spaceAfter=12,
            leading=40
        )

        self.business_name_style = ParagraphStyle(
            "business_name_style",
            parent=self.normal,
            fontSize=16,
            fontName="Helvetica-Bold",
            alignment=2, # Right alignment
            spaceAfter=6
        )

        self.header_info_style = ParagraphStyle(
            "header_info_style",
            parent=self.normal,
            fontSize=10,
            alignment=2, # Right alignment
            spaceAfter=3
        )

        self.invoice_meta_left_style = ParagraphStyle(
            "invoice_meta_left_style",
            parent=self.normal,
            fontSize=10,
            fontName="Helvetica-Bold",
            spaceAfter=3
        )

        self.invoice_meta_value_left_style = ParagraphStyle(
            "invoice_meta_value_left_style",
            parent=self.normal,
            fontSize=10,
            spaceAfter=6
        )

        self.payment_info_title_style = ParagraphStyle(
            "payment_info_title_style",
            parent=self.normal,
            fontSize=12,
            fontName="Helvetica-Bold",
            spaceAfter=6
        )

        self.payment_info_detail_style = ParagraphStyle(
            "payment_info_detail_style",
            parent=self.normal,
            fontSize=10,
            spaceAfter=3
        )

        self.prompt_payment_style = ParagraphStyle(
            "prompt_payment_style",
            parent=self.normal,
            fontSize=10,
            alignment=2, # Right alignment
            fontName="Helvetica-Bold",
            spaceBefore=12
        )


class InvoicePDFGenerator:
    """Generates PDF invoices using ReportLab."""
    
    def __init__(self):
        self.calculator = InvoiceCalculator()
        self.image_handler = ImageHandler()
        self.currency_formatter = CurrencyFormatter()
        self.style_manager = InvoiceStyleManager()
    
    def generate_pdf(self, invoice_id: str, data: Dict[str, Any] | InvoicePayload) -> str:
        try:
            # Convert Pydantic model to dict if needed
            if isinstance(data, InvoicePayload):
                data = data.model_dump()
            return self._create_pdf_document(invoice_id, data)
        except Exception as e:
            logger.error(f"Failed to generate PDF for invoice {invoice_id}: {e}")
            raise InvoiceGenerationError(f"PDF generation failed: {str(e)}")
    
    def _create_pdf_document(self, invoice_id: str, data: Dict[str, Any]) -> str:
        """Create the PDF document with all sections."""
        file_path = os.path.join(PDF_DIR, f"{invoice_id}.pdf")
        
        doc = SimpleDocTemplate(
            file_path, 
            pagesize=A4,
            leftMargin=20 * mm, 
            rightMargin=20 * mm,
            topMargin=18 * mm, 
            bottomMargin=18 * mm
        )
        
        elements: List[Flowable] = []
        
        # Add document sections
        elements.extend(self._create_header_section(data))
        elements.append(Spacer(1, 6))
        elements.extend(self._create_billing_section(data))
        elements.append(Spacer(1, 12))
        elements.extend(self._create_items_table(data))
        elements.extend(self._create_notes_section(data))
        
        doc.build(elements)
        return file_path
    
    def _create_header_section(self, data: Dict[str, Any]) -> List[Flowable]:
        """Create header section with invoice title, company info, and logo."""
        elements: List[Flowable] = []

        # Left side: INVOICE title, invoice number, date
        invoice_title = Paragraph("INVOICE", self.style_manager.invoice_title_style)
        
        invoice_number = data.get('invoice_number', 'N/A')
        invoice_date = data.get('invoice_date', 'N/A')

        invoice_meta_left = [
            Paragraph("INVOICE NO.:", self.style_manager.invoice_meta_left_style),
            Paragraph(invoice_number, self.style_manager.invoice_meta_value_left_style),
            Paragraph("DATE ISSUED", self.style_manager.invoice_meta_left_style),
            Paragraph(invoice_date, self.style_manager.invoice_meta_value_left_style),
        ]

        # Right side: Logo, Business Name, Company Info
        logo_url = data.get("company_logo_url") or data.get("logo_url")
        # Adjust logo size to be larger and more prominent, as in the template
        logo = self.image_handler.create_image(logo_url, 30 * mm, 30 * mm) # Increased size

        company_name = data.get('company_name', 'BUSINESS NAME')
        company_address = data.get('company_address', 'STREET NAME<br/>CITY, STATE ZIP')
        company_phone = data.get('company_phone', 'CONTACT INFO')
        company_email = data.get('company_email', '') # Not explicitly in template for this section

        company_info_right = [
            Paragraph(company_name, self.style_manager.business_name_style),
            Paragraph(company_address, self.style_manager.header_info_style),
            Paragraph(company_phone, self.style_manager.header_info_style),
        ]
        if company_email:
            company_info_right.append(Paragraph(company_email, self.style_manager.header_info_style))

        # Create a table for the top section
        # Column widths adjusted to give more space to the left for "INVOICE" title
        header_table_data = [
            [invoice_title, logo or ""],
            [Spacer(1, 1), Paragraph("", self.style_manager.normal)], # Spacer row
            [invoice_meta_left, company_info_right]
        ]

        header_table = Table(
            header_table_data,
            colWidths=[100 * mm, 70 * mm], # Adjusted column widths
            rowHeights=[None, 5*mm, None] # Adjust row heights for better spacing
        )
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (0, 0), "TOP"), # Align INVOICE title to top-left
            ("VALIGN", (1, 0), (1, 0), "TOP"), # Align logo to top-right
            ("ALIGN", (1, 0), (1, 0), "RIGHT"), # Align logo to right
            ("VALIGN", (0, 2), (0, 2), "TOP"), # Align invoice meta left to top
            ("VALIGN", (1, 2), (1, 2), "TOP"), # Align company info right to top
            ("ALIGN", (1, 2), (1, 2), "RIGHT"), # Align company info right to right
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 12)) # Add some space after the header

        return elements
    
    # The _format_company_info method is no longer needed as its logic is integrated
    # directly into _create_header_section. I will remove it.
    
    def _create_billing_section(self, data: Dict[str, Any]) -> List[Flowable]:
        """Create billing information section."""
        elements: List[Flowable] = []

        client_name = data.get('client_name', 'CLIENT NAME HERE')
        client_address = data.get('client_address', 'STREET NAME<br/>CITY, STATE ZIP')
        client_email = data.get('client_email', 'CONTACT INFO') # Using email for contact info as per template

        bill_to_text = (
            f"<b>ISSUED TO:</b><br/>"
            f"{client_name}<br/>"
            f"{client_address}<br/>"
            f"{client_email}"
        )
        elements.append(Paragraph(bill_to_text, self.style_manager.normal))
        elements.append(Spacer(1, 12)) # Add some space after the billing section

        return elements
    
    # The _create_bill_to_paragraph and _create_invoice_metadata methods are no longer needed
    # as their logic is integrated directly into _create_billing_section and _create_header_section.
    # I will remove them.
    
    def _create_items_table(self, data: Dict[str, Any]) -> List[Flowable]:
        """Create items table and totals section."""
        elements: List[Flowable] = []
        items = data.get("items", [])
        tax_rate = float(data.get("tax_rate", 0) or 0)
        currency = data.get("currency", DEFAULT_CURRENCY)
        
        # Calculate totals
        subtotal, tax_amount, grand_total = self.calculator.calculate_totals(items, tax_rate)
        
        # Create table data for items
        table_data: List[List[Any]] = [
            [
                Paragraph("DESCRIPTION", self.style_manager.small_bold),
                Paragraph("QTY", self.style_manager.small_bold),
                Paragraph("TOTAL", self.style_manager.small_bold)
            ]
        ]
        
        # Add item rows
        for item in items:
            item_total = item.get("total", item.get("quantity", 0) * item.get("unit_price", 0))
            table_data.append([
                Paragraph(item.get("name", "") or item.get("description", ""), self.style_manager.normal),
                Paragraph(str(item.get("quantity", 0)), self.style_manager.normal),
                Paragraph(self.currency_formatter.format_money(item_total, currency), self.style_manager.normal)
            ])
        
        items_table = Table(
            table_data, 
            colWidths=[110 * mm, 30 * mm, 30 * mm], # Adjusted column widths for 3 columns
            repeatRows=1 # Repeat header row on new pages
        )
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"), # QTY and TOTAL columns centered
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d0d0")),
            ("BOTTOMPADDING", (0,0), (-1,0), 12),
            ("TOPPADDING", (0,0), (-1,0), 12),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 12))

        # Add the "TOTAL" row as a separate table or paragraph below the items table
        total_row_data = [
            [Paragraph("TOTAL", self.style_manager.small_bold), Paragraph(self.currency_formatter.format_money(subtotal, currency), self.style_manager.small_bold)]
        ]
        total_row_table = Table(
            total_row_data,
            colWidths=[140 * mm, 30 * mm], # Adjusted to align with the right side of the items table
        )
        total_row_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("LINEBELOW", (0,0), (-1,-1), 1, colors.black), # Line below the total
        ]))
        elements.append(total_row_table)
        elements.append(Spacer(1, 12))

        # Add summary totals (TOTAL AMOUNT, TAX, AMOUNT DUE)
        summary_table_data = [
            [Paragraph("TOTAL AMOUNT", self.style_manager.normal), Paragraph(self.currency_formatter.format_money(subtotal, currency), self.style_manager.normal)],
            [Paragraph(f"TAX ({tax_rate*100:.0f}%)", self.style_manager.normal), Paragraph(self.currency_formatter.format_money(tax_amount, currency), self.style_manager.normal)],
            [Paragraph("<b>AMOUNT DUE</b>", self.style_manager.small_bold), Paragraph(f"<b>{self.currency_formatter.format_money(grand_total, currency)}</b>", self.style_manager.small_bold)]
        ]
        summary_table = Table(
            summary_table_data,
            colWidths=[140 * mm, 30 * mm], # Adjusted to align with the right side
        )
        summary_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 12))

        return elements
    
    def _create_notes_section(self, data: Dict[str, Any]) -> List[Flowable]:
        """Create notes, terms, payment information, and prompt payment message section."""
        elements = []
        
        # Add notes if present
        if data.get("notes"):
            elements.append(Spacer(1, 12))
            elements.append(Paragraph("<b>Notes</b>", self.style_manager.small_bold))
            elements.append(Paragraph(data["notes"], self.style_manager.normal))
        
        # Add terms if present
        if data.get("terms"):
            elements.append(Spacer(1, 6))
            elements.append(Paragraph("<b>Terms</b>", self.style_manager.small_bold))
            elements.append(Paragraph(data["terms"], self.style_manager.normal))

        # Add payment information and prompt payment message
        elements.append(Spacer(1, 24)) # Add significant space before footer

        payment_info_left = [
            Paragraph("PAYMENT INFORMATION:", self.style_manager.payment_info_title_style),
        ]
        if data.get("payment_info_checks"):
            payment_info_left.append(Paragraph(f"CHECKS MADE OUT TO {data['payment_info_checks']}", self.style_manager.payment_info_detail_style))
        if data.get("payment_info_paypal"):
            payment_info_left.append(Paragraph(f"PAYPAL: {data['payment_info_paypal']}", self.style_manager.payment_info_detail_style))
        if data.get("payment_info_venmo"):
            payment_info_left.append(Paragraph(f"VENMO: {data['payment_info_venmo']}", self.style_manager.payment_info_detail_style))
        if data.get("payment_info_cashapp"):
            payment_info_left.append(Paragraph(f"CASH APP: {data['payment_info_cashapp']}", self.style_manager.payment_info_detail_style))
        if data.get("payment_info_zelle"):
            payment_info_left.append(Paragraph(f"ZELLE: {data['payment_info_zelle']}", self.style_manager.payment_info_detail_style))
        
        prompt_payment_right = Paragraph(
            "PROMPT PAYMENTS ARE ALWAYS<br/>APPRECIATED!", 
            self.style_manager.prompt_payment_style
        )

        footer_table = Table(
            [[payment_info_left, prompt_payment_right]],
            colWidths=[100 * mm, 70 * mm] # Adjusted column widths
        )
        footer_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        elements.append(footer_table)
        
        return elements


# Utility functions
def cleanup_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Successfully deleted file: {path}")
        else:
            logger.warning(f"File not found for deletion: {path}")
    except OSError as e:
        logger.error(f"Error deleting file {path}: {e}")


def validate_invoice_data(data: Dict[str, Any] | InvoicePayload) -> None:
    # Convert Pydantic model to dict if needed
    if isinstance(data, InvoicePayload):
        data_dict = data.model_dump()
    else:
        data_dict = data
    
    required_fields = ["invoice_number"]
    missing_fields = [field for field in required_fields if not data_dict.get(field)]
    
    if missing_fields:
        raise HTTPException(
            status_code=400, 
            detail=f"Missing required fields: {', '.join(missing_fields)}"
        )


# API Endpoints
@router.post("/invoice_generator/", response_model=None)
async def create_invoice(
    background_tasks: BackgroundTasks,
    payload: InvoicePayload = Body(...), 
) -> FileResponse:
    try:
        # Validate input data
        validate_invoice_data(payload)
        
        invoice_id = payload.invoice_number
        
        # Generate PDF
        generator = InvoicePDFGenerator()
        pdf_path = generator.generate_pdf(invoice_id, payload)
        
        # Schedule file cleanup
        if background_tasks:
            background_tasks.add_task(cleanup_file, pdf_path)
        
        logger.info(f"Successfully generated invoice PDF: {invoice_id}")
        
        return FileResponse(
            pdf_path, 
            media_type='application/pdf', 
            filename=f"{invoice_id}.pdf"
        )
        
    except InvoiceGenerationError as e:
        logger.error(f"Invoice generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in invoice generation: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"An unexpected error occurred: {str(e)}"
        )


# Legacy function for backward compatibility
def generate_invoice_pdf(invoice_id: str, data: Dict[str, Any]) -> str:
    generator = InvoicePDFGenerator()
    return generator.generate_pdf(invoice_id, data)
