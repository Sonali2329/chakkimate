# -*- coding: utf-8 -*-
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import (
    Customer, Supplier, Product, StockMovement,
    Purchase, PurchaseItem, GrindingOrder,
    ProductionBatch, Sale, SaleItem, Invoice, Payment, Expense, ShopSettings
)

class InventoryService:
    @staticmethod
    @transaction.atomic
    def record_stock_movement(product, movement_type, quantity_kg, reference_type, reference_id, notes=""):
        """
        Atomically records a stock change in StockMovement and updates Product current_stock.
        quantity_kg can be positive (IN) or negative (OUT).
        """
        # Reload product with row lock if possible
        product = Product.objects.select_for_update().get(id=product.id)
        new_balance = product.current_stock + Decimal(str(quantity_kg))
        
        if new_balance < Decimal('0.000') and quantity_kg < Decimal('0.000'):
            # Allow only if explicitly confirmed or raise error
            raise ValidationError(
                f"Insufficient stock for {product.display_name}. Current: {product.current_stock:.3f} KG, Requested deduction: {abs(quantity_kg):.3f} KG"
            )

        product.current_stock = new_balance
        product.save(update_fields=['current_stock', 'updated_at'])

        movement = StockMovement.objects.create(
            product=product,
            stock_type=product.product_type,
            movement_type=movement_type,
            quantity_kg=Decimal(str(quantity_kg)),
            reference_type=reference_type,
            reference_id=reference_id,
            balance_after_kg=new_balance,
            notes=notes,
            created_at=timezone.now()
        )
        return movement

    @staticmethod
    @transaction.atomic
    def adjust_stock(product, new_stock_kg, reason, user_notes=""):
        """Manual stock correction with full auditable ledger entry."""
        product = Product.objects.select_for_update().get(id=product.id)
        diff = Decimal(str(new_stock_kg)) - product.current_stock
        
        product.current_stock = Decimal(str(new_stock_kg))
        product.save(update_fields=['current_stock', 'updated_at'])

        movement = StockMovement.objects.create(
            product=product,
            stock_type=product.product_type,
            movement_type='ADJUSTMENT',
            quantity_kg=diff,
            reference_type='MANUAL_ADJUSTMENT',
            reference_id=f"ADJ-{timezone.now().strftime('%Y%m%d%H%M')}",
            balance_after_kg=product.current_stock,
            notes=f"Adjustment: {reason}. {user_notes}".strip()
        )
        return movement


class PurchaseService:
    @staticmethod
    def generate_purchase_number():
        settings = ShopSettings.get_settings()
        prefix = settings.purchase_prefix or "PUR"
        today_str = timezone.now().strftime("%Y%m%d")
        count = Purchase.objects.filter(purchase_number__startswith=f"{prefix}-{today_str}").count() + 1
        return f"{prefix}-{today_str}-{count:03d}"

    @classmethod
    @transaction.atomic
    def create_purchase(cls, supplier, purchase_date, items_data, discount=0, other_charges=0,
                        amount_paid=0, payment_mode='CASH', notes=""):
        """
        Creates Purchase and lines, and atomically adds stock for all raw grain items.
        items_data: list of dicts [{'product': Product, 'quantity_kg': Decimal, 'rate_per_kg': Decimal}]
        """
        purchase_num = cls.generate_purchase_number()
        
        subtotal = Decimal('0.00')
        for it in items_data:
            qty = Decimal(str(it['quantity_kg']))
            rate = Decimal(str(it['rate_per_kg']))
            subtotal += (qty * rate)

        discount_dec = Decimal(str(discount or 0))
        other_charges_dec = Decimal(str(other_charges or 0))
        total_dec = max(Decimal('0.00'), subtotal - discount_dec + other_charges_dec)
        paid_dec = Decimal(str(amount_paid or 0))

        if paid_dec >= total_dec:
            pay_status = 'PAID'
        elif paid_dec > Decimal('0.00'):
            pay_status = 'PARTIAL'
        else:
            pay_status = 'UNPAID'

        purchase = Purchase.objects.create(
            supplier=supplier,
            purchase_number=purchase_num,
            purchase_date=purchase_date,
            subtotal=subtotal,
            discount=discount_dec,
            other_charges=other_charges_dec,
            total=total_dec,
            amount_paid=paid_dec,
            status='CONFIRMED',
            payment_status=pay_status,
            payment_mode=payment_mode,
            notes=notes
        )

        for it in items_data:
            prod = it['product']
            qty = Decimal(str(it['quantity_kg']))
            rate = Decimal(str(it['rate_per_kg']))
            line_tot = qty * rate

            PurchaseItem.objects.create(
                purchase=purchase,
                product=prod,
                quantity_kg=qty,
                rate_per_kg=rate,
                line_total=line_tot
            )

            # Atomically increment stock and record ledger
            InventoryService.record_stock_movement(
                product=prod,
                movement_type='PURCHASE',
                quantity_kg=qty,
                reference_type='PURCHASE',
                reference_id=purchase.purchase_number,
                notes=f"Purchased from {supplier.name}"
            )

        return purchase


class ProductionService:
    @staticmethod
    def generate_batch_number():
        settings = ShopSettings.get_settings()
        prefix = settings.production_prefix or "PROD"
        today_str = timezone.now().strftime("%Y%m%d")
        count = ProductionBatch.objects.filter(batch_number__startswith=f"{prefix}-{today_str}").count() + 1
        return f"{prefix}-{today_str}-{count:03d}"

    @classmethod
    @transaction.atomic
    def process_production_batch(cls, raw_product, flour_product, input_kg, output_kg, wastage_kg=0, batch_date=None, notes=""):
        """
        Executes own-grain flour processing:
        - Decreases raw grain stock by input_kg
        - Increases finished flour stock by output_kg
        - Stores wastage/bran weight
        - Records auditable movements in StockMovement
        """
        if not batch_date:
            batch_date = timezone.now().date()
            
        input_dec = Decimal(str(input_kg))
        output_dec = Decimal(str(output_kg))
        wastage_dec = Decimal(str(wastage_kg or (input_dec - output_dec)))
        if wastage_dec < Decimal('0.000'):
            wastage_dec = Decimal('0.000')

        batch_num = cls.generate_batch_number()

        # Deduct raw grain stock
        InventoryService.record_stock_movement(
            product=raw_product,
            movement_type='PRODUCTION_CONSUMED',
            quantity_kg=-input_dec,
            reference_type='PRODUCTION',
            reference_id=batch_num,
            notes=f"Consumed for processing {flour_product.name} (Batch #{batch_num})"
        )

        # Increase finished flour stock
        InventoryService.record_stock_movement(
            product=flour_product,
            movement_type='PRODUCTION_PRODUCED',
            quantity_kg=output_dec,
            reference_type='PRODUCTION',
            reference_id=batch_num,
            notes=f"Flour produced from {raw_product.name} (Batch #{batch_num})"
        )

        batch = ProductionBatch.objects.create(
            batch_number=batch_num,
            raw_product=raw_product,
            flour_product=flour_product,
            input_kg=input_dec,
            output_kg=output_dec,
            wastage_kg=wastage_dec,
            batch_date=batch_date,
            status='COMPLETED',
            notes=notes
        )
        return batch


class GrindingService:
    @staticmethod
    def generate_order_number():
        settings = ShopSettings.get_settings()
        prefix = settings.order_prefix or "GRN"
        today_str = timezone.now().strftime("%Y%m%d")
        count = GrindingOrder.objects.filter(order_number__startswith=f"{prefix}-{today_str}").count() + 1
        return f"{prefix}-{today_str}-{count:03d}"

    @classmethod
    @transaction.atomic
    def create_order(cls, customer, grain, input_kg, rate_per_kg=None, ownership_type='CUSTOMER',
                     expected_delivery=None, notes="", is_paid=False, payment_mode='CASH'):
        """
        Creates customer grinding order.
        Important rule: CUSTOMER grain grinding DOES NOT change mill stock!
        MILL grain grinding consumes raw stock.
        """
        input_dec = Decimal(str(input_kg))
        rate_dec = Decimal(str(rate_per_kg if rate_per_kg is not None else grain.grinding_rate))
        charges = (input_dec * rate_dec).quantize(Decimal('0.01'))

        order_num = cls.generate_order_number()
        token_num = f"T-{order_num.split('-')[-1]}"

        # If mill-owned grain, consume raw stock
        if ownership_type == 'MILL':
            InventoryService.record_stock_movement(
                product=grain,
                movement_type='GRAIN_SALE',
                quantity_kg=-input_dec,
                reference_type='GRINDING_ORDER',
                reference_id=order_num,
                notes=f"Grain supplied for grinding order {order_num}"
            )

        order = GrindingOrder.objects.create(
            order_number=order_num,
            token_number=token_num,
            customer=customer,
            grain=grain,
            ownership_type=ownership_type,
            input_kg=input_dec,
            rate_per_kg=rate_dec,
            charges=charges,
            status='PENDING',
            order_date=timezone.now(),
            expected_delivery=expected_delivery,
            is_paid=is_paid,
            payment_mode=payment_mode,
            notes=notes
        )

        # Create associated invoice for the grinding charge
        inv_prefix = ShopSettings.get_settings().invoice_prefix or "INV"
        inv_number = f"{inv_prefix}-G-{order_num}"
        
        status = 'PAID' if is_paid else 'UNPAID'
        amt_paid = charges if is_paid else Decimal('0.00')
        balance = Decimal('0.00') if is_paid else charges

        invoice = Invoice.objects.create(
            invoice_number=inv_number,
            invoice_type='GRINDING',
            customer=customer,
            grinding_order=order,
            invoice_date=timezone.now().date(),
            subtotal=charges,
            discount=Decimal('0.00'),
            total=charges,
            amount_paid=amt_paid,
            balance_due=balance,
            status=status,
            notes=f"Grinding order {order_num} ({grain.display_name} {input_dec} KG)"
        )

        if is_paid:
            Payment.objects.create(
                invoice=invoice,
                customer=customer,
                amount=charges,
                payment_mode=payment_mode,
                payment_date=timezone.now().date(),
                reference_number=f"GRN-PAID-{order.id}",
                notes="Paid at time of grinding order booking"
            )

        return order


class SalesService:
    @staticmethod
    def generate_sale_number():
        today_str = timezone.now().strftime("%Y%m%d")
        count = Sale.objects.filter(sale_number__startswith=f"SALE-{today_str}").count() + 1
        return f"SALE-{today_str}-{count:03d}"

    @classmethod
    @transaction.atomic
    def create_sale(cls, customer, items_data, discount=0, amount_paid=0, payment_mode='CASH', notes=""):
        """
        Creates Sale, Line items, reduces inventory for each item,
        and generates Invoice with automatic payment allocation.
        items_data: [{'product': Product, 'quantity_kg': Decimal, 'rate_per_kg': Decimal}]
        """
        sale_num = cls.generate_sale_number()
        
        subtotal = Decimal('0.00')
        for it in items_data:
            qty = Decimal(str(it['quantity_kg']))
            rate = Decimal(str(it['rate_per_kg']))
            subtotal += (qty * rate).quantize(Decimal('0.01'))

        discount_dec = Decimal(str(discount or 0))
        total_dec = max(Decimal('0.00'), subtotal - discount_dec)
        paid_dec = Decimal(str(amount_paid or 0))

        sale = Sale.objects.create(
            sale_number=sale_num,
            customer=customer,
            sale_date=timezone.now().date(),
            subtotal=subtotal,
            discount=discount_dec,
            total=total_dec,
            status='COMPLETED'
        )

        for it in items_data:
            prod = it['product']
            qty = Decimal(str(it['quantity_kg']))
            rate = Decimal(str(it['rate_per_kg']))
            line_tot = (qty * rate).quantize(Decimal('0.01'))

            SaleItem.objects.create(
                sale=sale,
                product=prod,
                quantity_kg=qty,
                rate_per_kg=rate,
                line_total=line_tot
            )

            # Deduct stock based on product category
            movement_type = 'GRAIN_SALE' if prod.product_type == 'RAW_GRAIN' else 'FLOUR_SALE'
            InventoryService.record_stock_movement(
                product=prod,
                movement_type=movement_type,
                quantity_kg=-qty,
                reference_type='SALE',
                reference_id=sale.sale_number,
                notes=f"Sold to {customer.name} (Sale #{sale_num})"
            )

        # Generate Invoice
        inv_prefix = ShopSettings.get_settings().invoice_prefix or "INV"
        today_str = timezone.now().strftime("%Y%m%d")
        count = Invoice.objects.filter(invoice_number__startswith=f"{inv_prefix}-{today_str}").count() + 1
        inv_number = f"{inv_prefix}-{today_str}-{count:03d}"

        balance_due = max(Decimal('0.00'), total_dec - paid_dec)
        inv_status = 'PAID' if balance_due == Decimal('0.00') else ('PARTIAL' if paid_dec > Decimal('0.00') else 'UNPAID')

        invoice = Invoice.objects.create(
            invoice_number=inv_number,
            invoice_type='SALE',
            customer=customer,
            sale=sale,
            invoice_date=timezone.now().date(),
            subtotal=subtotal,
            discount=discount_dec,
            total=total_dec,
            amount_paid=paid_dec,
            balance_due=balance_due,
            status=inv_status,
            notes=notes
        )

        if paid_dec > Decimal('0.00'):
            Payment.objects.create(
                invoice=invoice,
                customer=customer,
                amount=paid_dec,
                payment_mode=payment_mode,
                payment_date=timezone.now().date(),
                reference_number=f"PAY-{sale_num}",
                notes="Payment recorded during sale"
            )

        return sale, invoice


class BillingPaymentService:
    @staticmethod
    @transaction.atomic
    def record_payment(invoice, amount, payment_mode='CASH', reference_number="", notes="", payment_date=None):
        """
        Record a payment for an invoice and re-calculate outstanding balance.
        """
        if not payment_date:
            payment_date = timezone.now().date()
            
        amt_dec = Decimal(str(amount))
        if amt_dec <= Decimal('0.00'):
            raise ValidationError("Payment amount must be greater than zero.")

        if amt_dec > invoice.balance_due:
            # Prevent payment exceeding invoice balance
            raise ValidationError(f"Payment amount (₹{amt_dec:.2f}) cannot exceed invoice balance (₹{invoice.balance_due:.2f}).")

        payment = Payment.objects.create(
            invoice=invoice,
            customer=invoice.customer,
            amount=amt_dec,
            payment_mode=payment_mode,
            payment_date=payment_date,
            reference_number=reference_number,
            notes=notes
        )

        invoice.recalculate_balance()
        return payment
