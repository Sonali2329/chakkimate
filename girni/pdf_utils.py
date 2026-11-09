# -*- coding: utf-8 -*-
import io
from decimal import Decimal
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from .models import Invoice, ShopSettings

def generate_invoice_pdf(invoice_id):
    """
    Generates a high-quality professional PDF invoice for a given Invoice ID.
    Returns bytes buffer for HttpResponse.
    """
    invoice = Invoice.objects.select_related('customer', 'sale', 'grinding_order').get(id=invoice_id)
    settings = ShopSettings.get_settings()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1, # Center
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#4B5563'),
        alignment=1,
        fontName='Helvetica'
    )

    header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Normal'],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1F2937'),
        fontName='Helvetica-Bold'
    )

    cell_style = ParagraphStyle(
        'Cell',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        fontName='Helvetica'
    )

    cell_bold = ParagraphStyle(
        'CellBold',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        fontName='Helvetica-Bold'
    )

    cell_right = ParagraphStyle(
        'CellRight',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        alignment=2, # Right
        fontName='Helvetica'
    )

    cell_right_bold = ParagraphStyle(
        'CellRightBold',
        parent=styles['Normal'],
        fontSize=9,
        leading=12,
        alignment=2, # Right
        fontName='Helvetica-Bold'
    )

    elements = []

    # 1. Header with Shop Details
    shop_title = settings.shop_name
    elements.append(Paragraph(f"<b>{shop_title}</b>", title_style))
    contact_line = f"Proprietor: {settings.owner_name} | Mobile: {settings.mobile}"
    if settings.secondary_mobile:
        contact_line += f", {settings.secondary_mobile}"
    elements.append(Paragraph(contact_line, subtitle_style))
    elements.append(Paragraph(f"Address: {settings.address}", subtitle_style))
    if settings.gst_enabled and settings.gst_number:
        elements.append(Paragraph(f"GSTIN: {settings.gst_number}", subtitle_style))
    
    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1E3A8A'), spaceAfter=15))

    # 2. Bill Meta & Customer Info Table
    cust = invoice.customer
    inv_type_display = "FLOUR & GRAIN SALE INVOICE" if invoice.invoice_type == 'SALE' else "FLOUR MILL GRINDING BILL"
    
    meta_data = [
        [
            Paragraph(f"<b>Billed To:</b><br/><b>{cust.name}</b><br/>Mobile: {cust.mobile}<br/>Address: {cust.address or 'N/A'}", cell_style),
            Paragraph(
                f"<b>INVOICE DETAILS</b><br/>"
                f"<b>Invoice #:</b> {invoice.invoice_number}<br/>"
                f"<b>Date:</b> {invoice.invoice_date.strftime('%d-%m-%Y')}<br/>"
                f"<b>Type:</b> {inv_type_display}<br/>"
                f"<b>Status:</b> <b>{invoice.status}</b>",
                cell_style
            )
        ]
    ]
    meta_table = Table(meta_data, colWidths=[260, 260])
    meta_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#F8FAFC')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#EFF6FF')),
        ('BOX', (0, 0), (0, 0), 1, colors.HexColor('#CBD5E1')),
        ('BOX', (1, 0), (1, 0), 1, colors.HexColor('#93C5FD')),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 15))

    # 3. Line Items Table
    item_rows = [
        [
            Paragraph("<b>#</b>", cell_bold),
            Paragraph("<b>Item / Service Description</b>", cell_bold),
            Paragraph("<b>Quantity (KG)</b>", cell_right_bold),
            Paragraph("<b>Rate (Rs./KG)</b>", cell_right_bold),
            Paragraph("<b>Amount (Rs.)</b>", cell_right_bold)
        ]
    ]

    idx = 1
    if invoice.sale:
        for it in invoice.sale.items.all():
            item_rows.append([
                Paragraph(str(idx), cell_style),
                Paragraph(f"{it.product.name} ({it.product.get_product_type_display()})", cell_style),
                Paragraph(f"{it.quantity_kg:.3f}", cell_right),
                Paragraph(f"Rs. {it.rate_per_kg:.2f}", cell_right),
                Paragraph(f"Rs. {it.line_total:.2f}", cell_right)
            ])
            idx += 1
    elif invoice.grinding_order:
        go = invoice.grinding_order
        desc = f"Customer Grinding: {go.grain.name} [Token: {go.token_number or go.order_number}]"
        item_rows.append([
            Paragraph(str(idx), cell_style),
            Paragraph(desc, cell_style),
            Paragraph(f"{go.input_kg:.3f}", cell_right),
            Paragraph(f"Rs. {go.rate_per_kg:.2f}", cell_right),
            Paragraph(f"Rs. {go.charges:.2f}", cell_right)
        ])
    else:
        item_rows.append([
            Paragraph("1", cell_style),
            Paragraph(invoice.notes or "Miscellaneous charges", cell_style),
            Paragraph("-", cell_right),
            Paragraph("-", cell_right),
            Paragraph(f"Rs. {invoice.total:.2f}", cell_right)
        ])

    items_table = Table(item_rows, colWidths=[30, 250, 80, 80, 80])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('PADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 10))

    # 4. Totals & Payment Summary Box
    summary_data = [
        ["", Paragraph("<b>Subtotal:</b>", cell_right), Paragraph(f"Rs. {invoice.subtotal:.2f}", cell_right)],
        ["", Paragraph("<b>Discount:</b>", cell_right), Paragraph(f"- Rs. {invoice.discount:.2f}", cell_right)],
        ["", Paragraph("<b>Grand Total:</b>", cell_right_bold), Paragraph(f"<b>Rs. {invoice.total:.2f}</b>", cell_right_bold)],
        ["", Paragraph("<b>Amount Received:</b>", cell_right), Paragraph(f"Rs. {invoice.amount_paid:.2f}", cell_right)],
        ["", Paragraph("<b>Balance Remaining:</b>", cell_right_bold), Paragraph(f"<b>Rs. {invoice.balance_due:.2f}</b>", cell_right_bold)],
    ]
    summary_table = Table(summary_data, colWidths=[240, 140, 140])
    summary_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('LINEBELOW', (1, 2), (2, 2), 1, colors.HexColor('#1E3A8A')),
        ('LINEBELOW', (1, 4), (2, 4), 1.5, colors.HexColor('#DC2626') if invoice.balance_due > 0 else colors.HexColor('#16A34A')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    # 5. Payment details & Shop footer
    footer_text = settings.footer_message
    if settings.upi_id:
        footer_text += f"<br/><b>Pay via UPI / QR: {settings.upi_id}</b>"
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E2E8F0'), spaceAfter=10))
    elements.append(Paragraph(footer_text, subtitle_style))
    elements.append(Paragraph("<i>Computer generated invoice by ChakkiMate Girni Management System.</i>", subtitle_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
