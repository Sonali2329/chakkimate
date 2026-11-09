# -*- coding: utf-8 -*-
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from .models import (
    Customer, Supplier, Product, StockMovement,
    Purchase, PurchaseItem, GrindingOrder,
    ProductionBatch, Sale, SaleItem, Invoice, Payment, ShopSettings
)
from .services import (
    InventoryService, PurchaseService, ProductionService,
    GrindingService, SalesService, BillingPaymentService
)
from .pdf_utils import generate_invoice_pdf


class ChakkiMateBusinessLogicTests(TestCase):
    def setUp(self):
        # Create Owner User
        self.user = User.objects.create_superuser('owner', 'owner@chakkimate.com', 'owner')
        self.client = Client()
        self.client.force_login(self.user)

        # Settings
        self.settings = ShopSettings.get_settings()
        self.settings.shop_name = "ChakkiMate Flour Mill"
        self.settings.save()

        # Customer & Supplier
        self.customer = Customer.objects.create(
            name="Ramesh Patil",
            mobile="9822100001",
            address="Kolhapur",
            customer_type="REGULAR"
        )
        self.supplier = Supplier.objects.create(
            name="Kisan Agro",
            mobile="9422000011",
            address="Market Yard"
        )

        # Products
        self.wheat = Product.objects.create(
            name="Lokwan Wheat",
            name_mr="लोकवन गहू",
            product_type="RAW_GRAIN",
            purchase_rate=Decimal("30.00"),
            selling_rate=Decimal("38.00"),
            grinding_rate=Decimal("5.00"),
            current_stock=Decimal("100.000"),
            low_stock_threshold=Decimal("20.000")
        )

        self.wheat_flour = Product.objects.create(
            name="Fresh Chakki Atta",
            name_mr="ताजे चक्की पीठ",
            product_type="FINISHED_FLOUR",
            purchase_rate=Decimal("0.00"),
            selling_rate=Decimal("42.00"),
            grinding_rate=Decimal("0.00"),
            current_stock=Decimal("50.000"),
            low_stock_threshold=Decimal("10.000")
        )

    def test_scenario_1_purchase_100kg_wheat(self):
        """
        SRS Test Scenario 1:
        Purchase 100 KG wheat -> Raw wheat stock increases by 100 KG after purchase is posted.
        """
        initial_stock = self.wheat.current_stock  # 100.000
        purchase = PurchaseService.create_purchase(
            supplier=self.supplier,
            purchase_date=timezone.now().date(),
            items_data=[{
                'product': self.wheat,
                'quantity_kg': Decimal('100.000'),
                'rate_per_kg': Decimal('32.00')
            }],
            discount=0,
            amount_paid=Decimal('3200.00')
        )

        self.wheat.refresh_from_db()
        self.assertEqual(self.wheat.current_stock, initial_stock + Decimal('100.000'))
        
        # Verify ledger
        movement = StockMovement.objects.filter(reference_id=purchase.purchase_number).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.movement_type, 'PURCHASE')
        self.assertEqual(movement.quantity_kg, Decimal('100.000'))
        self.assertEqual(movement.balance_after_kg, Decimal('200.000'))

    def test_scenario_2_sell_10kg_wheat(self):
        """
        SRS Test Scenario 2:
        Sell 10 KG wheat -> Raw wheat stock decreases by 10 KG; sale bill is generated.
        """
        initial_stock = self.wheat.current_stock  # 100.000
        sale, invoice = SalesService.create_sale(
            customer=self.customer,
            items_data=[{
                'product': self.wheat,
                'quantity_kg': Decimal('10.000'),
                'rate_per_kg': Decimal('38.00')
            }],
            discount=0,
            amount_paid=Decimal('380.00')
        )

        self.wheat.refresh_from_db()
        self.assertEqual(self.wheat.current_stock, initial_stock - Decimal('10.000'))
        self.assertEqual(invoice.total, Decimal('380.00'))
        self.assertEqual(invoice.status, 'PAID')

        # Verify ledger
        movement = StockMovement.objects.filter(reference_id=sale.sale_number).first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.movement_type, 'GRAIN_SALE')
        self.assertEqual(movement.quantity_kg, Decimal('-10.000'))
        self.assertEqual(movement.balance_after_kg, Decimal('90.000'))

    def test_scenario_3_customer_grinding_stock_unaffected(self):
        """
        SRS Test Scenario 3:
        Customer brings 20 KG wheat for grinding -> Grinding charge is calculated; mill stock does not change.
        """
        initial_stock = self.wheat.current_stock  # 100.000
        order = GrindingService.create_order(
            customer=self.customer,
            grain=self.wheat,
            input_kg=Decimal('20.000'),
            rate_per_kg=Decimal('5.00'),
            ownership_type='CUSTOMER'
        )

        self.wheat.refresh_from_db()
        # Crucial requirement: Customer-owned grain grinding MUST NOT change mill stock!
        self.assertEqual(self.wheat.current_stock, initial_stock)
        self.assertEqual(order.charges, Decimal('100.00'))  # 20 * 5 = 100.00
        self.assertIsNotNone(order.invoice)
        self.assertEqual(order.invoice.total, Decimal('100.00'))

    def test_scenario_4_production_batch_reconcile_yield(self):
        """
        SRS Test Scenario 4:
        Process 50 KG mill-owned wheat into 42 KG flour ->
        Raw stock decreases 50 KG; flour stock increases 42 KG;
        remaining 8 KG is recorded as wastage/by-product.
        """
        initial_raw = self.wheat.current_stock          # 100.000
        initial_flour = self.wheat_flour.current_stock  # 50.000

        batch = ProductionService.process_production_batch(
            raw_product=self.wheat,
            flour_product=self.wheat_flour,
            input_kg=Decimal('50.000'),
            output_kg=Decimal('42.000'),
            wastage_kg=Decimal('8.000')
        )

        self.wheat.refresh_from_db()
        self.wheat_flour.refresh_from_db()

        self.assertEqual(self.wheat.current_stock, initial_raw - Decimal('50.000'))        # 50.000
        self.assertEqual(self.wheat_flour.current_stock, initial_flour + Decimal('42.000')) # 92.000
        self.assertEqual(batch.wastage_kg, Decimal('8.000'))
        self.assertEqual(batch.yield_percentage, Decimal('84.00'))  # (42/50)*100 = 84.00%

    def test_scenario_5_invoice_and_partial_payment(self):
        """
        SRS Test Scenario 5:
        Invoice total ₹500; payment ₹300 -> Paid amount ₹300; outstanding balance ₹200.
        """
        invoice = Invoice.objects.create(
            invoice_number="INV-TEST-001",
            invoice_type="SALE",
            customer=self.customer,
            invoice_date=timezone.now().date(),
            subtotal=Decimal('500.00'),
            total=Decimal('500.00'),
            amount_paid=Decimal('0.00'),
            balance_due=Decimal('500.00'),
            status="UNPAID"
        )

        # Pay 300
        BillingPaymentService.record_payment(
            invoice=invoice,
            amount=Decimal('300.00'),
            payment_mode="UPI"
        )

        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal('300.00'))
        self.assertEqual(invoice.balance_due, Decimal('200.00'))
        self.assertEqual(invoice.status, 'PARTIAL')

    def test_scenario_6_price_change_snapshot_preservation(self):
        """
        SRS Test Scenario 6:
        Change grain selling rate -> Previously issued invoice retains its original rate.
        """
        sale, invoice = SalesService.create_sale(
            customer=self.customer,
            items_data=[{
                'product': self.wheat,
                'quantity_kg': Decimal('10.000'),
                'rate_per_kg': Decimal('38.00')
            }]
        )
        self.assertEqual(invoice.total, Decimal('380.00'))

        # Now change master selling rate from 38 to 45
        self.wheat.selling_rate = Decimal('45.00')
        self.wheat.save()

        # The historical sale item must retain snapshot 38.00
        sale_item = sale.items.first()
        sale_item.refresh_from_db()
        self.assertEqual(sale_item.rate_per_kg, Decimal('38.00'))
        self.assertEqual(sale_item.line_total, Decimal('380.00'))

        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal('380.00'))

    def test_scenario_7_pdf_generation(self):
        """
        Verify PDF generation generates valid bytes and no errors.
        """
        sale, invoice = SalesService.create_sale(
            customer=self.customer,
            items_data=[{
                'product': self.wheat,
                'quantity_kg': Decimal('5.000'),
                'rate_per_kg': Decimal('38.00')
            }],
            amount_paid=Decimal('190.00')
        )
        pdf_bytes = generate_invoice_pdf(invoice.id)
        self.assertTrue(len(pdf_bytes) > 500)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_scenario_8_bilingual_language_switch(self):
        """
        SRS Test Scenario 7 & 8:
        Switch language to Marathi -> Navigation, labels and generated invoice support Marathi.
        """
        response = self.client.get(reverse('set_language', kwargs={'lang': 'mr'}), follow=True)
        self.assertEqual(self.client.session.get('lang'), 'mr')

        # Test dashboard renders in Marathi
        dash_response = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_response.status_code, 200)
        self.assertContains(dash_response, "डॅशबोर्ड")
        self.assertContains(dash_response, "दळण ऑर्डर्स")

    def test_pwa_manifest_and_service_worker(self):
        """
        Verify PWA manifest, service worker with root scope, and offline fallback endpoints.
        """
        # 1. Manifest
        manifest_res = self.client.get(reverse('pwa_manifest'))
        self.assertEqual(manifest_res.status_code, 200)
        self.assertIn("ChakkiMate", manifest_res.content.decode('utf-8'))
        self.assertIn("standalone", manifest_res.content.decode('utf-8'))

        # 2. Service Worker
        sw_res = self.client.get(reverse('pwa_service_worker'))
        self.assertEqual(sw_res.status_code, 200)
        self.assertEqual(sw_res.headers.get('Service-Worker-Allowed'), '/')
        self.assertIn('application/javascript', sw_res.headers.get('Content-Type'))
        self.assertIn("chakkimate", sw_res.content.decode('utf-8'))

        # 3. Offline Fallback
        offline_res = self.client.get(reverse('pwa_offline'))
        self.assertEqual(offline_res.status_code, 200)
        self.assertContains(offline_res, "इंटरनेट कनेक्शन उपलब्ध नाही")

    def test_grinding_order_validation_and_walkin_creation(self):
        """
        Verify validation prevents crash when customer missing,
        and auto-creates walk-in customer when details provided.
        """
        # 1. Missing customer should fail gracefully
        res = self.client.post(reverse('grinding_order_create'), {
            'grain_id': self.wheat.id,
            'input_kg': '15.000',
            'ownership_type': 'CUSTOMER'
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Please select an existing customer or enter walk-in customer details.")

        # 2. Walk-in customer should succeed and create record
        walkin_res = self.client.post(reverse('grinding_order_create'), {
            'quick_customer_name': 'Walkin Raju',
            'quick_customer_mobile': '9800000000',
            'grain_id': self.wheat.id,
            'input_kg': '12.000',
            'ownership_type': 'CUSTOMER',
            'is_paid': 'on',
            'payment_mode': 'CASH'
        }, follow=True)
        self.assertEqual(walkin_res.status_code, 200)
        new_cust = Customer.objects.filter(name='Walkin Raju').first()
        self.assertIsNotNone(new_cust)
        self.assertEqual(new_cust.customer_type, 'WALKIN')
        self.assertTrue(GrindingOrder.objects.filter(customer=new_cust, input_kg=Decimal('12.000')).exists())

    def test_sale_validation_and_stock_limit_enforcement(self):
        """
        Verify sale creation rejects empty customer and prevents over-selling stock.
        """
        # 1. Missing customer
        res = self.client.post(reverse('sale_create'), {
            'product_id[]': [self.wheat.id],
            'quantity_kg[]': ['5.000'],
            'rate_per_kg[]': ['38.00']
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Please select an existing customer or enter walk-in customer details.")

        # 2. Attempting to sell more than available stock (current_stock is 100 KG)
        res_over = self.client.post(reverse('sale_create'), {
            'customer_id': self.customer.id,
            'product_id[]': [self.wheat.id],
            'quantity_kg[]': ['9999.000'],
            'rate_per_kg[]': ['38.00']
        })
        self.assertEqual(res_over.status_code, 200)
        self.assertContains(res_over, "Insufficient stock")

    def test_purchase_validation_and_supplier_edit(self):
        """
        Verify purchase rejects missing supplier and supplier editing works.
        """
        # 1. Missing supplier
        res = self.client.post(reverse('purchase_create'), {
            'product_id[]': [self.wheat.id],
            'quantity_kg[]': ['50.000'],
            'rate_per_kg[]': ['30.00']
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Please select a supplier")

        # 2. Edit supplier
        edit_res = self.client.post(reverse('supplier_edit', kwargs={'supplier_id': self.supplier.id}), {
            'name': 'Kisan Agro Traders',
            'mobile': '9422009999',
            'address': 'New Yard Kolhapur',
            'notes': 'Preferred wheat partner'
        }, follow=True)
        self.assertEqual(edit_res.status_code, 200)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.name, 'Kisan Agro Traders')
        self.assertEqual(self.supplier.mobile, '9422009999')

    def test_product_deactivation_without_history_deletion(self):
        """
        SRS Section 4.5:
        Enable/disable items without deleting historical transaction data.
        """
        # Issue a sale first
        sale, invoice = SalesService.create_sale(
            customer=self.customer,
            items_data=[{
                'product': self.wheat,
                'quantity_kg': Decimal('5.000'),
                'rate_per_kg': Decimal('38.00')
            }]
        )

        # Deactivate product via edit
        res = self.client.post(reverse('product_edit', kwargs={'product_id': self.wheat.id}), {
            'name': self.wheat.name,
            'product_type': self.wheat.product_type,
            'purchase_rate': '30.00',
            'selling_rate': '38.00',
            'grinding_rate': '5.00',
            'low_stock_threshold': '20.000',
            # 'is_active' omitted so it becomes False
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.wheat.refresh_from_db()
        self.assertFalse(self.wheat.is_active)

        # Verify historical sale and invoice remain completely intact
        sale.refresh_from_db()
        self.assertEqual(sale.items.first().product_id, self.wheat.id)
        self.assertEqual(sale.total, Decimal('190.00'))

    def test_reports_financial_calculations(self):
        """
        SRS Section 4.13: Verify gross revenue, expenses, and net profit calculations.
        """
        # Create a sale of 380
        SalesService.create_sale(
            customer=self.customer,
            items_data=[{
                'product': self.wheat,
                'quantity_kg': Decimal('10.000'),
                'rate_per_kg': Decimal('38.00')
            }],
            amount_paid=Decimal('380.00')
        )

        # Create a grinding order of 100
        GrindingService.create_order(
            customer=self.customer,
            grain=self.wheat,
            input_kg=Decimal('20.000'),
            rate_per_kg=Decimal('5.00'),
            is_paid=True
        )

        # Record expense of 150
        from girni.models import Expense
        Expense.objects.create(
            category='ELECTRICITY',
            amount=Decimal('150.00'),
            expense_date=timezone.now().date(),
            description='Monthly bill'
        )

        # Check reports view
        rep_res = self.client.get(reverse('reports'))
        self.assertEqual(rep_res.status_code, 200)
        # Gross revenue = 380 + 100 = 480
        # Total expenses = 150
        # Net profit = 480 - 150 = 330
        self.assertEqual(rep_res.context['total_sales'], Decimal('380.00'))
        self.assertEqual(rep_res.context['total_grinding'], Decimal('100.00'))
        self.assertEqual(rep_res.context['total_expenses'], Decimal('150.00'))
        self.assertEqual(rep_res.context['gross_revenue'], Decimal('480.00'))
        self.assertEqual(rep_res.context['net_profit'], Decimal('330.00'))


