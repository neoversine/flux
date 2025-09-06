# app/invoice.py
import os
import logging
from io import BytesIO
from typing import Dict, Any, List, Optional, Tuple, Union
from decimal import Decimal, ROUND_HALF_UP

import requests
from fastapi import APIRouter, Body, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as ImageFlowable, Flowable
)
from pdf2image import convert_from_path, exceptions
from PIL import Image as PILImage, ImageDraw, ImageFont

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


router = APIRouter()

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "generated_pdfs")
IMAGE_DIR = os.path.join(BASE_DIR, "generated_images") # New directory for images
DEFAULT_TIMEOUT = 6
DEFAULT_CURRENCY = "₹"

class ImageHandler:
    """Handles image fetching and creation for ReportLab."""
    def create_image(self, url: Optional[str], width: Optional[float] = None, height: Optional[float] = None) -> Optional[ImageFlowable]:
        if not url:
            return None
        try:
            response = requests.get(url, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            img_data = BytesIO(response.content)
            img = ImageFlowable(img_data)
            if width:
                img.drawWidth = width
            if height:
                img.drawHeight = height
            return img
        except requests.exceptions.RequestException as e:
            logger.warning(f"Could not fetch image from {url}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error creating image from {url}: {e}")
            return None

class CurrencyFormatter:
    """Handles currency formatting."""
    def format_money(self, amount: Union[Decimal, float, str], currency_symbol: str = DEFAULT_CURRENCY) -> str:
        try:
            amount_decimal = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return f"{amount_decimal:,.2f} INR"
        except Exception as e:
            logger.error(f"Error formatting currency amount {amount}: {e}")
            return f"{amount} INR"

# Ensure directories exist
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True) # Ensure image directory exists


class InvoiceGenerationError(Exception):
    """Custom exception for invoice generation errors."""
    pass


# Pydantic Models
class InvoiceItem(BaseModel):
    """Model for invoice line items."""
    name: Optional[str]
    description: Optional[str]
    quantity: float
    unit_price: float
    total: Optional[float]


class InvoiceDetails(BaseModel):
    invoice_no: str
    invoice_date: str
    payment_due_date: str
    payment_mode: str
    order_id: Optional[str] = None # Added order_id
    order_date: Optional[str] = None # Added order_date

class CompanyInformation(BaseModel):
    name: str
    address: str
    email: str
    mobile: str
    company_logo_url: Optional[str]
    brand_name: Optional[str]
    state: Optional[str] = None # Added state field

class ClientInformation(BaseModel):
    name: str
    address: str
    place_of_supply: Optional[str] = None # Added place_of_supply to ClientInformation model

class Item(BaseModel):
    description: str
    hsn_code: str
    qty: Union[int, float]
    unit_rate: Union[float, str]
    amount: float

class SummaryOfCharges(BaseModel):
    total: float
    cgst: Union[float, str]
    sgst: Union[float, str]
    balance_received: Union[float, str]
    balance_due: Union[float, str]
    grand_total: float

class AdditionalInformation(BaseModel):
    total_amount_in_words: str
    terms_and_conditions: List[str]
    authorised_signatory: str
    authorised_signatory_image_url: Optional[str] = None # Added signatory image URL

class InvoicePayload(BaseModel):
    invoice_details: InvoiceDetails
    company_information: CompanyInformation
    client_information: ClientInformation
    items: List[Item]
    summary_of_charges: SummaryOfCharges
    additional_information: AdditionalInformation

class InvoiceCalculator:
    """Handles invoice calculations with precision."""
    
    @staticmethod
    def calculate_totals(items: List[Dict[str, Any]], summary_of_charges: Dict[str, Any]) -> Decimal:
        # Use grand_total from summary_of_charges if available
        if summary_of_charges and summary_of_charges.get("grand_total") is not None:
            grand_total = Decimal(str(summary_of_charges["grand_total"]))
        else:
            subtotal = Decimal('0')
            for item in items:
                # Calculate item total if not provided
                item_total = item.get("amount") # Use 'amount' from new payload
                if item_total is None:
                    # Fallback if 'amount' is not directly provided
                    quantity = Decimal(str(item.get("qty", 0)))
                    unit_price = Decimal(str(item.get("unit_rate", 0)))
                    item_total = quantity * unit_price
                
                subtotal += Decimal(str(item_total))
            grand_total = subtotal
        
        # Round to 2 decimal places
        grand_total = grand_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        return grand_total


class InvoiceStyleManager:
    """Manages PDF styles and formatting."""
    
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._create_custom_styles()
    
    def _create_custom_styles(self):
        """Create custom paragraph styles."""
        # Register a Unicode font that supports the Rupee symbol
        # This path might vary, or the font might not be present.
        # User might need to provide a specific .ttf file or ensure it's installed.
        unicode_font_path = "C:\\Windows\\Fonts\\ARIALUNI.TTF" # Common path for Arial Unicode MS on Windows
        self.default_font = 'Helvetica' # Fallback

        if os.path.exists(unicode_font_path):
            try:
                pdfmetrics.registerFont(TTFont('CustomUnicodeFont', unicode_font_path))
                self.default_font = 'CustomUnicodeFont'
                logger.info(f"Registered custom Unicode font from {unicode_font_path}")
            except Exception as e:
                logger.warning(f"Could not register font from {unicode_font_path}: {e}, falling back to Helvetica.")
        else:
            logger.warning(f"Unicode font not found at {unicode_font_path}, falling back to Helvetica. Rupee symbol might not display correctly.")

        self.normal = self.styles["Normal"]
        self.normal.spaceAfter = 1 * mm
        self.normal.fontSize = 9
        self.normal.leading = 11
        self.normal.fontName = self.default_font

        self.small_normal = ParagraphStyle(
            "small_normal",
            parent=self.normal,
            fontSize=8,
            spaceAfter=0.5 * mm,
            leading=10,
            fontName=self.default_font
        )
        
        self.small_bold = ParagraphStyle(
            "small_bold", 
            parent=self.normal, 
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=1 * mm,
            leading=11
        )

        self.extra_small_bold = ParagraphStyle(
            "extra_small_bold",
            parent=self.normal,
            fontSize=7,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=9
        )
        self.extra_medium_bold = ParagraphStyle(
            "extra_medium_bold",
            parent=self.normal,
            fontSize=10,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            spaceRight=0, # Removed spaceRight to allow better centering
            leading=9
        )

        self.extra_small_normal = ParagraphStyle(
            "extra_small_normal",
            parent=self.normal,
            fontSize=7,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=9
        )
        self.extra_medium_normal = ParagraphStyle(
            "extra_medium_normal",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=9
        )
        
        self.right_small = ParagraphStyle(
            "right_small", 
            parent=self.normal, 
            alignment=2,  # Right alignment
            fontSize=10,
            leading=12,
            fontName=self.default_font
        )
        
        self.invoice_title_style = ParagraphStyle(
            "invoice_title_style",
            parent=self.styles["h1"],
            fontSize=10, # Smaller font size for "Tax Invoice"
            fontName=self.default_font,
            spaceAfter=3 * mm,
            leading=16,
            alignment=0,
            backColor=colors.HexColor("#e8e8e8"), # Gray background
            leftIndent=0, # Ensure no left indent
            rightIndent=0, # Ensure no right indent
            borderPadding=1*mm # Add some padding around the text
        )

        self.company_name_style = ParagraphStyle(
            "company_name_style",
            parent=self.normal,
            fontSize=12,
            fontName=self.default_font,
            spaceAfter=1 * mm,
            leading=11
        )

        self.company_name_large_bold_style = ParagraphStyle(
            "company_name_large_bold_style",
            parent=self.styles["h1"],
            fontSize=16,
            fontName=self.default_font,
            spaceAfter=0 * mm, # Reduced space after for better alignment
            leading=18,
            alignment=0 # Left alignment
        )

        self.company_info_label_style = ParagraphStyle( # New style for bold labels
            "company_info_label_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=11
        )

        self.company_info_value_style = ParagraphStyle( # New style for regular values
            "company_info_value_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=11
        )

        self.section_title_style = ParagraphStyle(
            "section_title_style",
            parent=self.normal,
            fontSize=10,
            fontName=self.default_font,
            spaceAfter=3 * mm,
            leading=12,
            backColor=colors.HexColor("#e8e8e8"),
        )

        self.client_info_style = ParagraphStyle(
            "client_info_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=11
        )

        self.table_header_style = ParagraphStyle(
            "table_header_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            alignment=1,
            spaceAfter=2 * mm,
            spaceBefore=2 * mm,
            leading=11
        )

        self.table_data_style = ParagraphStyle(
            "table_data_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=1 * mm,
            spaceBefore=1 * mm,
            leading=11
        )

        self.total_label_style = ParagraphStyle(
            "total_label_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            alignment=2,
            spaceAfter=1 * mm,
            leading=11
        )

        self.total_value_style = ParagraphStyle(
            "total_value_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            alignment=2,
            spaceAfter=1 * mm,
            leading=11
        )

        self.footer_text_style = ParagraphStyle(
            "footer_text_style",
            parent=self.normal,
            fontSize=8,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=10
        )

        self.authorised_signatory_style = ParagraphStyle(
            "authorised_signatory_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            alignment=2,
            spaceBefore=10 * mm,
            leading=11,
            rightIndent=10
        )


class InvoicePDFGenerator:
    """Generates PDF invoices using ReportLab."""
    
    def __init__(self):
        self.calculator = InvoiceCalculator()
        self.style_manager = InvoiceStyleManager()
        self.image_handler = ImageHandler()
        self.currency_formatter = CurrencyFormatter()
    
    def generate_pdf(self, invoice_id: str, data: Union[Dict[str, Any], InvoicePayload]) -> str:
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
            leftMargin=15 * mm, # Reduced left margin
            rightMargin=15 * mm, # Reduced right margin
            topMargin=15 * mm, # Reduced top margin
            bottomMargin=10 * mm # Reduced bottom margin
        )
        
        elements: List[Flowable] = []
        
        # Add document sections
        elements.extend(self._create_header_section(data, doc.width))
        elements.append(Spacer(1, 3 * mm)) # Reduced spacer
        elements.extend(self._create_billing_section(data, doc.width))
        elements.append(Spacer(1, 6 * mm)) # Reduced spacer
        elements.extend(self._create_items_table(data))
        elements.append(Spacer(1, 6 * mm)) # Reduced space after items table
        elements.extend(self._create_footer_section(data, doc.width)) # Pass doc.width to footer section
        
        doc.build(elements)
        return file_path
    
    def _convert_pdf_to_image(self, pdf_path: str, invoice_id: str, fmt: str = "jpg") -> str:
        """Converts the first page of a PDF to an image."""
        image_path = os.path.join(IMAGE_DIR, f"{invoice_id}.{fmt}")
        try:
            # Convert PDF to a list of images (one image per page)
            images = convert_from_path(pdf_path, first_page=1, last_page=1)
            if images:
                # Save the first page as an image
                images[0].save(image_path, "JPEG")
                logger.info(f"Successfully converted PDF to image: {image_path}")
                return image_path
            else:
                raise InvoiceGenerationError("No images found in PDF for conversion.")
        except exceptions.PopplerNotInstalledError:
            logger.error("Poppler is not installed or not in PATH. Please install Poppler to enable PDF to image conversion.")
            raise InvoiceGenerationError("PDF to image conversion failed: Poppler is not installed. Please install Poppler and ensure it's in your system's PATH.")
        except Exception as e:
            logger.error(f"Failed to convert PDF to image from {pdf_path} for invoice {invoice_id}: {e}")
            raise InvoiceGenerationError(f"Image conversion failed: {str(e)}")

    def _create_header_section(self, data: Dict[str, Any], doc_width: float) -> List[Flowable]:
        """Create header section with 'ORIGINAL FOR RECIPIENT', 'Tax Invoice' title, company info, and invoice metadata."""
        elements: List[Flowable] = []

        company_info = data.get('company_information', {})
        invoice_details = data.get('invoice_details', {})

        company_name = company_info.get('name', '')
        company_address = company_info.get('address', '')
        company_email = company_info.get('email', '')
        company_mobile = company_info.get('mobile', '')
        company_logo_url = company_info.get('company_logo_url', '')
        company_state = company_info.get('state', '') # Retrieve state from company_info

        invoice_no = invoice_details.get('invoice_no', '')
        invoice_date = invoice_details.get('invoice_date', '')
        payment_due_date = invoice_details.get('payment_due_date', '')
        payment_mode = invoice_details.get('payment_mode', '')
        
        # Use brand_name if provided, otherwise default to company_name
        top_company_display_name = company_info.get('brand_name', company_name)

        # Top header with dynamic company name, "ORIGINAL FOR RECIPIENT" and Logo
        finno_farms_text = Paragraph(top_company_display_name, self.style_manager.company_name_large_bold_style)
        original_for_recipient_text = Paragraph("ORIGINAL FOR RECIPIENT", self.style_manager.extra_medium_bold)
        logo_image = self.image_handler.create_image(company_logo_url, width=40*mm, height=15*mm)

        top_header_table = Table(
            [[
                finno_farms_text,
                original_for_recipient_text,
                logo_image if logo_image else ""
            ]],
            colWidths=[doc_width / 3, doc_width / 3, doc_width / 3], # Divide width into three equal parts
            style=TableStyle([
                ('ALIGN', (0,0), (0,-1), 'LEFT'), # Company name left aligned
                ('ALIGN', (1,0), (1,-1), 'CENTER'), # "ORIGINAL FOR RECIPIENT" centered
                ('ALIGN', (2,0), (2,-1), 'RIGHT'), # Logo right aligned
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ])
        )
        elements.append(top_header_table)
        elements.append(Spacer(1, 3 * mm)) # Reduced spacer

        # "Tax Invoice" title
        elements.append(Paragraph("Tax Invoice", self.style_manager.invoice_title_style))
        elements.append(Spacer(1, 3 * mm)) # Reduced spacer

        # Company Header (Grey bar with company name)
        elements.append(Table(
            [[Paragraph(company_name, self.style_manager.company_name_style)]],
            colWidths=[doc_width], # Use doc_width for full width
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#e0e0e0")),
                ('LEFTPADDING', (0,0), (-1,-1), 5*mm),
                ('RIGHTPADDING', (0,0), (-1,-1), 5*mm),
                ('TOPPADDING', (0,0), (-1,-1), 2*mm),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
            ])
        ))
        elements.append(Spacer(1, 3 * mm)) # Reduced spacer

        # Company Details and Invoice Metadata Table
        # This table will have 2 columns: Label, Value
        header_details_table_data = [
            [
                Paragraph("Address:", self.style_manager.company_info_label_style),
                Paragraph(company_address.replace(', ', '<br/>'), self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("State:", self.style_manager.company_info_label_style),
                Paragraph(company_state, self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("Email ID:", self.style_manager.company_info_label_style),
                Paragraph(company_email, self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("Invoice No:", self.style_manager.company_info_label_style),
                Paragraph(invoice_no, self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("Invoice Date:", self.style_manager.company_info_label_style),
                Paragraph(invoice_date, self.style_manager.company_info_value_style)
            ]
        ]

        header_details_table = Table(
            header_details_table_data,
            colWidths=[30 * mm, 140 * mm], # Adjusted column widths for better alignment
        )
        header_details_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"), # Labels left aligned
            ("ALIGN", (1, 0), (1, -1), "LEFT"), # Values left aligned
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        elements.append(header_details_table)
        elements.append(Spacer(1, 2 * mm)) # Add some space after the header

        return elements
    
    def _create_billing_section(self, data: Dict[str, Any], doc_width: float) -> List[Flowable]:
        """Create customer details section."""
        elements: List[Flowable] = []

        # Customer Details section title with grey background
        elements.append(Table(
            [[Paragraph("Customer Details", self.style_manager.section_title_style)]],
            colWidths=[doc_width],
            style=TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#e8e8e8")),
                ('LEFTPADDING', (0,0), (-1,-1), 5*mm),
                ('RIGHTPADDING', (0,0), (-1,-1), 5*mm),
                ('TOPPADDING', (0,0), (-1,-1), 2*mm),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2*mm),
            ])
        ))
        elements.append(Spacer(1, 3 * mm))

        client_information = data.get('client_information', {})
        client_name = client_information.get('name', '')
        client_address = client_information.get('address', '')
        place_of_supply = client_information.get('place_of_supply', '')

        invoice_details = data.get('invoice_details', {})
        order_id = invoice_details.get('order_id', '')
        order_date = invoice_details.get('order_date', '')

        client_details_table_data = [
            [Paragraph("<b>Name:</b>", self.style_manager.client_info_style), Paragraph(client_name, self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Delivery Address:</b>", self.style_manager.client_info_style), Paragraph(client_address.replace(', ', '<br/>'), self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Place of Supply:</b>", self.style_manager.client_info_style), Paragraph(place_of_supply, self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Order ID:</b>", self.style_manager.client_info_style), Paragraph(order_id, self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Order Date:</b>", self.style_manager.client_info_style), Paragraph(order_date, self.style_manager.client_info_style)],
        ]

        client_details_table = Table(
            client_details_table_data,
            colWidths=[30*mm, 140*mm], # Adjusted column widths for 2 columns
        )
        client_details_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))
        elements.append(client_details_table)
        elements.append(Spacer(1, 2 * mm))

        return elements
    
    def _create_items_table(self, data: Dict[str, Any]) -> List[Flowable]:
        """Create items table and totals section."""
        elements: List[Flowable] = []
        items = data.get("items", [])
        summary_of_charges = data.get("summary_of_charges", {})
        currency = data.get("currency", DEFAULT_CURRENCY)
        
        # Calculate grand total
        grand_total = self.calculator.calculate_totals(items, summary_of_charges)
        

        # Create table data for items
        table_data: List[List[Any]] = [
            [
                Paragraph("Sr.No", self.style_manager.table_header_style),
                Paragraph("Items", self.style_manager.table_header_style),
                Paragraph("HSN/SAC", self.style_manager.table_header_style), # Added HSN/SAC header
                Paragraph("Qty", self.style_manager.table_header_style),
                Paragraph("Unit Price", self.style_manager.table_header_style),
                Paragraph("Amount", self.style_manager.table_header_style)
            ]
        ]
        
        # Add item rows
        for i, item in enumerate(items):
            quantity = Decimal(str(item.get("qty", 0)))
            unit_price = Decimal(str(item.get("unit_rate", 0)))
            amount = Decimal(str(item.get("amount", 0))) # Use 'amount' from new payload
            hsn_code = item.get("hsn_code", "") # Get HSN code

            table_data.append([
                Paragraph(str(i + 1), self.style_manager.table_data_style),
                Paragraph(item.get("description", ""), self.style_manager.table_data_style),
                Paragraph(hsn_code, self.style_manager.table_data_style), # Added HSN code
                Paragraph(str(quantity), self.style_manager.table_data_style),
                Paragraph(self.currency_formatter.format_money(unit_price, currency), self.style_manager.table_data_style),
                Paragraph(self.currency_formatter.format_money(amount, currency), self.style_manager.table_data_style)
            ])
        
        items_table = Table(
            table_data, 
            colWidths=[10 * mm, 50 * mm, 20 * mm, 20 * mm, 35 * mm, 35 * mm], # Adjusted column widths for new HSN/SAC column
            repeatRows=1 # Repeat header row on new pages
        )
        items_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("ALIGN", (0, 0), (1, -1), "LEFT"), # Sr.No and Particulars left aligned
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"), # Amounts right aligned
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d0d0")),
            ("BOTTOMPADDING", (0,0), (-1,0), 6),
            ("TOPPADDING", (0,0), (-1,0), 6),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 6 * mm))

        # Summary of Charges
        summary_table_data = []
        summary_total = Decimal(str(summary_of_charges.get("total", 0)))
        summary_cgst = Decimal(str(summary_of_charges.get("cgst", 0)))
        summary_sgst = Decimal(str(summary_of_charges.get("sgst", 0)))
        summary_balance_received = Decimal(str(summary_of_charges.get("balance_received", 0)))
        summary_balance_due = Decimal(str(summary_of_charges.get("balance_due", 0)))
        summary_grand_total = Decimal(str(summary_of_charges.get("grand_total", 0)))

        summary_table_data.append([
            Paragraph("Total Amount (Excl. Tax)", self.style_manager.total_label_style),
            Paragraph(self.currency_formatter.format_money(summary_total, currency), self.style_manager.total_value_style)
        ])
        summary_table_data.append([
            Paragraph("CGST", self.style_manager.total_label_style),
            Paragraph(self.currency_formatter.format_money(summary_cgst, currency), self.style_manager.total_value_style)
        ])
        summary_table_data.append([
            Paragraph("SGST", self.style_manager.total_label_style),
            Paragraph(self.currency_formatter.format_money(summary_sgst, currency), self.style_manager.total_value_style)
        ])
        summary_table_data.append([
            Paragraph("Balance Received", self.style_manager.total_label_style),
            Paragraph(self.currency_formatter.format_money(summary_balance_received, currency), self.style_manager.total_value_style)
        ])
        summary_table_data.append([
            Paragraph("Balance Due", self.style_manager.total_label_style),
            Paragraph(self.currency_formatter.format_money(summary_balance_due, currency), self.style_manager.total_value_style)
        ])
        summary_table_data.append([
            Paragraph("Grand Total", self.style_manager.total_label_style),
            Paragraph(self.currency_formatter.format_money(summary_grand_total, currency), self.style_manager.total_value_style)
        ])

        summary_table = Table(
            summary_table_data,
            colWidths=[140 * mm, 30 * mm],
        )
        summary_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("LINEBELOW", (0,-1), (-1,-1), 1, colors.black), # Line below the grand total
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 12 * mm))

        return elements
    
    def _create_footer_section(self, data: Dict[str, Any], doc_width: float) -> List[Flowable]: # Added doc_width parameter
        """Create footer section with terms and authorised signatory."""
        elements = []
        
        additional_info = data.get("additional_information", {})
        terms_and_conditions = additional_info.get("terms_and_conditions", [])
        authorised_signatory = additional_info.get("authorised_signatory", '')
        authorised_signatory_image_url = additional_info.get("authorised_signatory_image_url", '')

        for term in terms_and_conditions:
            elements.append(Paragraph(term, self.style_manager.footer_text_style))
        elements.append(Spacer(1, 3 * mm)) # Add some space before the signature

        # Authorised Signatory section using a table for alignment
        signatory_elements: List[Flowable] = []
        
        # Add signatory image if URL is provided
        if authorised_signatory_image_url:
            signatory_image = self.image_handler.create_image(authorised_signatory_image_url, width=40*mm, height=15*mm)
            if signatory_image:
                signatory_elements.append(signatory_image)
                signatory_elements.append(Spacer(1, 1 * mm)) # Small space after image
        
        signatory_elements.append(Paragraph(authorised_signatory, self.style_manager.authorised_signatory_style))

        footer_table_data = [
            [
                Paragraph("For Eternal Limited (formerly known as Zomato Limited)", self.style_manager.small_bold),
                signatory_elements
            ]
        ]

        footer_table = Table(
            footer_table_data,
            colWidths=[doc_width / 2, doc_width / 2], # Use doc_width here
            style=TableStyle([
                ('ALIGN', (0,0), (0,-1), 'LEFT'), # Company name left aligned
                ('ALIGN', (1,0), (1,-1), 'RIGHT'), # Signatory elements right aligned
                ('VALIGN', (0,0), (-1,-1), 'BOTTOM'), # Align to bottom for signature line
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ])
        )
        elements.append(footer_table)
        
        return elements


# Utility functions
def cleanup_file(paths: Union[str, List[str]]) -> None:
    """Cleans up one or more files."""
    if isinstance(paths, str):
        paths = [paths]
    
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Successfully deleted file: {path}")
            else:
                logger.warning(f"File not found for deletion: {path}")
        except OSError as e:
            logger.error(f"Error deleting file {path}: {e}")


def validate_invoice_data(data: Union[Dict[str, Any], InvoicePayload]) -> None:
    # Convert Pydantic model to dict if needed
    if isinstance(data, InvoicePayload):
        data_dict = data.model_dump()
    else:
        data_dict = data
    
    # Access invoice_no from invoice_details
    invoice_details = data_dict.get("invoice_details", {})
    required_fields = ["invoice_no"]
    missing_fields = [field for field in required_fields if not invoice_details.get(field)]
    
    if missing_fields:
        raise HTTPException(
            status_code=400, 
            detail=f"Missing required fields in invoice_details: {', '.join(missing_fields)}"
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
        
        invoice_id = payload.invoice_details.invoice_no
        
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


# API Endpoints
@router.post("/invoice_image_generator/", response_model=None)
async def create_invoice_image(
    background_tasks: BackgroundTasks,
    payload: InvoicePayload = Body(...),
    image_format: str = "jpg" # Allow specifying image format
) -> FileResponse:
    try:
        validate_invoice_data(payload)
        
        invoice_id = payload.invoice_details.invoice_no
        
        generator = InvoicePDFGenerator()
        pdf_path = generator.generate_pdf(invoice_id, payload)
        image_path = generator._convert_pdf_to_image(pdf_path, invoice_id, image_format)
        
        # Schedule both PDF and image files for cleanup
        if background_tasks:
            background_tasks.add_task(cleanup_file, [pdf_path, image_path])
        
        logger.info(f"Successfully generated invoice image: {invoice_id}.{image_format}")
        
        return FileResponse(
            image_path,
            media_type=f'image/{image_format}',
            filename=f"{invoice_id}.{image_format}"
        )
        
    except InvoiceGenerationError as e:
        logger.error(f"Invoice image generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in invoice image generation: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )


# Legacy function for backward compatibility
def generate_invoice_image(payload: InvoicePayload, output_path: Optional[str] = None, image_format: str = "jpg") -> str:
    """
    Generates an invoice image by first creating a PDF and then converting it to an image.
    This ensures consistency with the PDF generation logic.

    Args:
        payload (InvoicePayload): The invoice data.
        output_path (str, optional): The desired output path for the image. If None, a default path will be used.
        image_format (str): The format of the output image (e.g., "jpg", "png").

    Returns:
        str: Path to the generated image file.
    """
    try:
        validate_invoice_data(payload)

        invoice_id = payload.invoice_details.invoice_no

        generator = InvoicePDFGenerator()
        pdf_path = generator.generate_pdf(invoice_id, payload)

        # If output_path is not provided, use the default image directory
        if output_path is None:
            image_path = os.path.join(IMAGE_DIR, f"{invoice_id}.{image_format}")
        else:
            image_path = output_path

        # Convert PDF to image
        final_image_path = generator._convert_pdf_to_image(pdf_path, invoice_id, image_format)

        # Rename the image if output_path was specified and is different from the default
        if output_path is not None and final_image_path != output_path:
            os.rename(final_image_path, output_path)
            final_image_path = output_path

        # Clean up the generated PDF
        cleanup_file(pdf_path)

        logger.info(f"Successfully generated invoice image: {final_image_path}")
        return final_image_path

    except InvoiceGenerationError as e:
        logger.error(f"Invoice image generation error: {e}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in invoice image generation: {e}")
        raise e
