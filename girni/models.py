# -*- coding: utf-8 -*-
from decimal import Decimal
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError


class Customer(models.Model):
    CUSTOMER_TYPE_CHOICES = (
        ('REGULAR', 'Regular (कायमचे)'),
        ('WALKIN', 'Walk-in (किरकोळ)'),
    )

    name = models.CharField(max_length=150, verbose_name="Customer Name / नाव")
    mobile = models.CharField(max_length=20, db_index=True, verbose_name="Mobile / मोबाईल")
    address = models.TextField(blank=True, verbose_name="Address / पत्ता")
    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPE_CHOICES,
        default='REGULAR',
        verbose_name="Customer Type / प्रकार"
    )
    is_active = models.BooleanField(default=True, verbose_name="Active Status")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']
        verbose_name = "Customer"
        verbose_name_plural = "Customers"

    def __str__(self):
        return f"{self.name} ({self.mobile})"

    @property
    def total_outstanding(self):
        """Sum of balance_due across all unpaid/partial invoices."""
        invoices = self.invoices.filter(status__in=['UNPAID', 'PARTIAL'])
        return sum(inv.balance_due for inv in invoices) or Decimal('0.00')


class Supplier(models.Model):
    name = models.CharField(max_length=150, verbose_name="Supplier Name / पुरवठादाराचे नाव")
    mobile = models.CharField(max_length=20, verbose_name="Mobile / मोबाईल")
    address = models.TextField(blank=True, verbose_name="Address / पत्ता")
    notes = models.TextField(blank=True, verbose_name="Notes / टीप")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"

    def __str__(self):
        return f"{self.name} ({self.mobile})"

    @property
    def total_purchases(self):
        return sum(p.total for p in self.purchases.filter(status='CONFIRMED')) or Decimal('0.00')

    @property
    def total_payable_balance(self):
        confirmed = self.purchases.filter(status='CONFIRMED')
        return sum(p.balance_due for p in confirmed) or Decimal('0.00')


class Product(models.Model):
    PRODUCT_TYPE_CHOICES = (
        ('RAW_GRAIN', 'Raw Grain / कच्चे धान्य'),
        ('FINISHED_FLOUR', 'Finished Flour / तयार पीठ'),
    )

    name = models.CharField(max_length=120, verbose_name="Product Name (English)")
    name_mr = models.CharField(max_length=120, blank=True, verbose_name="Product Name (मराठी नाव)")
    product_type = models.CharField(
        max_length=30,
        choices=PRODUCT_TYPE_CHOICES,
        default='RAW_GRAIN',
        verbose_name="Category / प्रकार"
    )
    unit = models.CharField(max_length=20, default='KG', verbose_name="Unit (Default KG)")
    purchase_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Purchase Rate (₹/KG)"
    )
    selling_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Selling Rate (₹/KG)"
    )
    grinding_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('5.00'),
        verbose_name="Grinding Rate (₹/KG)"
    )
    current_stock = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('0.000'),
        verbose_name="Current Stock (KG)"
    )
    low_stock_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal('20.000'),
        verbose_name="Low Stock Alert Level (KG)"
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Product / Grain"
        verbose_name_plural = "Products / Grains"

    def __str__(self):
        if self.name_mr:
            return f"{self.name} ({self.name_mr})"
        return self.name

    @property
    def display_name(self):
        if self.name_mr:
            return f"{self.name} / {self.name_mr}"
        return self.name

    @property
    def is_low_stock(self):
        return self.current_stock <= self.low_stock_threshold


class StockMovement(models.Model):
    MOVEMENT_TYPE_CHOICES = (
        ('PURCHASE', 'Purchase Received (खरेदी)'),
        ('GRAIN_SALE', 'Grain Sale (धान्य विक्री)'),
        ('FLOUR_SALE', 'Flour Sale (पीठ विक्री)'),
        ('PRODUCTION_CONSUMED', 'Production Consumed (उत्पादनासाठी वापरलेले कच्चे धान्य)'),
        ('PRODUCTION_PRODUCED', 'Production Produced (तयार पीठ उत्पादन)'),
        ('ADJUSTMENT', 'Manual Adjustment (साठा दुरुस्ती)'),
        ('REVERSAL', 'Transaction Reversal (रद्द व्यवहार परतावा)'),
    )

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='stock_movements')
    stock_type = models.CharField(max_length=30, choices=Product.PRODUCT_TYPE_CHOICES)
    movement_type = models.CharField(max_length=40, choices=MOVEMENT_TYPE_CHOICES)
    quantity_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Quantity (KG) [+ In / - Out]")
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    balance_after_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Stock Balance After (KG)")
    notes = models.TextField(blank=True, verbose_name="Reason / Notes")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="Movement Timestamp")

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"

    def __str__(self):
        return f"{self.product.name} | {self.movement_type} | {self.quantity_kg:+.3f} KG"


class Purchase(models.Model):
    STATUS_CHOICES = (
        ('CONFIRMED', 'Confirmed (नोंदवले)'),
        ('DRAFT', 'Draft (मसुदा)'),
        ('CANCELLED', 'Cancelled (रद्द)'),
    )
    PAYMENT_STATUS_CHOICES = (
        ('PAID', 'Paid (पूर्ण जमा)'),
        ('PARTIAL', 'Partial (अर्धवट)'),
        ('UNPAID', 'Unpaid (बाकी)'),
    )

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    purchase_number = models.CharField(max_length=50, unique=True, verbose_name="Purchase Bill #")
    purchase_date = models.DateField(default=timezone.now, verbose_name="Purchase Date")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    other_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CONFIRMED')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PAID')
    payment_mode = models.CharField(max_length=30, default='CASH')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-purchase_date', '-id']
        verbose_name = "Purchase"
        verbose_name_plural = "Purchases"

    def __str__(self):
        return f"{self.purchase_number} - {self.supplier.name} (₹{self.total})"

    @property
    def balance_due(self):
        return max(Decimal('0.00'), self.total - self.amount_paid)


class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_items')
    quantity_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Quantity (KG)")
    rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Rate (₹/KG) [Snapshot]")
    line_total = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Line Total (₹)")

    def __str__(self):
        return f"{self.product.name} - {self.quantity_kg} KG @ ₹{self.rate_per_kg}"


class GrindingOrder(models.Model):
    OWNERSHIP_CHOICES = (
        ('CUSTOMER', 'Customer Grain (ग्राहकाचे धान्य) - Mill stock unaffected'),
        ('MILL', 'Mill Grain (गिरणीचे धान्य) - Consumes mill raw stock'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending (प्रलंबित)'),
        ('IN_PROGRESS', 'In Progress (चालू आहे)'),
        ('COMPLETED', 'Completed (तयार आहे)'),
        ('DELIVERED', 'Delivered (ग्राहकाला दिले)'),
        ('CANCELLED', 'Cancelled (रद्द)'),
    )

    order_number = models.CharField(max_length=50, unique=True, verbose_name="Order Number")
    token_number = models.CharField(max_length=30, blank=True, verbose_name="Token / पावती क्र.")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='grinding_orders')
    grain = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='grinding_orders')
    ownership_type = models.CharField(max_length=20, choices=OWNERSHIP_CHOICES, default='CUSTOMER')
    input_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Input Grain (KG)")
    output_kg = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, verbose_name="Output Flour (KG)")
    wastage_kg = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'), verbose_name="Wastage / Husk (KG)")
    rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Grinding Rate (₹/KG) [Snapshot]")
    charges = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Total Grinding Charges (₹)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    order_date = models.DateTimeField(default=timezone.now)
    expected_delivery = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    payment_mode = models.CharField(max_length=30, default='CASH')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-order_date', '-id']
        verbose_name = "Grinding Order"
        verbose_name_plural = "Grinding Orders"

    def __str__(self):
        return f"{self.order_number} - {self.customer.name} ({self.grain.name} {self.input_kg} KG)"


class ProductionBatch(models.Model):
    STATUS_CHOICES = (
        ('COMPLETED', 'Completed (पूर्ण)'),
        ('CANCELLED', 'Cancelled (रद्द)'),
    )

    batch_number = models.CharField(max_length=50, unique=True, verbose_name="Batch #")
    raw_product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='production_inputs',
        verbose_name="Raw Grain Consumed (कच्चे धान्य)"
    )
    flour_product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='production_outputs',
        verbose_name="Finished Flour Produced (तयार पीठ)"
    )
    input_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Raw Grain Consumed (KG)")
    output_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Finished Flour Produced (KG)")
    wastage_kg = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'), verbose_name="Wastage / Bran / Husk (KG)")
    batch_date = models.DateField(default=timezone.now, verbose_name="Processing Date")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    notes = models.TextField(blank=True, verbose_name="Batch Notes / Machine Details")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-batch_date', '-id']
        verbose_name = "Production Batch"
        verbose_name_plural = "Production Batches"

    def __str__(self):
        return f"{self.batch_number} | {self.raw_product.name} -> {self.flour_product.name}"

    @property
    def yield_percentage(self):
        if self.input_kg and self.input_kg > Decimal('0.000'):
            return round((self.output_kg / self.input_kg) * Decimal('100.0'), 2)
        return Decimal('0.00')


class Sale(models.Model):
    STATUS_CHOICES = (
        ('COMPLETED', 'Completed (पूर्ण)'),
        ('CANCELLED', 'Cancelled (रद्द)'),
    )

    sale_number = models.CharField(max_length=50, unique=True, verbose_name="Sale Number")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='sales')
    sale_date = models.DateField(default=timezone.now, verbose_name="Sale Date")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sale_date', '-id']
        verbose_name = "Sale"
        verbose_name_plural = "Sales"

    def __str__(self):
        return f"{self.sale_number} - {self.customer.name} (₹{self.total})"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='sale_items')
    quantity_kg = models.DecimalField(max_digits=12, decimal_places=3, verbose_name="Quantity (KG)")
    rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Rate (₹/KG) [Snapshot]")
    line_total = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Line Total (₹)")

    def __str__(self):
        return f"{self.product.name} - {self.quantity_kg} KG @ ₹{self.rate_per_kg}"


class Invoice(models.Model):
    INVOICE_TYPE_CHOICES = (
        ('SALE', 'Product Sale Bill (विक्री बिल)'),
        ('GRINDING', 'Grinding Bill (दळण बिल)'),
        ('COMBINED', 'Combined Bill (एकत्रित बिल)'),
    )
    STATUS_CHOICES = (
        ('PAID', 'Paid (पूर्ण जमा)'),
        ('PARTIAL', 'Partial (अर्धवट)'),
        ('UNPAID', 'Unpaid (बाकी)'),
        ('CANCELLED', 'Cancelled (रद्द)'),
    )

    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="Invoice Number")
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPE_CHOICES, default='SALE')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices')
    sale = models.OneToOneField(Sale, on_delete=models.PROTECT, null=True, blank=True, related_name='invoice')
    grinding_order = models.OneToOneField(
        GrindingOrder,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='invoice'
    )
    invoice_date = models.DateField(default=timezone.now, verbose_name="Invoice Date")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNPAID')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date', '-id']
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"

    def __str__(self):
        return f"{self.invoice_number} - {self.customer.name} (₹{self.total}) [{self.status}]"

    def recalculate_balance(self):
        """Update amount_paid and balance_due based on confirmed Payments."""
        total_payments = sum(p.amount for p in self.payments.all()) or Decimal('0.00')
        self.amount_paid = min(total_payments, self.total)
        self.balance_due = max(Decimal('0.00'), self.total - self.amount_paid)
        if self.balance_due == Decimal('0.00'):
            self.status = 'PAID'
        elif self.amount_paid > Decimal('0.00'):
            self.status = 'PARTIAL'
        else:
            self.status = 'UNPAID'
        self.save()


class Payment(models.Model):
    PAYMENT_MODE_CHOICES = (
        ('CASH', 'Cash (रोख)'),
        ('UPI', 'UPI / QR Code (यूपीआय)'),
        ('BANK_TRANSFER', 'Bank Transfer (बँक खात्यात)'),
        ('OTHER', 'Other (इतर)'),
    )

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name="Linked Invoice"
    )
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Amount Paid (₹)")
    payment_mode = models.CharField(max_length=30, choices=PAYMENT_MODE_CHOICES, default='CASH')
    payment_date = models.DateField(default=timezone.now, verbose_name="Payment Date")
    reference_number = models.CharField(max_length=100, blank=True, verbose_name="UPI/Ref # (संदर्भ क्र.)")
    notes = models.TextField(blank=True, verbose_name="Notes / टीप")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        verbose_name = "Payment"
        verbose_name_plural = "Payments"

    def __str__(self):
        return f"₹{self.amount} by {self.customer.name} ({self.payment_mode})"


class Expense(models.Model):
    CATEGORY_CHOICES = (
        ('ELECTRICITY', 'Electricity Bill (लाईट बिल)'),
        ('REPAIR', 'Machine Repair & Maintenance (मशिन दुरुस्ती व देखभाल)'),
        ('TRANSPORT', 'Transport / Hamali (वाहतूक / हमाली)'),
        ('SALARY', 'Wages / Salary (कामगार पगार)'),
        ('RENT', 'Shop Rent (दुकान भाडे)'),
        ('PACKAGING', 'Bags & Packaging (बारदाने / पिशव्या)'),
        ('OTHER', 'Other Expenses (इतर किरकोळ खर्च)'),
    )
    PAYMENT_MODE_CHOICES = (
        ('CASH', 'Cash (रोख)'),
        ('UPI', 'UPI / QR Code (यूपीआय)'),
        ('BANK_TRANSFER', 'Bank Transfer (बँक खात्यात)'),
        ('OTHER', 'Other (इतर)'),
    )

    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default='OTHER')
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Amount (₹)")
    expense_date = models.DateField(default=timezone.now, verbose_name="Expense Date")
    payment_mode = models.CharField(max_length=30, choices=PAYMENT_MODE_CHOICES, default='CASH')
    description = models.CharField(max_length=255, verbose_name="Description / तपशील")
    receipt_file = models.FileField(upload_to='expenses/', null=True, blank=True, verbose_name="Receipt (Optional)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-id']
        verbose_name = "Expense"
        verbose_name_plural = "Expenses"

    def __str__(self):
        return f"{self.get_category_display()} - ₹{self.amount} ({self.expense_date})"


class ShopSettings(models.Model):
    shop_name = models.CharField(max_length=150, default="ChakkiMate Flour Mill")
    shop_name_mr = models.CharField(max_length=150, default="चक्कीमेट आधुनिक गिरणी")
    owner_name = models.CharField(max_length=120, default="आनंद पाटील (Anand Patil)")
    mobile = models.CharField(max_length=20, default="9876543210")
    secondary_mobile = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="chakkimate@gmail.com")
    address = models.TextField(default="Near Market Yard, Main Road, Kolhapur")
    address_mr = models.TextField(default="मार्केट यार्ड जवळ, मेन रोड, कोल्हापूर - ४१६००१")
    default_language = models.CharField(max_length=10, default="mr", choices=(('mr', 'मराठी (Marathi)'), ('en', 'English')))
    currency_symbol = models.CharField(max_length=10, default="₹")
    invoice_prefix = models.CharField(max_length=10, default="INV")
    order_prefix = models.CharField(max_length=10, default="GRN")
    purchase_prefix = models.CharField(max_length=10, default="PUR")
    production_prefix = models.CharField(max_length=10, default="PROD")
    gst_enabled = models.BooleanField(default=False)
    gst_number = models.CharField(max_length=30, blank=True, default="")
    upi_id = models.CharField(max_length=100, blank=True, default="chakkimate@okaxis")
    footer_message = models.TextField(default="आमच्या गिरणीला भेट दिल्याबद्दल धन्यवाद! पुन्हा या! / Thank you for visiting!")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shop Settings"
        verbose_name_plural = "Shop Settings"

    def __str__(self):
        return self.shop_name

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj
