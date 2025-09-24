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

class NumberToWordsConverter:
    """Converts numerical amounts to words."""
    
    def __init__(self):
        self.units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
        self.teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        self.tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        self.thousands = ["", "Thousand", "Million", "Billion", "Trillion"] # Extend as needed

    def _convert_less_than_thousand(self, num: int) -> str:
        if num == 0:
            return ""
        if num < 10:
            return self.units[num]
        if num < 20:
            return self.teens[num - 10]
        if num < 100:
            return self.tens[num // 10] + (" " + self.units[num % 10] if (num % 10 != 0) else "")
        return self.units[num // 100] + " Hundred" + (" " + self._convert_less_than_thousand(num % 100) if (num % 100 != 0) else "")

    def convert_to_words(self, amount: Decimal) -> str:
        if amount == 0:
            return "Zero Rupees Only"

        # Separate integer and decimal parts
        integer_part = int(amount.to_integral_value(rounding=ROUND_HALF_UP))
        decimal_part = int((amount - integer_part) * 100)

        words = []
        if integer_part > 0:
            i = 0
            while integer_part > 0:
                chunk = integer_part % 1000
                if chunk != 0:
                    words.append(self._convert_less_than_thousand(chunk) + " " + self.thousands[i])
                integer_part //= 1000
                i += 1
            words.reverse()
            
        result = " ".join(words).strip()
        
        if result:
            result += " Rupees"
        
        if decimal_part > 0:
            if result:
                result += " and "
            result += self._convert_less_than_thousand(decimal_part) + " Paisa"
        
        if result:
            result += " Only"
        
        return result.strip()

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
    gstin: Optional[str] = None # Added GSTIN field
class ClientInformation(BaseModel):
    name: str
    address: str
    place_of_supply: Optional[str] = None # Added place_of_supply to ClientInformation model

class Item(BaseModel):
    description: str
    hsn_code: str
    qty: Union[int, float]
    unit_rate: Union[float, str]
    tax_percentage: Union[float, str] = Field(default=0.0) # New field for tax percentage
    tax_amount: Union[float, str] = Field(default=0.0) # New field for tax amount
    total_amt_inc_gst: Union[float, str] # Renamed 'amount' to 'total_amt_inc_gst'

class SummaryOfCharges(BaseModel):
    net_sales: Union[float, str] = Field(default=0.0) # New field for Net Sales
    cgst: Union[float, str]
    sgst: Union[float, str]
    misc: Union[float, str] = Field(default=0.0) # New field for Misc
    total: Union[float, str] # This will be Net Sales + CGST + SGST + Misc
    balance_received: Union[float, str]
    balance_due: Union[float, str]
    grand_total: Union[float, str]

class AdditionalInformation(BaseModel):
    total_amount_in_words: Optional[str] = None
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
    def calculate_totals(summary_of_charges: Dict[str, Any]) -> Decimal:
        # Use total from summary_of_charges
        total = Decimal(str(summary_of_charges.get("total", 0)))
        
        # Round to 2 decimal places
        total = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        
        return total


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

        self.description_title_style = ParagraphStyle(
            "description_title_style",
            parent=self.normal,
            fontSize=10,
            fontName=self.default_font,
            spaceAfter=1 * mm,
            leading=12,
            textColor=colors.HexColor("#555555")
        )

        self.description_text_style = ParagraphStyle(
            "description_text_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=3 * mm,
            leading=11,
            backColor=colors.HexColor("#f0f0f0"),
            borderPadding=0 # Removed borderPadding
        )

        self.order_amount_title_style = ParagraphStyle(
            "order_amount_title_style",
            parent=self.normal,
            fontSize=10,
            fontName=self.default_font,
            spaceAfter=1 * mm,
            leading=12,
            textColor=colors.HexColor("#555555")
        )

        self.order_amount_text_style = ParagraphStyle(
            "order_amount_text_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=3 * mm,
            leading=11,
            backColor=colors.HexColor("#f0f0f0"),
            borderPadding=0 # Removed borderPadding
        )

        self.terms_title_style = ParagraphStyle(
            "terms_title_style",
            parent=self.normal,
            fontSize=10,
            fontName=self.default_font,
            spaceAfter=1 * mm,
            leading=12,
            textColor=colors.HexColor("#555555")
        )

        self.terms_text_style = ParagraphStyle(
            "terms_text_style",
            parent=self.normal,
            fontSize=9,
            fontName=self.default_font,
            spaceAfter=0.5 * mm,
            leading=11,
            backColor=colors.HexColor("#f0f0f0"),
            borderPadding=0 # Removed borderPadding
        )


class InvoicePDFGenerator:
    """Generates PDF invoices using ReportLab."""
    
    def __init__(self):
        self.calculator = InvoiceCalculator()
        self.style_manager = InvoiceStyleManager()
        self.image_handler = ImageHandler()
        self.currency_formatter = CurrencyFormatter()
        self.number_to_words_converter = NumberToWordsConverter()
    
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
        elements.extend(self._create_items_table(data, doc.width))
        elements.append(Spacer(1, 6 * mm)) # Reduced space after items table
        
        # Create a two-column layout for description/terms and summary
        left_column_content = self._create_description_terms_section(data, doc.width * 0.6) # Allocate 60% width for left column
        right_column_content = self._create_summary_table(data, doc.width * 0.4) # Allocate 40% width for right column

        two_column_table = Table(
            [[left_column_content, right_column_content]],
            colWidths=[doc.width * 0.6, doc.width * 0.4],
            style=TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ])
        )
        elements.append(two_column_table)
        elements.append(Spacer(1, 6 * mm)) # Spacer after new section

        elements.extend(self._create_footer_section(data, doc.width)) # Pass doc.width to footer section
        
        doc.build(elements)
        return file_path
    
    def _create_description_terms_section(self, data: Dict[str, Any], column_width: float) -> List[Flowable]:
        """Create the Description, Order Amount in Words, and Terms and Conditions sections."""
        elements: List[Flowable] = []
        additional_info = data.get("additional_information", {})
        summary_of_charges = data.get("summary_of_charges", {})
        
        description_text = "Thanks for doing business with us!" # Hardcoded as per image
        terms_and_conditions = additional_info.get("terms_and_conditions", [])

        # Get total amount and convert to words
        total_amount = Decimal(str(summary_of_charges.get("total", 0)))
        dynamic_order_amount_in_words = self.number_to_words_converter.convert_to_words(total_amount)
        
        # Use provided total_amount_in_words if available, otherwise use dynamic one
        order_amount_in_words = additional_info.get("total_amount_in_words", dynamic_order_amount_in_words)

        # DESCRIPTION
        elements.append(Paragraph("DESCRIPTION", self.style_manager.description_title_style))
        elements.append(Paragraph(description_text, self.style_manager.description_text_style))
        elements.append(Spacer(1, 3 * mm))

        # ORDER AMOUNT IN WORDS
        elements.append(Paragraph("ORDER AMOUNT IN WORDS", self.style_manager.order_amount_title_style))
        elements.append(Paragraph(order_amount_in_words, self.style_manager.order_amount_text_style))
        elements.append(Spacer(1, 3 * mm))

        # TERMS AND CONDITIONS
        elements.append(Paragraph("TERMS AND CONDITIONS", self.style_manager.terms_title_style))
        for term in terms_and_conditions:
            elements.append(Paragraph(term, self.style_manager.terms_text_style))
        elements.append(Spacer(1, 3 * mm))

        return elements

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
        company_gstin = company_info.get('gstin', '') # Retrieve GSTIN from company_info
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
        # Left column content for company details
        left_col_data = [
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
                Paragraph("GSTIN:", self.style_manager.company_info_label_style),
                Paragraph(company_gstin, self.style_manager.company_info_value_style)
            ],
            ]
        
        left_col_table = Table(left_col_data, colWidths=[30 * mm, 60 * mm])
        left_col_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (1, -1), "LEFT"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

        # Right column content for invoice metadata
        right_col_data = [
            [
                Paragraph("Invoice No:", self.style_manager.company_info_label_style),
                Paragraph(invoice_no, self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("Invoice Date:", self.style_manager.company_info_label_style),
                Paragraph(invoice_date, self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("Phone No:", self.style_manager.company_info_label_style),
                Paragraph(company_mobile, self.style_manager.company_info_value_style)
            ],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [
                Paragraph("Email:", self.style_manager.company_info_label_style),
                Paragraph(company_email, self.style_manager.company_info_value_style)
            ]
        ]
        right_col_table = Table(right_col_data, colWidths=[30 * mm, 60 * mm])
        right_col_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("ALIGN", (1, 0), (1, -1), "LEFT"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

        # Combine into a two-column table
        header_details_two_col_table = Table(
            [[left_col_table, right_col_table]],
            colWidths=[doc_width / 2, doc_width / 2],
            style=TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ])
        )
        elements.append(header_details_two_col_table)
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

        # Left column content for client details
        left_col_data = [
            [Paragraph("<b>Name:</b>", self.style_manager.client_info_style), Paragraph(client_name, self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Delivery Address:</b>", self.style_manager.client_info_style), Paragraph(client_address.replace(', ', '<br/>'), self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Place of Supply:</b>", self.style_manager.client_info_style), Paragraph(place_of_supply, self.style_manager.client_info_style)],
        ]
        left_col_table = Table(left_col_data, colWidths=[30 * mm, 60 * mm])
        left_col_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

        # Right column content for order details
        right_col_data = [
            [Paragraph("<b>Order ID:</b>", self.style_manager.client_info_style), Paragraph(order_id, self.style_manager.client_info_style)],
            [Spacer(1, 1 * mm), Spacer(1, 1 * mm)], # Add line gap
            [Paragraph("<b>Order Date:</b>", self.style_manager.client_info_style), Paragraph(order_date, self.style_manager.client_info_style)],
        ]
        right_col_table = Table(right_col_data, colWidths=[30 * mm, 60 * mm])
        right_col_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ]))

        # Combine into a two-column table
        client_details_two_col_table = Table(
            [[left_col_table, right_col_table]],
            colWidths=[doc_width / 2, doc_width / 2],
            style=TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
                ('TOPPADDING', (0,0), (-1,-1), 0),
                ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ])
        )
        elements.append(client_details_two_col_table)
        elements.append(Spacer(1, 2 * mm))

        return elements
    
    def _create_items_table(self, data: Dict[str, Any], doc_width: float) -> List[Flowable]:
        """Create items table and totals section."""
        elements: List[Flowable] = []
        items = data.get("items", [])
        summary_of_charges = data.get("summary_of_charges", {})
        currency = data.get("currency", DEFAULT_CURRENCY)
        
        # Calculate total
        total = self.calculator.calculate_totals(summary_of_charges)
        
        # Ensure sub_total is calculated if not provided in payload
        if summary_of_charges.get("sub_total") is None:
            subtotal_from_items = Decimal('0')
            for item in items:
                quantity = Decimal(str(item.get("qty", 0)))
                unit_price = Decimal(str(item.get("unit_rate", 0)))
                total_amt_inc_gst = Decimal(str(item.get("total_amt_inc_gst", 0)))
                
                # If total_amt_inc_gst is provided, use it, otherwise calculate
                if total_amt_inc_gst:
                    subtotal_from_items += total_amt_inc_gst
                else:
                    subtotal_from_items += quantity * unit_price
            summary_of_charges["sub_total"] = subtotal_from_items.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Update the grand_total in summary_of_charges to be the calculated total
        summary_of_charges["total"] = total

        # Create table data for items
        table_data: List[List[Any]] = [
            [
                Paragraph("Sr.No", self.style_manager.table_header_style),
                Paragraph("Item Name", self.style_manager.table_header_style),
                Paragraph("HSN Code", self.style_manager.table_header_style),
                Paragraph("Qty", self.style_manager.table_header_style),
                Paragraph("Price/Unit", self.style_manager.table_header_style),
                Paragraph("Tax%", self.style_manager.table_header_style),
                Paragraph("Tax Amount", self.style_manager.table_header_style),
                Paragraph("Total Amt. Inc GST (INR)", self.style_manager.table_header_style)
            ]
        ]
        
        # Add item rows
        for i, item in enumerate(items):
            quantity = Decimal(str(item.get("qty", 0)))
            unit_price = Decimal(str(item.get("unit_rate", 0)))
            tax_percentage = Decimal(str(item.get("tax_percentage", 0)))
            tax_amount = Decimal(str(item.get("tax_amount", 0)))
            total_amt_inc_gst = Decimal(str(item.get("total_amt_inc_gst", 0)))
            hsn_code = item.get("hsn_code", "")

            table_data.append([
                Paragraph(str(i + 1), self.style_manager.table_data_style),
                Paragraph(item.get("description", ""), self.style_manager.table_data_style),
                Paragraph(hsn_code, self.style_manager.table_data_style),
                Paragraph(str(quantity), self.style_manager.table_data_style),
                Paragraph(self.currency_formatter.format_money(unit_price, currency), self.style_manager.table_data_style),
                Paragraph(f"{tax_percentage:,.2f}%", self.style_manager.table_data_style),
                Paragraph(self.currency_formatter.format_money(tax_amount, currency), self.style_manager.table_data_style),
                Paragraph(self.currency_formatter.format_money(total_amt_inc_gst, currency), self.style_manager.table_data_style)
            ])
        
        items_table = Table(
            table_data, 
            colWidths=[8 * mm, 35 * mm, 18 * mm, 12 * mm, 25 * mm, 15 * mm, 25 * mm, 32 * mm], # Adjusted column widths for new columns
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
        return elements

    def _create_summary_table(self, data: Dict[str, Any], doc_width: float) -> List[Flowable]:
        """Create the summary of charges table."""
        summary_elements: List[Flowable] = []
        summary_of_charges = data.get("summary_of_charges", {})
        currency = data.get("currency", DEFAULT_CURRENCY)

        summary_net_sales = Decimal(str(summary_of_charges.get("net_sales", 0)))
        summary_cgst = Decimal(str(summary_of_charges.get("cgst", 0)))
        summary_sgst = Decimal(str(summary_of_charges.get("sgst", 0)))
        summary_misc = Decimal(str(summary_of_charges.get("misc", 0)))
        summary_total_amount = Decimal(str(summary_of_charges.get("total", 0))) # Using 'total' for 'Total Amount'
        summary_balance_received = Decimal(str(summary_of_charges.get("balance_received", 0)))
        summary_balance_due = Decimal(str(summary_of_charges.get("balance_due", 0)))

        summary_table_data = [
            [
                Paragraph("Net Sales:", self.style_manager.total_label_style),
                Paragraph(self.currency_formatter.format_money(summary_net_sales, currency), self.style_manager.total_value_style)
            ],
            [
                Paragraph("CGST:", self.style_manager.total_label_style),
                Paragraph(self.currency_formatter.format_money(summary_cgst, currency), self.style_manager.total_value_style)
            ],
            [
                Paragraph("SGST:", self.style_manager.total_label_style),
                Paragraph(self.currency_formatter.format_money(summary_sgst, currency), self.style_manager.total_value_style)
            ],
            [
                Paragraph("Misc:", self.style_manager.total_label_style),
                Paragraph(self.currency_formatter.format_money(summary_misc, currency), self.style_manager.total_value_style)
            ],
            [
                Paragraph("<b>Total Amount:</b>", self.style_manager.total_label_style),
                Paragraph(f"<b>{self.currency_formatter.format_money(summary_total_amount, currency)}</b>", self.style_manager.total_value_style)
            ],
            [
                Paragraph("Balance Received:", self.style_manager.total_label_style),
                Paragraph(self.currency_formatter.format_money(summary_balance_received, currency), self.style_manager.total_value_style)
            ],
            [
                Paragraph("Balance Due:", self.style_manager.total_label_style),
                Paragraph(self.currency_formatter.format_money(summary_balance_due, currency), self.style_manager.total_value_style)
            ]
        ]

        summary_table = Table(
            summary_table_data,
            colWidths=[doc_width / 2, doc_width / 2],
        )
        summary_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0,0), (-1,-1), 3),
            ("TOPPADDING", (0,0), (-1,-1), 3),
            ("BACKGROUND", (0,4), (-1,4), colors.HexColor("#13cf16")), # Highlight Total Amount row (index 4)
            ("TEXTCOLOR", (0,4), (-1,4), colors.white), # White text for Total Amount row
        ]))
        summary_elements.append(summary_table)
        summary_elements.append(Spacer(1, 12 * mm))

        return summary_elements
    
    def _create_footer_section(self, data: Dict[str, Any], doc_width: float) -> List[Flowable]: # Added doc_width parameter
        """Create footer section with terms and authorised signatory."""
        elements = []
        
        additional_info = data.get("additional_information", {})
        terms_and_conditions = additional_info.get("terms_and_conditions", [])
        authorised_signatory = additional_info.get("authorised_signatory", '')
        authorised_signatory_image_url = additional_info.get("authorised_signatory_image_url", '')
        
        # Terms and conditions are now handled in _create_description_terms_section
        # for term in terms_and_conditions:
        #     elements.append(Paragraph(term, self.style_manager.footer_text_style))
        # elements.append(Spacer(1, 3 * mm)) # Add some space before the signature

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
