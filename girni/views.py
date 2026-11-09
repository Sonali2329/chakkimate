# -*- coding: utf-8 -*-
from decimal import Decimal
import urllib.parse
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from datetime import timedelta
import os
from django.conf import settings

from .models import (
    Customer, Supplier, Product, StockMovement,
    Purchase, PurchaseItem, GrindingOrder,
    ProductionBatch, Sale, SaleItem, Invoice, Payment, Expense, ShopSettings
)
from .services import (
    InventoryService, PurchaseService, ProductionService,
    GrindingService, SalesService, BillingPaymentService
)
from .pdf_utils import generate_invoice_pdf
from .translations import TRANSLATIONS, get_text


def setup_initial_owner():
    """Ensure at least one owner superuser exists for easy out-of-the-box usage."""
    if not User.objects.filter(is_superuser=True).exists():
        User.objects.create_superuser(
            username='owner',
            email='owner@chakkimate.com',
            password='owner'
        )


def girni_login_view(request):
    setup_initial_owner()
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "Welcome back to ChakkiMate! / चक्कीमेट मध्ये आपले स्वागत आहे!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password. (Default is owner / owner)")

    return render(request, 'girni/login.html')


def girni_logout_view(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('girni_login')


def set_language_view(request, lang):
    """Toggle language between 'mr' (Marathi) and 'en' (English)."""
    if lang in ('mr', 'en'):
        request.session['lang'] = lang
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


# ==========================================
# DASHBOARD
# ==========================================
@login_required
def dashboard_view(request):
    today = timezone.now().date()
    
    # 1. Today's Grain & Flour Sales
    today_sales_qs = Sale.objects.filter(sale_date=today, status='COMPLETED')
    today_sales_total = today_sales_qs.aggregate(tot=Sum('total'))['tot'] or Decimal('0.00')

    # 2. Today's Grinding Orders & Charges
    today_grinding_qs = GrindingOrder.objects.filter(order_date__date=today).exclude(status='CANCELLED')
    today_grinding_count = today_grinding_qs.count()
    today_grinding_charges = today_grinding_qs.aggregate(tot=Sum('charges'))['tot'] or Decimal('0.00')

    # 3. Today's Total Collections (Payments received today)
    today_payments_total = Payment.objects.filter(payment_date=today).aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')

    # 4. Today's Expenses
    today_expenses_total = Expense.objects.filter(expense_date=today).aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')

    # 5. Pending Grinding Jobs (PENDING & IN_PROGRESS)
    pending_orders = GrindingOrder.objects.filter(status__in=['PENDING', 'IN_PROGRESS']).select_related('customer', 'grain')
    pending_orders_count = pending_orders.count()

    # 6. Customer Outstanding Dues
    total_outstanding = Invoice.objects.filter(status__in=['UNPAID', 'PARTIAL']).aggregate(tot=Sum('balance_due'))['tot'] or Decimal('0.00')

    # 7. Stock summaries
    raw_stock_total = Product.objects.filter(product_type='RAW_GRAIN', is_active=True).aggregate(tot=Sum('current_stock'))['tot'] or Decimal('0.000')
    flour_stock_total = Product.objects.filter(product_type='FINISHED_FLOUR', is_active=True).aggregate(tot=Sum('current_stock'))['tot'] or Decimal('0.000')
    low_stock_items = Product.objects.filter(is_active=True, current_stock__lte=F('low_stock_threshold'))

    # 8. Recent Activities
    recent_orders = GrindingOrder.objects.select_related('customer', 'grain').order_by('-order_date')[:6]
    recent_sales = Sale.objects.select_related('customer').order_by('-id')[:5]
    recent_movements = StockMovement.objects.select_related('product').order_by('-created_at')[:6]

    # 9. Past 7 days sales & grinding summary for chart/display
    weekly_labels = []
    weekly_sales_data = []
    weekly_grinding_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_label = day.strftime("%d %b")
        weekly_labels.append(day_label)
        
        s_val = Sale.objects.filter(sale_date=day, status='COMPLETED').aggregate(tot=Sum('total'))['tot'] or Decimal('0.00')
        g_val = GrindingOrder.objects.filter(order_date__date=day).exclude(status='CANCELLED').aggregate(tot=Sum('charges'))['tot'] or Decimal('0.00')
        
        weekly_sales_data.append(float(s_val))
        weekly_grinding_data.append(float(g_val))

    # 10. Vyapar Daybook (Today's Transactions Register)
    daybook_entries = []
    for g in GrindingOrder.objects.filter(order_date__date=today).select_related('customer', 'grain')[:8]:
        daybook_entries.append({
            'time': g.order_date,
            'type': 'GRINDING',
            'type_label': 'दळण मजुरी',
            'voucher_no': g.token_number or g.order_number,
            'party': g.customer.name,
            'amount': g.charges,
            'flow': 'INFLOW',
            'mode': g.payment_mode or 'CASH',
            'status': g.get_status_display()
        })
    for s in Sale.objects.filter(sale_date=today).select_related('customer')[:8]:
        daybook_entries.append({
            'time': timezone.now(),
            'type': 'SALE',
            'type_label': 'धान्य/पीठ विक्री',
            'voucher_no': s.sale_number,
            'party': s.customer.name,
            'amount': s.total,
            'flow': 'INFLOW',
            'mode': s.payment_mode or 'CASH',
            'status': 'पूर्ण'
        })
    for p in Payment.objects.filter(payment_date=today).select_related('customer')[:8]:
        daybook_entries.append({
            'time': timezone.now(),
            'type': 'PAYMENT',
            'type_label': 'रक्कम जमा (Inflow)',
            'voucher_no': f"PAY-{p.id}",
            'party': p.customer.name if p.customer else 'ग्राहक',
            'amount': p.amount,
            'flow': 'INFLOW',
            'mode': p.payment_mode,
            'status': 'जमा'
        })
    for e in Expense.objects.filter(expense_date=today)[:8]:
        daybook_entries.append({
            'time': timezone.now(),
            'type': 'EXPENSE',
            'type_label': 'खर्च (Outflow)',
            'voucher_no': f"EXP-{e.id}",
            'party': e.get_category_display(),
            'amount': e.amount,
            'flow': 'OUTFLOW',
            'mode': e.payment_mode,
            'status': 'खर्च'
        })
    daybook_entries.sort(key=lambda x: x['time'], reverse=True)

    context = {
        'today': today,
        'today_sales_total': today_sales_total,
        'today_grinding_count': today_grinding_count,
        'today_grinding_charges': today_grinding_charges,
        'today_payments_total': today_payments_total,
        'today_expenses_total': today_expenses_total,
        'pending_orders': pending_orders[:6],
        'pending_orders_count': pending_orders_count,
        'total_outstanding': total_outstanding,
        'raw_stock_total': raw_stock_total,
        'flour_stock_total': flour_stock_total,
        'low_stock_items': low_stock_items,
        'recent_orders': recent_orders,
        'recent_sales': recent_sales,
        'recent_movements': recent_movements,
        'weekly_labels': weekly_labels,
        'weekly_sales_data': weekly_sales_data,
        'weekly_grinding_data': weekly_grinding_data,
        'daybook_entries': daybook_entries[:12],
    }
    return render(request, 'girni/dashboard.html', context)


# ==========================================
# CUSTOMER MANAGEMENT
# ==========================================
@login_required
def customer_list_view(request):
    query = request.GET.get('q', '').strip()
    cust_type = request.GET.get('type', '')

    qs = Customer.objects.filter(is_active=True)
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(mobile__icontains=query) | Q(address__icontains=query))
    if cust_type:
        qs = qs.filter(customer_type=cust_type)

    return render(request, 'girni/customer_list.html', {'customers': qs, 'query': query, 'cust_type': cust_type})


@login_required
def customer_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        customer_type = request.POST.get('customer_type', 'REGULAR')

        if not name or not mobile:
            messages.error(request, "Name and Mobile number are required.")
        else:
            cust = Customer.objects.create(
                name=name,
                mobile=mobile,
                address=address,
                customer_type=customer_type
            )
            # If AJAX request from quick-customer modal
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax'):
                return JsonResponse({'status': 'ok', 'id': cust.id, 'name': cust.name, 'mobile': cust.mobile})
            
            messages.success(request, f"Customer '{cust.name}' added successfully.")
            return redirect('customer_detail', customer_id=cust.id)

    return render(request, 'girni/customer_form.html', {'action': 'Create'})


@login_required
def customer_edit_view(request, customer_id):
    cust = get_object_or_404(Customer, id=customer_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        if not name or not mobile:
            messages.error(request, "Name and Mobile number are required.")
        else:
            cust.name = name
            cust.mobile = mobile
            cust.address = request.POST.get('address', cust.address).strip()
            cust.customer_type = request.POST.get('customer_type', cust.customer_type)
            cust.save()
            messages.success(request, f"Customer '{cust.name}' updated successfully.")
            return redirect('customer_detail', customer_id=cust.id)

    return render(request, 'girni/customer_form.html', {'customer': cust, 'action': 'Edit'})


@login_required
def customer_detail_view(request, customer_id):
    cust = get_object_or_404(Customer, id=customer_id)
    grinding_orders = cust.grinding_orders.all()[:10]
    sales = cust.sales.all()[:10]
    invoices = cust.invoices.all()[:10]
    payments = cust.payments.all()[:10]
    
    return render(request, 'girni/customer_detail.html', {
        'customer': cust,
        'grinding_orders': grinding_orders,
        'sales': sales,
        'invoices': invoices,
        'payments': payments,
    })


# ==========================================
# SUPPLIER MANAGEMENT
# ==========================================
@login_required
def supplier_list_view(request):
    suppliers = Supplier.objects.filter(is_active=True)
    return render(request, 'girni/supplier_list.html', {'suppliers': suppliers})


@login_required
def supplier_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not name or not mobile:
            messages.error(request, "Name and Mobile number are required.")
        else:
            sup = Supplier.objects.create(name=name, mobile=mobile, address=address, notes=notes)
            messages.success(request, f"Supplier '{sup.name}' added successfully.")
            return redirect('supplier_list')

    return render(request, 'girni/supplier_form.html', {'action': 'Create'})


@login_required
def supplier_detail_view(request, supplier_id):
    sup = get_object_or_404(Supplier, id=supplier_id)
    purchases = sup.purchases.all()
    return render(request, 'girni/supplier_detail.html', {'supplier': sup, 'purchases': purchases})


@login_required
def supplier_edit_view(request, supplier_id):
    sup = get_object_or_404(Supplier, id=supplier_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        notes = request.POST.get('notes', '').strip()
        if not name or not mobile:
            messages.error(request, "Name and Mobile number are required.")
        else:
            sup.name = name
            sup.mobile = mobile
            sup.address = address
            sup.notes = notes
            sup.save()
            messages.success(request, f"Supplier '{sup.name}' updated successfully.")
            return redirect('supplier_detail', supplier_id=sup.id)

    return render(request, 'girni/supplier_form.html', {'supplier': sup, 'action': 'Edit'})


# ==========================================
# GRAIN & PRODUCT MASTER
# ==========================================
@login_required
def product_list_view(request):
    p_type = request.GET.get('type', '')
    products = Product.objects.filter(is_active=True)
    if p_type:
        products = products.filter(product_type=p_type)

    return render(request, 'girni/product_list.html', {'products': products, 'selected_type': p_type})


@login_required
def product_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_mr = request.POST.get('name_mr', '').strip()
        product_type = request.POST.get('product_type', 'RAW_GRAIN')
        unit = request.POST.get('unit', 'KG').strip() or 'KG'
        purchase_rate = request.POST.get('purchase_rate', '0.00')
        selling_rate = request.POST.get('selling_rate', '0.00')
        grinding_rate = request.POST.get('grinding_rate', '5.00')
        current_stock = request.POST.get('current_stock', '0.000')
        low_stock_threshold = request.POST.get('low_stock_threshold', '20.000')

        if not name:
            messages.error(request, "Product name is required.")
        else:
            prod = Product.objects.create(
                name=name,
                name_mr=name_mr,
                product_type=product_type,
                unit=unit,
                purchase_rate=Decimal(str(purchase_rate or 0)),
                selling_rate=Decimal(str(selling_rate or 0)),
                grinding_rate=Decimal(str(grinding_rate or 0)),
                current_stock=Decimal(str(current_stock or 0)),
                low_stock_threshold=Decimal(str(low_stock_threshold or 20))
            )
            # If opening stock > 0, record in ledger
            if prod.current_stock > Decimal('0.000'):
                StockMovement.objects.create(
                    product=prod,
                    stock_type=prod.product_type,
                    movement_type='ADJUSTMENT',
                    quantity_kg=prod.current_stock,
                    reference_type='OPENING_STOCK',
                    reference_id=f"INIT-{prod.id}",
                    balance_after_kg=prod.current_stock,
                    notes="Initial opening stock recorded at item creation"
                )

            messages.success(request, f"Product '{prod.display_name}' created successfully.")
            return redirect('product_list')

    return render(request, 'girni/product_form.html', {'action': 'Create'})


@login_required
def product_edit_view(request, product_id):
    prod = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "Product name is required.")
        else:
            prod.name = name
            prod.name_mr = request.POST.get('name_mr', '').strip()
            prod.product_type = request.POST.get('product_type', prod.product_type)
            prod.purchase_rate = Decimal(request.POST.get('purchase_rate', prod.purchase_rate) or 0)
            prod.selling_rate = Decimal(request.POST.get('selling_rate', prod.selling_rate) or 0)
            prod.grinding_rate = Decimal(request.POST.get('grinding_rate', prod.grinding_rate) or 0)
            prod.low_stock_threshold = Decimal(request.POST.get('low_stock_threshold', prod.low_stock_threshold) or 20)
            prod.is_active = request.POST.get('is_active') == 'on'
            prod.save()
            messages.success(request, f"Product '{prod.display_name}' updated successfully.")
            return redirect('product_list')

    return render(request, 'girni/product_form.html', {'product': prod, 'action': 'Edit'})


# ==========================================
# PURCHASE MANAGEMENT
# ==========================================
@login_required
def purchase_list_view(request):
    purchases = Purchase.objects.select_related('supplier').all()
    return render(request, 'girni/purchase_list.html', {'purchases': purchases})


@login_required
def purchase_create_view(request):
    suppliers = Supplier.objects.filter(is_active=True)
    raw_products = Product.objects.filter(product_type='RAW_GRAIN', is_active=True)

    if request.method == 'POST':
        supplier_id = request.POST.get('supplier_id')
        purchase_date = request.POST.get('purchase_date') or timezone.now().date()
        discount = request.POST.get('discount', '0')
        other_charges = request.POST.get('other_charges', '0')
        amount_paid = request.POST.get('amount_paid', '0')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        notes = request.POST.get('notes', '')

        if not supplier_id:
            messages.error(request, "Please select a supplier. / कृपया पुरवठादार निवडा.")
            return render(request, 'girni/purchase_form.html', {
                'suppliers': suppliers,
                'raw_products': raw_products,
                'today': timezone.now().date()
            })
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # Parse dynamic item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity_kg[]')
        rates = request.POST.getlist('rate_per_kg[]')

        items_data = []
        for pid, qty, rate in zip(product_ids, quantities, rates):
            if pid and qty and rate and float(qty) > 0:
                prod = Product.objects.get(id=pid)
                items_data.append({
                    'product': prod,
                    'quantity_kg': Decimal(qty),
                    'rate_per_kg': Decimal(rate)
                })

        if not items_data:
            messages.error(request, "Please add at least one purchase grain line item.")
        else:
            try:
                purchase = PurchaseService.create_purchase(
                    supplier=supplier,
                    purchase_date=purchase_date,
                    items_data=items_data,
                    discount=discount,
                    other_charges=other_charges,
                    amount_paid=amount_paid,
                    payment_mode=payment_mode,
                    notes=notes
                )
                messages.success(request, f"Purchase '{purchase.purchase_number}' posted successfully! Stock updated.")
                return redirect('purchase_detail', purchase_id=purchase.id)
            except Exception as e:
                messages.error(request, f"Error saving purchase: {str(e)}")

    return render(request, 'girni/purchase_form.html', {
        'suppliers': suppliers,
        'raw_products': raw_products,
        'today': timezone.now().date()
    })


@login_required
def purchase_detail_view(request, purchase_id):
    purchase = get_object_or_404(Purchase.objects.select_related('supplier'), id=purchase_id)
    return render(request, 'girni/purchase_detail.html', {'purchase': purchase})


# ==========================================
# INVENTORY & STOCK LEDGER
# ==========================================
@login_required
def stock_summary_view(request):
    raw_grains = Product.objects.filter(product_type='RAW_GRAIN', is_active=True)
    flour_products = Product.objects.filter(product_type='FINISHED_FLOUR', is_active=True)
    return render(request, 'girni/stock_summary.html', {
        'raw_grains': raw_grains,
        'flour_products': flour_products
    })


@login_required
def stock_ledger_view(request):
    product_id = request.GET.get('product_id')
    movement_type = request.GET.get('movement_type')

    movements = StockMovement.objects.select_related('product').all()
    if product_id:
        movements = movements.filter(product_id=product_id)
    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    all_products = Product.objects.filter(is_active=True)
    return render(request, 'girni/stock_ledger.html', {
        'movements': movements[:100],
        'products': all_products,
        'selected_product': product_id,
        'selected_movement': movement_type
    })


@login_required
def stock_adjust_view(request):
    products = Product.objects.filter(is_active=True)
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        new_stock = request.POST.get('new_stock_kg', '0')
        reason = request.POST.get('reason', '').strip()
        notes = request.POST.get('notes', '').strip()

        prod = get_object_or_404(Product, id=product_id)
        if not reason:
            messages.error(request, "Reason for stock adjustment is required.")
        else:
            try:
                InventoryService.adjust_stock(prod, Decimal(new_stock), reason, notes)
                messages.success(request, f"Stock for {prod.display_name} adjusted to {new_stock} KG.")
                return redirect('stock_summary')
            except Exception as e:
                messages.error(request, f"Adjustment failed: {str(e)}")

    return render(request, 'girni/stock_adjust.html', {'products': products})


# ==========================================
# CUSTOMER GRINDING ORDERS
# ==========================================
@login_required
def grinding_order_list_view(request):
    status_filter = request.GET.get('status', '')
    orders = GrindingOrder.objects.select_related('customer', 'grain').all()
    if status_filter:
        orders = orders.filter(status=status_filter)

    return render(request, 'girni/grinding_list.html', {
        'orders': orders,
        'status_filter': status_filter
    })


@login_required
def grinding_order_create_view(request):
    customers = Customer.objects.filter(is_active=True)
    raw_products = Product.objects.filter(product_type='RAW_GRAIN', is_active=True)

    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        grain_id = request.POST.get('grain_id')
        ownership_type = request.POST.get('ownership_type', 'CUSTOMER')
        input_kg = request.POST.get('input_kg', '0')
        rate_per_kg = request.POST.get('rate_per_kg', '')
        is_paid = request.POST.get('is_paid') == 'on'
        payment_mode = request.POST.get('payment_mode', 'CASH')
        expected_delivery = request.POST.get('expected_delivery') or None
        notes = request.POST.get('notes', '')

        # Validation checks
        if not customer_id and not request.POST.get('quick_customer_name'):
            messages.error(request, "Please select an existing customer or enter walk-in customer details.")
            return render(request, 'girni/grinding_form.html', {
                'customers': customers,
                'raw_products': raw_products,
                'default_expected_delivery': (timezone.now() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
            })

        if not grain_id:
            messages.error(request, "Please select grain type.")
            return render(request, 'girni/grinding_form.html', {
                'customers': customers,
                'raw_products': raw_products,
                'default_expected_delivery': (timezone.now() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
            })

        try:
            inp_val = Decimal(str(input_kg or 0))
            if inp_val <= Decimal('0.000'):
                raise ValueError("Weight must be greater than zero.")
        except Exception:
            messages.error(request, "Please enter a valid grain weight (KG) greater than zero.")
            return render(request, 'girni/grinding_form.html', {
                'customers': customers,
                'raw_products': raw_products,
                'default_expected_delivery': (timezone.now() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
            })

        # Walk-in customer instant create
        if not customer_id and request.POST.get('quick_customer_name'):
            cust_name = request.POST.get('quick_customer_name').strip()
            cust_mobile = request.POST.get('quick_customer_mobile', '0000000000').strip()
            customer = Customer.objects.create(
                name=cust_name,
                mobile=cust_mobile,
                customer_type='WALKIN'
            )
        else:
            customer = get_object_or_404(Customer, id=customer_id)

        grain = get_object_or_404(Product, id=grain_id)

        try:
            rate_dec = Decimal(rate_per_kg) if rate_per_kg else None
            order = GrindingService.create_order(
                customer=customer,
                grain=grain,
                input_kg=Decimal(input_kg),
                rate_per_kg=rate_dec,
                ownership_type=ownership_type,
                expected_delivery=expected_delivery,
                notes=notes,
                is_paid=is_paid,
                payment_mode=payment_mode
            )
            messages.success(request, f"Grinding Order {order.order_number} ({order.token_number}) booked successfully!")
            return redirect('grinding_order_detail', order_id=order.id)
        except Exception as e:
            messages.error(request, f"Error booking order: {str(e)}")

    return render(request, 'girni/grinding_form.html', {
        'customers': customers,
        'raw_products': raw_products,
        'default_expected_delivery': (timezone.now() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    })


@login_required
def grinding_order_detail_view(request, order_id):
    order = get_object_or_404(
        GrindingOrder.objects.select_related('customer', 'grain', 'invoice'),
        id=order_id
    )
    return render(request, 'girni/grinding_detail.html', {'order': order})


@login_required
def grinding_order_status_update_view(request, order_id):
    order = get_object_or_404(GrindingOrder, id=order_id)
    new_status = request.POST.get('status')
    output_kg = request.POST.get('output_kg')
    wastage_kg = request.POST.get('wastage_kg')

    if new_status in dict(GrindingOrder.STATUS_CHOICES):
        order.status = new_status
        if new_status == 'DELIVERED':
            order.delivered_at = timezone.now()
        if output_kg:
            order.output_kg = Decimal(output_kg)
        if wastage_kg:
            order.wastage_kg = Decimal(wastage_kg)
        order.save()
        messages.success(request, f"Order status updated to {order.get_status_display()}.")

    return redirect('grinding_order_detail', order_id=order.id)


# ==========================================
# OWN PRODUCTION / FLOUR PROCESSING
# ==========================================
@login_required
def production_list_view(request):
    batches = ProductionBatch.objects.select_related('raw_product', 'flour_product').all()
    return render(request, 'girni/production_list.html', {'batches': batches})


@login_required
def production_create_view(request):
    raw_products = Product.objects.filter(product_type='RAW_GRAIN', is_active=True)
    flour_products = Product.objects.filter(product_type='FINISHED_FLOUR', is_active=True)

    if request.method == 'POST':
        raw_id = request.POST.get('raw_product_id')
        flour_id = request.POST.get('flour_product_id')
        input_kg = request.POST.get('input_kg', '0')
        output_kg = request.POST.get('output_kg', '0')
        wastage_kg = request.POST.get('wastage_kg', '0')
        batch_date = request.POST.get('batch_date') or timezone.now().date()
        notes = request.POST.get('notes', '')

        if not raw_id or not flour_id:
            messages.error(request, "Please select both raw grain and finished flour.")
            return render(request, 'girni/production_form.html', {
                'raw_products': raw_products,
                'flour_products': flour_products,
                'today': timezone.now().date()
            })

        if raw_id == flour_id:
            messages.error(request, "Raw grain and finished flour cannot be the same item.")
            return render(request, 'girni/production_form.html', {
                'raw_products': raw_products,
                'flour_products': flour_products,
                'today': timezone.now().date()
            })

        try:
            inp_val = Decimal(str(input_kg or 0))
            out_val = Decimal(str(output_kg or 0))
            if inp_val <= Decimal('0.000') or out_val <= Decimal('0.000'):
                raise ValueError()
        except Exception:
            messages.error(request, "Input and Output weights must be valid numbers greater than zero.")
            return render(request, 'girni/production_form.html', {
                'raw_products': raw_products,
                'flour_products': flour_products,
                'today': timezone.now().date()
            })

        raw_prod = get_object_or_404(Product, id=raw_id)
        flour_prod = get_object_or_404(Product, id=flour_id)

        try:
            batch = ProductionService.process_production_batch(
                raw_product=raw_prod,
                flour_product=flour_prod,
                input_kg=Decimal(input_kg),
                output_kg=Decimal(output_kg),
                wastage_kg=Decimal(wastage_kg),
                batch_date=batch_date,
                notes=notes
            )
            messages.success(
                request,
                f"Production Batch #{batch.batch_number} recorded! "
                f"Yield: {batch.yield_percentage}% ({flour_prod.name} stock increased by {output_kg} KG)."
            )
            return redirect('production_list')
        except Exception as e:
            messages.error(request, f"Production processing error: {str(e)}")

    return render(request, 'girni/production_form.html', {
        'raw_products': raw_products,
        'flour_products': flour_products,
        'today': timezone.now().date()
    })


# ==========================================
# SALES & BILLING
# ==========================================
@login_required
def sale_list_view(request):
    sales = Sale.objects.select_related('customer').prefetch_related('items__product').all()
    return render(request, 'girni/sale_list.html', {'sales': sales})


@login_required
def sale_create_view(request):
    customers = Customer.objects.filter(is_active=True)
    all_products = Product.objects.filter(is_active=True)

    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        discount = request.POST.get('discount', '0')
        amount_paid = request.POST.get('amount_paid', '0')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        notes = request.POST.get('notes', '')

        if not customer_id and not request.POST.get('quick_customer_name'):
            messages.error(request, "Please select an existing customer or enter walk-in customer details.")
            return render(request, 'girni/sale_form.html', {
                'customers': customers,
                'products': all_products,
                'today': timezone.now().date()
            })

        if not customer_id and request.POST.get('quick_customer_name'):
            cust_name = request.POST.get('quick_customer_name').strip()
            cust_mobile = request.POST.get('quick_customer_mobile', '0000000000').strip()
            customer = Customer.objects.create(name=cust_name, mobile=cust_mobile, customer_type='WALKIN')
        else:
            customer = get_object_or_404(Customer, id=customer_id)

        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity_kg[]')
        rates = request.POST.getlist('rate_per_kg[]')

        items_data = []
        for pid, qty, rate in zip(product_ids, quantities, rates):
            if pid and qty and rate:
                try:
                    qty_dec = Decimal(str(qty))
                    rate_dec = Decimal(str(rate))
                    if qty_dec > Decimal('0.000'):
                        prod = Product.objects.get(id=pid)
                        items_data.append({
                            'product': prod,
                            'quantity_kg': qty_dec,
                            'rate_per_kg': rate_dec
                        })
                except Exception:
                    pass

        if not items_data:
            messages.error(request, "Please add at least one grain or flour item.")
        else:
            try:
                sale, invoice = SalesService.create_sale(
                    customer=customer,
                    items_data=items_data,
                    discount=discount,
                    amount_paid=amount_paid,
                    payment_mode=payment_mode,
                    notes=notes
                )
                messages.success(request, f"Sale #{sale.sale_number} completed and Invoice #{invoice.invoice_number} created!")
                return redirect('invoice_detail', invoice_id=invoice.id)
            except Exception as e:
                messages.error(request, f"Error completing sale: {str(e)}")

    return render(request, 'girni/sale_form.html', {
        'customers': customers,
        'products': all_products,
        'today': timezone.now().date()
    })


# ==========================================
# INVOICES & PAYMENTS
# ==========================================
@login_required
def invoice_list_view(request):
    status_filter = request.GET.get('status', '')
    invoices = Invoice.objects.select_related('customer', 'sale', 'grinding_order').all()
    if status_filter:
        invoices = invoices.filter(status=status_filter)

    return render(request, 'girni/invoice_list.html', {
        'invoices': invoices,
        'status_filter': status_filter
    })


@login_required
def invoice_detail_view(request, invoice_id):
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'sale', 'grinding_order').prefetch_related('payments'),
        id=invoice_id
    )
    settings = ShopSettings.get_settings()
    
    # Generate WhatsApp message link
    msg = f"*{settings.shop_name}* (गिरणी बिल)\n"
    msg += f"बिल क्र.: {invoice.invoice_number}\n"
    msg += f"ग्राहक: {invoice.customer.name}\n"
    msg += f"तारीख: {invoice.invoice_date.strftime('%d-%m-%Y')}\n"
    msg += f"एकूण रक्कम: ₹{invoice.total:.2f}\n"
    msg += f"जमा रक्कम: ₹{invoice.amount_paid:.2f}\n"
    msg += f"बाकी रक्कम: ₹{invoice.balance_due:.2f}\n"
    if settings.upi_id:
        msg += f"UPI पेमेंट: {settings.upi_id}\n"
    msg += f"{settings.footer_message}"
    
    encoded_msg = urllib.parse.quote(msg)
    mobile_clean = invoice.customer.mobile.replace("+", "").replace("-", "").replace(" ", "")
    if len(mobile_clean) == 10:
        mobile_clean = "91" + mobile_clean
    whatsapp_url = f"https://wa.me/{mobile_clean}?text={encoded_msg}"

    return render(request, 'girni/invoice_detail.html', {
        'invoice': invoice,
        'whatsapp_url': whatsapp_url,
        'raw_message': msg
    })


@login_required
def invoice_pdf_view(request, invoice_id):
    pdf_bytes = generate_invoice_pdf(invoice_id)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Invoice_{invoice_id}.pdf"'
    return response


@login_required
def record_payment_view(request):
    if request.method == 'POST':
        invoice_id = request.POST.get('invoice_id')
        amount = request.POST.get('amount')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        reference_number = request.POST.get('reference_number', '')
        notes = request.POST.get('notes', '')

        if not invoice_id:
            messages.error(request, "Invoice ID is missing.")
            return redirect('invoice_list')

        invoice = get_object_or_404(Invoice, id=invoice_id)
        if not amount:
            messages.error(request, "Please enter a valid payment amount.")
            return redirect('invoice_detail', invoice_id=invoice.id)

        try:
            payment = BillingPaymentService.record_payment(
                invoice=invoice,
                amount=amount,
                payment_mode=payment_mode,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"Payment of ₹{payment.amount} recorded for Invoice {invoice.invoice_number}.")
        except Exception as e:
            messages.error(request, f"Payment error: {str(e)}")

        return redirect('invoice_detail', invoice_id=invoice.id)

    return redirect('invoice_list')


@login_required
def payment_list_view(request):
    payments = Payment.objects.select_related('customer', 'invoice').all()
    return render(request, 'girni/payment_list.html', {'payments': payments})


# ==========================================
# EXPENSES
# ==========================================
@login_required
def expense_list_view(request):
    expenses = Expense.objects.all()
    total_expense = expenses.aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')
    return render(request, 'girni/expense_list.html', {
        'expenses': expenses,
        'total_expense': total_expense
    })


@login_required
def expense_create_view(request):
    if request.method == 'POST':
        category = request.POST.get('category')
        amount = request.POST.get('amount')
        expense_date = request.POST.get('expense_date') or timezone.now().date()
        payment_mode = request.POST.get('payment_mode', 'CASH')
        description = request.POST.get('description', '')
        receipt = request.FILES.get('receipt_file')

        if not amount or float(amount) <= 0:
            messages.error(request, "Valid expense amount is required.")
        else:
            exp = Expense.objects.create(
                category=category,
                amount=Decimal(amount),
                expense_date=expense_date,
                payment_mode=payment_mode,
                description=description,
                receipt_file=receipt
            )
            messages.success(request, f"Expense of ₹{exp.amount} recorded successfully.")
            return redirect('expense_list')

    return render(request, 'girni/expense_form.html', {
        'today': timezone.now().date(),
        'categories': Expense.CATEGORY_CHOICES,
        'payment_modes': Expense.PAYMENT_MODE_CHOICES
    })


# ==========================================
# COMPREHENSIVE REPORTS (SRS 4.13)
# ==========================================
@login_required
def reports_view(request):
    today = timezone.now().date()
    from_date_str = request.GET.get('from_date', (today - timedelta(days=30)).strftime("%Y-%m-%d"))
    to_date_str = request.GET.get('to_date', today.strftime("%Y-%m-%d"))

    # Sales in range
    sales_qs = Sale.objects.filter(sale_date__gte=from_date_str, sale_date__lte=to_date_str, status='COMPLETED')
    total_sales = sales_qs.aggregate(tot=Sum('total'))['tot'] or Decimal('0.00')

    # Grinding charges in range
    grinding_qs = GrindingOrder.objects.filter(order_date__date__gte=from_date_str, order_date__date__lte=to_date_str).exclude(status='CANCELLED')
    total_grinding = grinding_qs.aggregate(tot=Sum('charges'))['tot'] or Decimal('0.00')
    total_grinding_orders = grinding_qs.count()

    # Expenses in range
    expense_qs = Expense.objects.filter(expense_date__gte=from_date_str, expense_date__lte=to_date_str)
    total_expenses = expense_qs.aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')

    # Net income calculation
    gross_revenue = total_sales + total_grinding
    net_profit = gross_revenue - total_expenses

    # Item-wise sales breakdown
    item_sales = SaleItem.objects.filter(
        sale__sale_date__gte=from_date_str,
        sale__sale_date__lte=to_date_str,
        sale__status='COMPLETED'
    ).values('product__name', 'product__name_mr', 'product__product_type').annotate(
        total_kg=Sum('quantity_kg'),
        total_revenue=Sum('line_total')
    ).order_by('-total_revenue')

    # Production & Yield summary
    batches = ProductionBatch.objects.filter(batch_date__gte=from_date_str, batch_date__lte=to_date_str)

    # Customer outstanding balances
    top_debtors = Customer.objects.filter(
        invoices__status__in=['UNPAID', 'PARTIAL']
    ).annotate(
        due=Sum('invoices__balance_due')
    ).filter(due__gt=0).order_by('-due')[:15]

    return render(request, 'girni/reports.html', {
        'from_date': from_date_str,
        'to_date': to_date_str,
        'total_sales': total_sales,
        'total_grinding': total_grinding,
        'total_grinding_orders': total_grinding_orders,
        'total_expenses': total_expenses,
        'gross_revenue': gross_revenue,
        'net_profit': net_profit,
        'item_sales': item_sales,
        'batches': batches,
        'top_debtors': top_debtors
    })


# ==========================================
# SHOP SETTINGS & LANGUAGE
# ==========================================
@login_required
def shop_settings_view(request):
    settings = ShopSettings.get_settings()
    if request.method == 'POST':
        settings.shop_name = request.POST.get('shop_name', settings.shop_name).strip()
        settings.shop_name_mr = request.POST.get('shop_name_mr', settings.shop_name_mr).strip()
        settings.owner_name = request.POST.get('owner_name', settings.owner_name).strip()
        settings.mobile = request.POST.get('mobile', settings.mobile).strip()
        settings.secondary_mobile = request.POST.get('secondary_mobile', '').strip()
        settings.address = request.POST.get('address', settings.address).strip()
        settings.address_mr = request.POST.get('address_mr', settings.address_mr).strip()
        settings.default_language = request.POST.get('default_language', 'mr')
        settings.currency_symbol = request.POST.get('currency_symbol', '₹').strip()
        settings.gst_enabled = request.POST.get('gst_enabled') == 'on'
        settings.gst_number = request.POST.get('gst_number', '').strip()
        settings.upi_id = request.POST.get('upi_id', '').strip()
        settings.footer_message = request.POST.get('footer_message', settings.footer_message).strip()
        settings.save()

        # Update current session language if default changed
        request.session['lang'] = settings.default_language
        messages.success(request, "Shop settings saved successfully! / दुकानाची माहिती जतन झाली!")
        return redirect('shop_settings')

    return render(request, 'girni/settings.html', {'settings': settings})


# ==========================================
# PWA (Progressive Web App) ENDPOINTS
# ==========================================
def offline_view(request):
    """Fallback offline page served by the service worker."""
    return render(request, 'girni/offline.html')


def service_worker_view(request):
    """Serves the service worker with root scope permissions."""
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'service-worker.js')
    with open(sw_path, 'r', encoding='utf-8') as f:
        content = f.read()
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


def manifest_view(request):
    """Serves the PWA web app manifest."""
    mf_path = os.path.join(settings.BASE_DIR, 'static', 'manifest.json')
    with open(mf_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/manifest+json')

