# app/invoice.py
import os
from io import BytesIO
from typing import Dict, Any, List, Optional
import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, Flowable
)
from jinja2 import Template
from weasyprint import HTML

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "generated_pdfs")
os.makedirs(PDF_DIR, exist_ok=True)

# --- Default HTML template (embedded) ---
DEFAULT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Invoice {{ invoice_number }}</title>
<style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    h1 { color: #333; }
    .header { display: flex; justify-content: space-between; }
    .company, .client { width: 45%; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background-color: #f5f5f5; }
    .right { text-align: right; }
    .total { font-weight: bold; }
</style>
</head>
<body>
    <div class="header">
        <div class="company">
            <h2>{{ company_name }}</h2>
            <p>{{ company_address|replace("\n", "<br/>") }}</p>
            <p>{{ company_email }}</p>
            <p>{{ company_phone }}</p>
        </div>
        <div class="client">
            <h3>BILL TO:</h3>
            <p>{{ client_name }}</p>
            <p>{{ client_address|replace("\n", "<br/>") }}</p>
            <p>{{ client_email }}</p>
        </div>
    </div>

    <h1>Invoice</h1>
    <p><b>Invoice #:</b> {{ invoice_number }}<br>
    <b>Date:</b> {{ invoice_date }}<br>
    <b>Due Date:</b> {{ due_date }}<br>
    <b>Amount Due:</b> {{ currency }}{{ '%.2f' % _grand_total }}</p>

    <table>
        <tr>
            <th>Description</th>
            <th>Qty</th>
            <th>Unit Price</th>
            <th>Total</th>
        </tr>
        {% for item in items %}
        <tr>
            <td>{{ item.description }}</td>
            <td class="right">{{ item.quantity }}</td>
            <td class="right">{{ currency }}{{ '%.2f' % item.unit_price }}</td>
            <td class="right">{{ currency }}{{ '%.2f' % item.total }}</td>
        </tr>
        {% endfor %}
        <tr>
            <td colspan="3" class="right total">Subtotal</td>
            <td class="right total">{{ currency }}{{ '%.2f' % _subtotal }}</td>
        </tr>
        <tr>
            <td colspan="3" class="right total">Tax ({{ tax_rate*100 }}%)</td>
            <td class="right total">{{ currency }}{{ '%.2f' % _tax_amount }}</td>
        </tr>
        <tr>
            <td colspan="3" class="right total">Grand Total</td>
            <td class="right total">{{ currency }}{{ '%.2f' % _grand_total }}</td>
        </tr>
    </table>

    {% if notes %}
    <h3>Notes</h3>
    <p>{{ notes }}</p>
    {% endif %}

    {% if terms %}
    <h3>Terms</h3>
    <p>{{ terms }}</p>
    {% endif %}
</body>
</html>
"""

# --- Helper functions ---
def _fetch_image_bytes(url: str, timeout: int = 6) -> Optional[BytesIO]:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return BytesIO(resp.content)
    except Exception:
        return None

def _maybe_image(source: Optional[str], width: float, height: float) -> Optional[Image]:
    if not source:
        return None
    if source.startswith("http://") or source.startswith("https://"):
        b = _fetch_image_bytes(source)
        if b:
            try:
                return Image(b, width=width, height=height)
            except Exception:
                return None
    else:
        if os.path.exists(source):
            try:
                return Image(source, width=width, height=height)
            except Exception:
                return None
    return None

def _money(val: float, currency: str = "$") -> str:
    return f"{currency}{val:,.2f}"

# --- Main invoice generation function ---
def generate_invoice_pdf(invoice_id: str, data: Dict[str, Any], use_html_template: bool = False) -> str:
    if use_html_template:
        return _generate_invoice_html(invoice_id, data)
    else:
        return _generate_invoice_reportlab(invoice_id, data)

# HTML method
def _generate_invoice_html(invoice_id: str, data: Dict[str, Any]) -> str:
    template = Template(DEFAULT_HTML_TEMPLATE)
    html_content = template.render(**data)
    file_path = os.path.join(PDF_DIR, f"{invoice_id}.pdf")
    HTML(string=html_content).write_pdf(file_path)
    return file_path

# ReportLab method
def _generate_invoice_reportlab(invoice_id: str, data: Dict[str, Any]) -> str:
    file_path = os.path.join(PDF_DIR, f"{invoice_id}.pdf")
    doc = SimpleDocTemplate(file_path, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.spaceAfter = 6
    small_bold = ParagraphStyle("small_bold", parent=styles["Normal"], fontSize=9)
    right_small = ParagraphStyle("right_small", parent=styles["Normal"], alignment=2, fontSize=10)
    elements: List[Flowable] = []

    # Header
    company_lines = f"<b>{data.get('company_name','')}</b><br/>{data.get('company_address','')}<br/>{data.get('company_email','')}<br/>{data.get('company_phone','')}"
    company_para = Paragraph(company_lines, normal)
    logo = _maybe_image(data.get("company_logo_url") or data.get("logo_url"), 60 * mm, 20 * mm)
    hdr_table = Table([[company_para, logo or ""]], colWidths=[100 * mm, 60 * mm])
    hdr_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    elements.append(hdr_table)
    elements.append(Spacer(1, 6))

    # Bill To + Meta
    bill_to_para = Paragraph(f"<b>BILL TO:</b><br/><b>{data.get('client_name','')}</b><br/>{data.get('client_address','')}<br/>{data.get('client_email','')}", normal)
    subtotal = sum(float(it.get("total", it.get("quantity", 0) * it.get("unit_price", 0))) for it in data.get("items", []))
    tax_rate = float(data.get("tax_rate", 0) or 0)
    tax_amount = subtotal * tax_rate
    grand_total = subtotal + tax_amount
    currency = data.get("currency", "$")
    meta_para = Paragraph(f"<b>INVOICE #</b><br/>{data.get('invoice_number','')}<br/><br/><b>INVOICE DATE</b><br/>{data.get('invoice_date','')}<br/><br/><b>DUE DATE</b><br/>{data.get('due_date','')}<br/><br/><b>AMOUNT DUE</b><br/>{_money(grand_total, currency)}", right_small)
    meta_table = Table([[bill_to_para, meta_para]], colWidths=[100 * mm, 60 * mm])
    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    # Items Table
    table_data = [["Item", "Description", "Qty", "Unit Price", "Total"]]
    for it in data.get("items", []):
        table_data.append([it.get("name", "") or it.get("description", ""), Paragraph(it.get("description", ""), normal),
                           str(it.get("quantity", 0)), _money(it.get("unit_price", 0), currency), _money(it.get("total", 0), currency)])
    table_data.append(["", "", "", "Subtotal", _money(subtotal, currency)])
    table_data.append(["", "", "", f"Tax ({tax_rate*100:.0f}%)", _money(tax_amount, currency)])
    table_data.append(["", "", "", "<b>Total</b>", f"<b>{_money(grand_total, currency)}</b>"])
    items_table = Table(table_data, colWidths=[45 * mm, 65 * mm, 20 * mm, 30 * mm, 30 * mm])
    items_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")), ("ALIGN", (2, 1), (4, -1), "CENTER"), ("GRID", (0, 0), (-1, -4), 0.25, colors.HexColor("#d0d0d0"))]))
    elements.append(items_table)

    # Notes & Terms
    if data.get("notes"):
        elements.append(Paragraph("<b>Notes</b>", small_bold))
        elements.append(Paragraph(data["notes"], normal))
    if data.get("terms"):
        elements.append(Paragraph("<b>Terms</b>", small_bold))
        elements.append(Paragraph(data["terms"], normal))

    doc.build(elements)
    return file_path
