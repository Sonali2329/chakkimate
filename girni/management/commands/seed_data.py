# -*- coding: utf-8 -*-
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from girni.models import Customer, Supplier, Product, ShopSettings, StockMovement

class Command(BaseCommand):
    help = "Seeds initial demo data for ChakkiMate (चक्कीमेट)"

    def handle(self, *args, **options):
        self.stdout.write("Initializing ChakkiMate initial master data...")

        # 1. Superuser Owner
        if not User.objects.filter(username='owner').exists():
            User.objects.create_superuser('owner', 'owner@chakkimate.com', 'owner')
            self.stdout.write(self.style.SUCCESS("Created owner user (owner / owner)"))

        # 2. Shop Settings
        settings = ShopSettings.get_settings()
        settings.shop_name = "ChakkiMate Flour Mill"
        settings.shop_name_mr = "चक्कीमेट आधुनिक गिरणी व धान्य विक्री केंद्र"
        settings.owner_name = "आनंद पाटील (Anand Patil)"
        settings.mobile = "9822012345"
        settings.secondary_mobile = "9822054321"
        settings.address = "Near APMC Market Yard, Station Road, Kolhapur - 416001"
        settings.address_mr = "मार्केट यार्ड समोर, स्टेशन रोड, कोल्हापूर - ४१६००१"
        settings.default_language = "mr"
        settings.upi_id = "anand.girni@okaxis"
        settings.footer_message = "आमच्या गिरणीला भेट दिल्याबद्दल धन्यवाद! शुद्ध आणि ताजे पीठ हीच आमची ओळख!"
        settings.save()
        self.stdout.write(self.style.SUCCESS("Configured Shop Settings"))

        # 3. Grain & Flour Masters
        products_data = [
            # Raw Grains
            {
                'name': 'Lokwan Wheat',
                'name_mr': 'लोकवन गहू',
                'product_type': 'RAW_GRAIN',
                'purchase_rate': Decimal('32.00'),
                'selling_rate': Decimal('38.00'),
                'grinding_rate': Decimal('5.00'),
                'current_stock': Decimal('250.000'),
                'low_stock_threshold': Decimal('30.000'),
            },
            {
                'name': 'Sharbati Wheat',
                'name_mr': 'शरबती सीहोर गहू',
                'product_type': 'RAW_GRAIN',
                'purchase_rate': Decimal('42.00'),
                'selling_rate': Decimal('50.00'),
                'grinding_rate': Decimal('5.00'),
                'current_stock': Decimal('150.000'),
                'low_stock_threshold': Decimal('25.000'),
            },
            {
                'name': 'Maldandi Jowar',
                'name_mr': 'मालदांडी ज्वारी',
                'product_type': 'RAW_GRAIN',
                'purchase_rate': Decimal('45.00'),
                'selling_rate': Decimal('55.00'),
                'grinding_rate': Decimal('6.00'),
                'current_stock': Decimal('120.000'),
                'low_stock_threshold': Decimal('20.000'),
            },
            {
                'name': 'Desi Bajra',
                'name_mr': 'गावरान बाजरी',
                'product_type': 'RAW_GRAIN',
                'purchase_rate': Decimal('28.00'),
                'selling_rate': Decimal('35.00'),
                'grinding_rate': Decimal('5.00'),
                'current_stock': Decimal('90.000'),
                'low_stock_threshold': Decimal('20.000'),
            },
            {
                'name': 'Chana Dal / Gram',
                'name_mr': 'हरभरा डाळ',
                'product_type': 'RAW_GRAIN',
                'purchase_rate': Decimal('70.00'),
                'selling_rate': Decimal('85.00'),
                'grinding_rate': Decimal('7.00'),
                'current_stock': Decimal('80.000'),
                'low_stock_threshold': Decimal('15.000'),
            },
            {
                'name': 'Yellow Corn / Maize',
                'name_mr': 'पिवळी मका',
                'product_type': 'RAW_GRAIN',
                'purchase_rate': Decimal('24.00'),
                'selling_rate': Decimal('30.00'),
                'grinding_rate': Decimal('5.00'),
                'current_stock': Decimal('50.000'),
                'low_stock_threshold': Decimal('15.000'),
            },
            # Finished Flours
            {
                'name': 'Fresh Chakki Atta (Wheat Flour)',
                'name_mr': 'ताजे चक्की पीठ (गहू)',
                'product_type': 'FINISHED_FLOUR',
                'purchase_rate': Decimal('0.00'),
                'selling_rate': Decimal('42.00'),
                'grinding_rate': Decimal('0.00'),
                'current_stock': Decimal('85.000'),
                'low_stock_threshold': Decimal('20.000'),
            },
            {
                'name': 'Pure Besan (Gram Flour)',
                'name_mr': 'शुद्ध चणा बेसन पीठ',
                'product_type': 'FINISHED_FLOUR',
                'purchase_rate': Decimal('0.00'),
                'selling_rate': Decimal('95.00'),
                'grinding_rate': Decimal('0.00'),
                'current_stock': Decimal('45.000'),
                'low_stock_threshold': Decimal('10.000'),
            },
            {
                'name': 'Multigrain Atta',
                'name_mr': 'पौष्टिक मल्टीग्रेन पीठ',
                'product_type': 'FINISHED_FLOUR',
                'purchase_rate': Decimal('0.00'),
                'selling_rate': Decimal('65.00'),
                'grinding_rate': Decimal('0.00'),
                'current_stock': Decimal('30.000'),
                'low_stock_threshold': Decimal('10.000'),
            },
            {
                'name': 'Jowar Flour',
                'name_mr': 'ज्वारी पीठ',
                'product_type': 'FINISHED_FLOUR',
                'purchase_rate': Decimal('0.00'),
                'selling_rate': Decimal('60.00'),
                'grinding_rate': Decimal('0.00'),
                'current_stock': Decimal('40.000'),
                'low_stock_threshold': Decimal('10.000'),
            }
        ]

        for p_info in products_data:
            prod, created = Product.objects.get_or_create(
                name=p_info['name'],
                defaults=p_info
            )
            if created and prod.current_stock > Decimal('0.000'):
                StockMovement.objects.create(
                    product=prod,
                    stock_type=prod.product_type,
                    movement_type='ADJUSTMENT',
                    quantity_kg=prod.current_stock,
                    reference_type='OPENING_STOCK',
                    reference_id=f"INIT-{prod.id}",
                    balance_after_kg=prod.current_stock,
                    notes="Opening stock balance for mill startup"
                )

        self.stdout.write(self.style.SUCCESS("Created sample products & initial inventory"))

        # 4. Sample Customers
        customers_data = [
            {'name': 'रमेश मारुती शिंदे', 'mobile': '9822100001', 'address': 'शिवाजी पेठ, कोल्हापूर', 'customer_type': 'REGULAR'},
            {'name': 'सुनीता अशोक कांबळे', 'mobile': '9822100002', 'address': 'राजारामपुरी, गल्ली नं. ५', 'customer_type': 'REGULAR'},
            {'name': 'बाबासाहेब कदम', 'mobile': '9822100003', 'address': 'कसबा बावडा, कोल्हापूर', 'customer_type': 'REGULAR'},
            {'name': 'सचिन जाधव (किरकोळ ग्राहक)', 'mobile': '9822100004', 'address': 'बस स्टँड जवळ', 'customer_type': 'WALKIN'},
        ]
        for c in customers_data:
            Customer.objects.get_or_create(mobile=c['mobile'], defaults=c)

        # 5. Sample Suppliers
        suppliers_data = [
            {'name': 'शेतकरी कृषी विकास केंद्र', 'mobile': '9422000011', 'address': 'मार्केट यार्ड, दुकान क्र. १२', 'notes': 'गहू व ज्वारीचे मुख्य पुरवठादार'},
            {'name': 'महावीर ग्रेन एजन्सी', 'mobile': '9422000022', 'address': 'व्यापारी संकुल, कोल्हापूर', 'notes': 'हरभरा डाळ व मका सप्लायर'},
        ]
        for s in suppliers_data:
            Supplier.objects.get_or_create(mobile=s['mobile'], defaults=s)

        self.stdout.write(self.style.SUCCESS("Successfully seeded master data for ChakkiMate!"))
