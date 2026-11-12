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
import re
from datetime import datetime, timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash

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

def clean_mobile(raw_mobile):
    """
    Cleans and validates Indian phone numbers.
    Accepts 10 digits starting with [6-9]. Strips +91, 0, spaces, dashes.
    Returns 10-digit string if valid, else None.
    """
    if not raw_mobile:
        return None
    digits = re.sub(r'\D', '', str(raw_mobile))
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in '6789':
        return digits
    return None

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
            messages.success(request, "चक्कीमेट मध्ये आपले स्वागत आहे! / Welcome to ChakkiMate!")
            next_url = request.GET.get('next') or 'dashboard'
            return redirect(next_url)
        else:
            messages.error(request, "वापरकर्ता नाव किंवा पासवर्ड चुकीचा आहे. कृपया पुन्हा तपासा.")

    return render(request, 'girni/login.html')

def girni_logout_view(request):
    logout(request)
    messages.info(request, "आपण यशस्वीपणे लॉगआउट झाला आहात.")
    return redirect('girni_login')

@login_required
def password_change_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "तुमचा पासवर्ड यशस्वीपणे बदलण्यात आला आहे! / Password changed successfully!")
            return redirect('shop_settings')
        else:
            messages.error(request, "पासवर्ड बदलताना त्रुटी आढळली. कृपया खालील सूचना तपासा.")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'girni/password_change.html', {'form': form})
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

    sales_chart_has_data = any(v > 0 for v in weekly_sales_data) or any(v > 0 for v in weekly_grinding_data)

    # 10. Vyapar Daybook (Today's Transactions Register) - Real Money In/Out & True Modes (B20)
    daybook_entries = []
    
    # 10a. Grinding orders (exclude cancelled, identify paid vs unpaid credit)
    for g in GrindingOrder.objects.filter(order_date__date=today).exclude(status='CANCELLED').select_related('customer', 'grain')[:10]:
        g_flow = 'INFLOW' if g.is_paid else 'CREDIT'
        g_status = 'पूर्ण (जमा)' if g.is_paid else 'बाकी (Unpaid)'
        g_mode = (g.payment_mode or 'CASH') if g.is_paid else 'उधार (बाकी)'
        daybook_entries.append({
            'time': g.order_date,
            'type': 'GRINDING',
            'type_label': 'दळण मजुरी',
            'voucher_no': g.token_number or g.order_number,
            'party': g.customer.name,
            'amount': g.charges,
            'flow': g_flow,
            'mode': g_mode,
            'status': g_status
        })

    # 10b. Sales (check true invoice status: VOID, Full Paid, Partial, Credit)
    for s in Sale.objects.filter(sale_date=today).select_related('customer', 'invoice')[:10]:
        mode = 'रोख (CASH)'
        flow = 'INFLOW'
        status_txt = 'पूर्ण (Paid)'
        amt = s.total

        if hasattr(s, 'invoice') and s.invoice:
            if s.invoice.status == 'VOID':
                flow = 'VOID'
                mode = 'रद्द (Void)'
                status_txt = 'रद्द (VOID)'
                amt = Decimal('0.00')
            elif s.invoice.balance_due == Decimal('0.00'):
                p_first = s.invoice.payments.first()
                mode = p_first.get_payment_mode_display() if p_first else 'रोख (CASH)'
                status_txt = 'पूर्ण (Paid)'
                flow = 'INFLOW'
            elif s.invoice.amount_paid > Decimal('0.00'):
                flow = 'PARTIAL'
                p_first = s.invoice.payments.first()
                mode = p_first.get_payment_mode_display() if p_first else 'अर्धवट जमा'
                status_txt = f"जमा ₹{s.invoice.amount_paid:.2f} / बाकी ₹{s.invoice.balance_due:.2f}"
            else:
                flow = 'CREDIT'
                mode = 'उधार (बाकी)'
                status_txt = 'बाकी (Unpaid)'

        daybook_entries.append({
            'time': s.created_at,
            'type': 'SALE',
            'type_label': 'धान्य/पीठ विक्री',
            'voucher_no': s.sale_number,
            'party': s.customer.name,
            'amount': amt,
            'flow': flow,
            'mode': mode,
            'status': status_txt
        })

    # 10c. Standalone & Khata Lump-sum Payments (exclude payments already tied to today's sales/orders to prevent double counting)
    today_sale_inv_ids = set(Sale.objects.filter(sale_date=today).values_list('invoice__id', flat=True))
    today_grind_inv_ids = set(Invoice.objects.filter(grinding_order__order_date__date=today).values_list('id', flat=True))
    linked_inv_ids = today_sale_inv_ids.union(today_grind_inv_ids)

    for p in Payment.objects.filter(payment_date=today).exclude(invoice_id__in=linked_inv_ids).select_related('customer')[:10]:
        daybook_entries.append({
            'time': p.created_at,
            'type': 'PAYMENT',
            'type_label': 'खाते जमा (Khata Inflow)',
            'voucher_no': f"PAY-{p.id}",
            'party': p.customer.name if p.customer else 'ग्राहक',
            'amount': p.amount,
            'flow': 'INFLOW',
            'mode': p.get_payment_mode_display(),
            'status': 'जमा'
        })

    # 10d. Expenses (Outflow)
    for e in Expense.objects.filter(expense_date=today)[:10]:
        daybook_entries.append({
            'time': e.created_at,
            'type': 'EXPENSE',
            'type_label': 'दुकान खर्च (Expense)',
            'voucher_no': f"EXP-{e.id}",
            'party': e.get_category_display(),
            'amount': e.amount,
            'flow': 'OUTFLOW',
            'mode': e.get_payment_mode_display(),
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
        'sales_chart_has_data': sales_chart_has_data,
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

    qs = Customer.objects.filter(is_active=True).order_by('-id')
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(mobile__icontains=query) | Q(address__icontains=query))
    if cust_type:
        qs = qs.filter(customer_type=cust_type)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page', 1)
    customers = paginator.get_page(page_number)

    return render(request, 'girni/customer_list.html', {
        'customers': customers,
        'query': query,
        'cust_type': cust_type,
        'total_count': qs.count()
    })


@login_required
def customer_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        raw_mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        customer_type = request.POST.get('customer_type', 'REGULAR')

        if not name:
            messages.error(request, "ग्राहकाचे नाव आवश्यक आहे (Customer name is required).")
            return render(request, 'girni/customer_form.html', {'action': 'Create', 'data': request.POST})

        clean_mob = clean_mobile(raw_mobile)
        if not clean_mob:
            messages.error(request, "कृपया १० अंकी वैध मोबाईल नंबर टाका (उदा. 9876543210). अक्षरे किंवा चुकीचा नंबर चालणार नाही.")
            return render(request, 'girni/customer_form.html', {'action': 'Create', 'data': request.POST})

        existing = Customer.objects.filter(mobile=clean_mob).first()
        if existing:
            messages.info(request, f"या मोबाईल नंबरवर '{existing.name}' हे ग्राहक आधीच नोंदणीकृत आहेत.")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax'):
                return JsonResponse({'status': 'ok', 'id': existing.id, 'name': existing.name, 'mobile': existing.mobile})
            return redirect('customer_detail', customer_id=existing.id)

        if customer_type not in dict(Customer.CUSTOMER_TYPE_CHOICES):
            customer_type = 'REGULAR'

        cust = Customer.objects.create(
            name=name,
            mobile=clean_mob,
            address=address,
            customer_type=customer_type
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax'):
            return JsonResponse({'status': 'ok', 'id': cust.id, 'name': cust.name, 'mobile': cust.mobile})
        
        messages.success(request, f"ग्राहक '{cust.name}' यशस्वीपणे जोडले.")
        return redirect('customer_detail', customer_id=cust.id)

    return render(request, 'girni/customer_form.html', {'action': 'Create'})


@login_required
def customer_edit_view(request, customer_id):
    cust = get_object_or_404(Customer, id=customer_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        raw_mobile = request.POST.get('mobile', '').strip()
        customer_type = request.POST.get('customer_type', cust.customer_type)

        if not name:
            messages.error(request, "ग्राहकाचे नाव आवश्यक आहे.")
            return render(request, 'girni/customer_form.html', {'customer': cust, 'action': 'Edit'})

        clean_mob = clean_mobile(raw_mobile)
        if not clean_mob:
            messages.error(request, "कृपया १० अंकी वैध मोबाईल नंबर टाका.")
            return render(request, 'girni/customer_form.html', {'customer': cust, 'action': 'Edit'})

        dup = Customer.objects.filter(mobile=clean_mob).exclude(id=cust.id).first()
        if dup:
            messages.error(request, f"हा मोबाईल नंबर आधीच '{dup.name}' यांच्या नावावर नोंदवला आहे.")
            return render(request, 'girni/customer_form.html', {'customer': cust, 'action': 'Edit'})

        cust.name = name
        cust.mobile = clean_mob
        cust.address = request.POST.get('address', cust.address).strip()
        cust.customer_type = customer_type if customer_type in dict(Customer.CUSTOMER_TYPE_CHOICES) else cust.customer_type
        cust.save()
        messages.success(request, f"ग्राहक '{cust.name}' माहिती अद्ययावत झाली.")
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
    search_query = request.GET.get('q', '').strip()
    suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    if search_query:
        suppliers = suppliers.filter(Q(name__icontains=search_query) | Q(mobile__icontains=search_query))
    paginator = Paginator(suppliers, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'girni/supplier_list.html', {
        'suppliers': page_obj,
        'page_obj': page_obj,
        'search_query': search_query
    })


@login_required
def supplier_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        raw_mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not name:
            messages.error(request, "पुरवठादाराचे नाव आवश्यक आहे. / Supplier name is required.")
            return render(request, 'girni/supplier_form.html', {'action': 'Create', 'name': name, 'mobile': raw_mobile, 'address': address, 'notes': notes})

        clean_mob = clean_mobile(raw_mobile)
        if not clean_mob:
            messages.error(request, "कृपया १० अंकी वैध मोबाईल नंबर टाका (उदा. 9822012345). / Please enter a valid 10-digit mobile number.")
            return render(request, 'girni/supplier_form.html', {'action': 'Create', 'name': name, 'mobile': raw_mobile, 'address': address, 'notes': notes})

        if Supplier.objects.filter(mobile=clean_mob).exists():
            messages.error(request, f"हा मोबाईल नंबर ({clean_mob}) आधीच नोंदवला आहे.")
            return render(request, 'girni/supplier_form.html', {'action': 'Create', 'name': name, 'mobile': raw_mobile, 'address': address, 'notes': notes})

        sup = Supplier.objects.create(name=name, mobile=clean_mob, address=address, notes=notes)
        messages.success(request, f"पुरवठादार '{sup.name}' यशस्वीपणे जोडले. / Supplier '{sup.name}' added successfully.")
        return redirect('supplier_detail', supplier_id=sup.id)

    return render(request, 'girni/supplier_form.html', {'action': 'Create'})


@login_required
def supplier_detail_view(request, supplier_id):
    sup = get_object_or_404(Supplier, id=supplier_id)
    purchases = sup.purchases.all().order_by('-purchase_date', '-id')
    return render(request, 'girni/supplier_detail.html', {'supplier': sup, 'purchases': purchases})


@login_required
def supplier_edit_view(request, supplier_id):
    sup = get_object_or_404(Supplier, id=supplier_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        raw_mobile = request.POST.get('mobile', '').strip()
        address = request.POST.get('address', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not name:
            messages.error(request, "पुरवठादाराचे नाव आवश्यक आहे.")
            return render(request, 'girni/supplier_form.html', {'supplier': sup, 'action': 'Edit'})

        clean_mob = clean_mobile(raw_mobile)
        if not clean_mob:
            messages.error(request, "कृपया १० अंकी वैध मोबाईल नंबर टाका.")
            return render(request, 'girni/supplier_form.html', {'supplier': sup, 'action': 'Edit'})

        dup = Supplier.objects.filter(mobile=clean_mob).exclude(id=sup.id).first()
        if dup:
            messages.error(request, f"हा मोबाईल नंबर आधीच '{dup.name}' यांच्या नावावर नोंदवला आहे.")
            return render(request, 'girni/supplier_form.html', {'supplier': sup, 'action': 'Edit'})

        sup.name = name
        sup.mobile = clean_mob
        sup.address = address
        sup.notes = notes
        sup.save()
        messages.success(request, f"पुरवठादार '{sup.name}' माहिती अद्ययावत झाली.")
        return redirect('supplier_detail', supplier_id=sup.id)

    return render(request, 'girni/supplier_form.html', {'supplier': sup, 'action': 'Edit'})


# ==========================================
# GRAIN & PRODUCT MASTER
# ==========================================
@login_required
def product_list_view(request):
    p_type = request.GET.get('type', '')
    search_query = request.GET.get('q', '').strip()
    products = Product.objects.filter(is_active=True).order_by('name')
    if p_type:
        products = products.filter(product_type=p_type)
    if search_query:
        products = products.filter(Q(name__icontains=search_query) | Q(name_mr__icontains=search_query))

    paginator = Paginator(products, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'girni/product_list.html', {
        'products': page_obj,
        'page_obj': page_obj,
        'selected_type': p_type,
        'search_query': search_query
    })


@login_required
def product_create_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        name_mr = request.POST.get('name_mr', '').strip()
        product_type = request.POST.get('product_type', 'RAW_GRAIN')
        unit = request.POST.get('unit', 'KG').strip() or 'KG'
        purchase_rate_str = request.POST.get('purchase_rate', '0.00').strip()
        selling_rate_str = request.POST.get('selling_rate', '0.00').strip()
        grinding_rate_str = request.POST.get('grinding_rate', '5.00').strip()
        current_stock_str = request.POST.get('current_stock', '0.000').strip()
        low_stock_str = request.POST.get('low_stock_threshold', '20.000').strip()

        if not name:
            messages.error(request, "मालाचे नाव आवश्यक आहे. / Product name is required.")
            return render(request, 'girni/product_form.html', {'action': 'Create'})

        # Case-insensitive duplicate name check
        if Product.objects.filter(name__iexact=name).exists():
            messages.error(request, f"या नावाचा माल ('{name}') आधीच अस्तित्वात आहे.")
            return render(request, 'girni/product_form.html', {'action': 'Create'})

        try:
            purchase_rate = Decimal(purchase_rate_str or '0')
            selling_rate = Decimal(selling_rate_str or '0')
            grinding_rate = Decimal(grinding_rate_str or '0')
            current_stock = Decimal(current_stock_str or '0')
            low_stock = Decimal(low_stock_str or '20')

            if purchase_rate < 0 or selling_rate < 0 or grinding_rate < 0:
                raise ValueError("दर ० किंवा त्यापेक्षा जास्त असणे आवश्यक आहे.")
            if current_stock < 0 or low_stock < 0:
                raise ValueError("साठा ० किंवा त्यापेक्षा जास्त असणे आवश्यक आहे.")
        except Exception as e:
            messages.error(request, f"दर किंवा साठ्याची संख्या अयोग्य आहे: {str(e)}")
            return render(request, 'girni/product_form.html', {'action': 'Create'})

        if selling_rate > 0 and purchase_rate > 0 and selling_rate < purchase_rate:
            messages.warning(request, f"सूचना: विक्री दर (₹{selling_rate}) हा खरेदी दरापेक्षा (₹{purchase_rate}) कमी आहे.")

        prod = Product.objects.create(
            name=name,
            name_mr=name_mr,
            product_type=product_type,
            unit=unit,
            purchase_rate=purchase_rate,
            selling_rate=selling_rate,
            grinding_rate=grinding_rate,
            current_stock=current_stock,
            low_stock_threshold=low_stock
        )
        if prod.current_stock > Decimal('0.000'):
            StockMovement.objects.create(
                product=prod,
                stock_type=prod.product_type,
                movement_type='ADJUSTMENT',
                quantity_kg=prod.current_stock,
                reference_type='OPENING_STOCK',
                reference_id=f"INIT-{prod.id}",
                balance_after_kg=prod.current_stock,
                notes="आरंभीचा साठा (Initial opening stock)"
            )

        messages.success(request, f"माल '{prod.display_name}' यशस्वीपणे तयार झाला.")
        return redirect('product_list')

    return render(request, 'girni/product_form.html', {'action': 'Create'})


@login_required
def product_edit_view(request, product_id):
    prod = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, "मालाचे नाव आवश्यक आहे.")
            return render(request, 'girni/product_form.html', {'product': prod, 'action': 'Edit'})

        dup = Product.objects.filter(name__iexact=name).exclude(id=prod.id).first()
        if dup:
            messages.error(request, f"या नावाचा माल ('{dup.name}') आधीच अस्तित्वात आहे.")
            return render(request, 'girni/product_form.html', {'product': prod, 'action': 'Edit'})

        try:
            purchase_rate = Decimal(request.POST.get('purchase_rate', prod.purchase_rate) or '0')
            selling_rate = Decimal(request.POST.get('selling_rate', prod.selling_rate) or '0')
            grinding_rate = Decimal(request.POST.get('grinding_rate', prod.grinding_rate) or '0')
            low_stock = Decimal(request.POST.get('low_stock_threshold', prod.low_stock_threshold) or '20')

            if purchase_rate < 0 or selling_rate < 0 or grinding_rate < 0 or low_stock < 0:
                raise ValueError("दर किंवा मर्यादा ० पेक्षा कमी असू शकत नाही.")
        except Exception as e:
            messages.error(request, f"दर किंवा मर्यादा अयोग्य आहे: {str(e)}")
            return render(request, 'girni/product_form.html', {'product': prod, 'action': 'Edit'})

        if selling_rate > 0 and purchase_rate > 0 and selling_rate < purchase_rate:
            messages.warning(request, f"सूचना: विक्री दर (₹{selling_rate}) हा खरेदी दरापेक्षा (₹{purchase_rate}) कमी आहे.")

        prod.name = name
        prod.name_mr = request.POST.get('name_mr', '').strip()
        prod.product_type = request.POST.get('product_type', prod.product_type)
        prod.purchase_rate = purchase_rate
        prod.selling_rate = selling_rate
        prod.grinding_rate = grinding_rate
        prod.low_stock_threshold = low_stock
        prod.is_active = request.POST.get('is_active') == 'on'
        prod.save()
        messages.success(request, f"माल '{prod.display_name}' माहिती अद्ययावत झाली.")
        return redirect('product_list')

    return render(request, 'girni/product_form.html', {'product': prod, 'action': 'Edit'})


# ==========================================
# PURCHASE MANAGEMENT
# ==========================================
@login_required
def purchase_list_view(request):
    purchases = Purchase.objects.select_related('supplier').all().order_by('-purchase_date', '-id')
    paginator = Paginator(purchases, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'girni/purchase_list.html', {'purchases': page_obj, 'page_obj': page_obj})


@login_required
def purchase_create_view(request):
    suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    raw_products = Product.objects.filter(product_type='RAW_GRAIN', is_active=True).order_by('name')

    if request.method == 'POST':
        supplier_id = request.POST.get('supplier_id')
        purchase_date_str = request.POST.get('purchase_date')
        discount = request.POST.get('discount', '0')
        other_charges = request.POST.get('other_charges', '0')
        amount_paid = request.POST.get('amount_paid', '0')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        notes = request.POST.get('notes', '')

        if not supplier_id:
            messages.error(request, "कृपया पुरवठादार निवडा. / Please select a supplier.")
            return render(request, 'girni/purchase_form.html', {
                'suppliers': suppliers,
                'raw_products': raw_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })
        
        supplier = get_object_or_404(Supplier, id=supplier_id)

        # Validate date <= today
        if purchase_date_str:
            try:
                p_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
                if p_date > timezone.now().date():
                    messages.error(request, "खरेदी तारीख भविष्यातील असू शकत नाही. / Purchase date cannot be in the future.")
                    return render(request, 'girni/purchase_form.html', {
                        'suppliers': suppliers,
                        'raw_products': raw_products,
                        'today': timezone.now().date(),
                        'post_data': request.POST
                    })
            except ValueError:
                p_date = timezone.now().date()
        else:
            p_date = timezone.now().date()

        # Parse dynamic item rows
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity_kg[]')
        rates = request.POST.getlist('rate_per_kg[]')

        items_data = []
        for pid, qty, rate in zip(product_ids, quantities, rates):
            if pid and qty and rate:
                try:
                    q_dec = Decimal(str(qty))
                    r_dec = Decimal(str(rate))
                    if q_dec > Decimal('0.000') and r_dec >= Decimal('0.00'):
                        prod = Product.objects.get(id=pid)
                        items_data.append({
                            'product': prod,
                            'quantity_kg': q_dec,
                            'rate_per_kg': r_dec
                        })
                except Exception:
                    pass

        if not items_data:
            messages.error(request, "कृपया किमान एका धान्याची खरेदी नोंदवा (वजन ० पेक्षा जास्त असावे).")
            return render(request, 'girni/purchase_form.html', {
                'suppliers': suppliers,
                'raw_products': raw_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })

        try:
            purchase = PurchaseService.create_purchase(
                supplier=supplier,
                purchase_date=p_date,
                items_data=items_data,
                discount=discount,
                other_charges=other_charges,
                amount_paid=amount_paid,
                payment_mode=payment_mode,
                notes=notes
            )
            messages.success(request, f"खरेदी पावती #{purchase.purchase_number} नोंदवली! धान्याचा साठा वाढवला गेला.")
            return redirect('purchase_detail', purchase_id=purchase.id)
        except ValidationError as ve:
            messages.error(request, f"खरेदी त्रुटी: {ve.message if hasattr(ve, 'message') else str(ve)}")
        except Exception as e:
            messages.error(request, f"खरेदी साठवताना त्रुटी: {str(e)}")

        return render(request, 'girni/purchase_form.html', {
            'suppliers': suppliers,
            'raw_products': raw_products,
            'today': timezone.now().date(),
            'post_data': request.POST
        })

    return render(request, 'girni/purchase_form.html', {
        'suppliers': suppliers,
        'raw_products': raw_products,
        'today': timezone.now().date()
    })


@login_required
def purchase_detail_view(request, purchase_id):
    purchase = get_object_or_404(Purchase.objects.select_related('supplier'), id=purchase_id)
    return render(request, 'girni/purchase_detail.html', {'purchase': purchase})


@login_required
def supplier_payment_view(request, purchase_id):
    purchase = get_object_or_404(Purchase, id=purchase_id)
    if request.method == 'POST':
        amount = request.POST.get('amount')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        reference_number = request.POST.get('reference_number', '')
        notes = request.POST.get('notes', '')

        try:
            BillingPaymentService.record_supplier_payment(
                purchase=purchase,
                amount=amount,
                payment_mode=payment_mode,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"पुरवठादाराला ₹{amount} चे पेमेंट यशस्वीपणे नोंदवले!")
        except ValidationError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f"पेमेंट त्रुटी: {str(e)}")

    return redirect('purchase_detail', purchase_id=purchase.id)


# ==========================================
# INVENTORY & STOCK LEDGER
# ==========================================
@login_required
def stock_summary_view(request):
    raw_grains = Product.objects.filter(product_type='RAW_GRAIN', is_active=True).order_by('name')
    flour_products = Product.objects.filter(product_type='FINISHED_FLOUR', is_active=True).order_by('name')
    return render(request, 'girni/stock_summary.html', {
        'raw_grains': raw_grains,
        'flour_products': flour_products
    })


@login_required
def stock_ledger_view(request):
    raw_pid = request.GET.get('product_id', '').strip()
    movement_type = request.GET.get('movement_type', '').strip()

    movements = StockMovement.objects.select_related('product').all().order_by('-created_at')
    selected_product = None
    if raw_pid and raw_pid.isdigit():
        movements = movements.filter(product_id=int(raw_pid))
        selected_product = int(raw_pid)

    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    paginator = Paginator(movements, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    all_products = Product.objects.filter(is_active=True).order_by('name')
    return render(request, 'girni/stock_ledger.html', {
        'movements': page_obj,
        'page_obj': page_obj,
        'products': all_products,
        'selected_product': selected_product,
        'selected_movement': movement_type
    })


@login_required
def stock_adjust_view(request):
    products = Product.objects.filter(is_active=True).order_by('name')
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        new_stock = request.POST.get('new_stock_kg', '0')
        reason = request.POST.get('reason', '').strip()
        notes = request.POST.get('notes', '').strip()

        prod = get_object_or_404(Product, id=product_id)
        if not reason:
            messages.error(request, "साठा बदलण्याचे कारण आवश्यक आहे. / Reason is required.")
        else:
            try:
                ns_dec = Decimal(str(new_stock))
                if ns_dec < Decimal('0.000'):
                    raise ValidationError("नवीन साठा ० पेक्षा कमी असू शकत नाही.")
                InventoryService.adjust_stock(prod, ns_dec, reason, notes)
                messages.success(request, f"'{prod.display_name}' चा साठा {new_stock} KG वर अद्ययावत केला.")
                return redirect('stock_summary')
            except ValidationError as ve:
                messages.error(request, str(ve))
            except Exception as e:
                messages.error(request, f"साठा बदल अयशस्वी: {str(e)}")

    return render(request, 'girni/stock_adjust.html', {'products': products})


# ==========================================
# CUSTOMER GRINDING ORDERS
# ==========================================
@login_required
def grinding_order_list_view(request):
    status_filter = request.GET.get('status', '').strip()
    search_query = request.GET.get('q', '').strip()
    orders = GrindingOrder.objects.select_related('customer', 'grain').all().order_by('-order_date')
    if status_filter:
        orders = orders.filter(status=status_filter)
    if search_query:
        orders = orders.filter(
            Q(order_number__icontains=search_query) |
            Q(token_number__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__mobile__icontains=search_query)
        )

    paginator = Paginator(orders, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'girni/grinding_list.html', {
        'orders': page_obj,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query
    })


@login_required
def grinding_order_create_view(request):
    customers = Customer.objects.filter(is_active=True).order_by('name')
    raw_products = Product.objects.filter(product_type='RAW_GRAIN', is_active=True).order_by('name')
    default_delivery = (timezone.localtime() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")

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
        quick_name = request.POST.get('quick_customer_name', '').strip()
        quick_mobile = request.POST.get('quick_customer_mobile', '').strip()

        # Validation checks
        if not customer_id and not quick_name:
            messages.error(request, "Please select an existing customer or enter walk-in customer details. / कृपया ग्राहक निवडा किंवा थेट ग्राहकाचे नाव लिहा.")
            return render(request, 'girni/grinding_form.html', {
                'customers': customers,
                'raw_products': raw_products,
                'default_expected_delivery': default_delivery,
                'post_data': request.POST
            })

        if not grain_id:
            messages.error(request, "कृपया धान्याचा प्रकार निवडा.")
            return render(request, 'girni/grinding_form.html', {
                'customers': customers,
                'raw_products': raw_products,
                'default_expected_delivery': default_delivery,
                'post_data': request.POST
            })

        try:
            inp_val = Decimal(str(input_kg or 0))
            if inp_val <= Decimal('0.000'):
                raise ValueError("वजन ० पेक्षा जास्त असावे.")
        except Exception:
            messages.error(request, "कृपया धान्याचे वैध वजन (KG) टाका (० पेक्षा जास्त).")
            return render(request, 'girni/grinding_form.html', {
                'customers': customers,
                'raw_products': raw_products,
                'default_expected_delivery': default_delivery,
                'post_data': request.POST
            })

        # Walk-in customer instant create or lookup
        if not customer_id and quick_name:
            clean_mob = clean_mobile(quick_mobile) if quick_mobile else '9999999999'
            customer, _ = Customer.objects.get_or_create(
                name=quick_name,
                mobile=clean_mob or '9999999999',
                defaults={'customer_type': 'WALKIN'}
            )
        else:
            customer = get_object_or_404(Customer, id=customer_id)

        grain = get_object_or_404(Product, id=grain_id)

        try:
            rate_dec = Decimal(rate_per_kg) if rate_per_kg else None
            order = GrindingService.create_order(
                customer=customer,
                grain=grain,
                input_kg=inp_val,
                rate_per_kg=rate_dec,
                ownership_type=ownership_type,
                expected_delivery=expected_delivery,
                notes=notes,
                is_paid=is_paid,
                payment_mode=payment_mode
            )
            messages.success(request, f"दळण ऑर्डर {order.order_number} (टोकन: {order.token_number}) नोंदवली गेली!")
            return redirect('grinding_order_detail', order_id=order.id)
        except ValidationError as ve:
            messages.error(request, f"ऑर्डर त्रुटी: {str(ve)}")
        except Exception as e:
            messages.error(request, f"ऑर्डर नोंदवताना त्रुटी: {str(e)}")

        return render(request, 'girni/grinding_form.html', {
            'customers': customers,
            'raw_products': raw_products,
            'default_expected_delivery': default_delivery,
            'post_data': request.POST
        })

    return render(request, 'girni/grinding_form.html', {
        'customers': customers,
        'raw_products': raw_products,
        'default_expected_delivery': default_delivery
    })


@login_required
def grinding_order_detail_view(request, order_id):
    order = get_object_or_404(
        GrindingOrder.objects.select_related('customer', 'grain', 'invoice'),
        id=order_id
    )
    return render(request, 'girni/grinding_detail.html', {'order': order})


ALLOWED_TRANSITIONS = {
    'PENDING': ['IN_PROGRESS', 'CANCELLED'],
    'IN_PROGRESS': ['COMPLETED', 'CANCELLED'],
    'COMPLETED': ['DELIVERED'],
    'DELIVERED': [],
    'CANCELLED': []
}

@login_required
def grinding_order_status_update_view(request, order_id):
    order = get_object_or_404(GrindingOrder, id=order_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        output_kg = request.POST.get('output_kg')

        valid_targets = ALLOWED_TRANSITIONS.get(order.status, [])
        if new_status not in valid_targets:
            messages.error(request, f"स्थिती बदल अवैध आहे: '{order.get_status_display()}' वरून '{new_status}' करता येत नाही.")
            return redirect('grinding_order_detail', order_id=order.id)

        if new_status == 'COMPLETED':
            if not output_kg:
                messages.error(request, "दळण पूर्ण करताना तयार पीठाचे प्रत्यक्ष वजन (Output KG) आवश्यक आहे.")
                return redirect('grinding_order_detail', order_id=order.id)
            try:
                out_dec = Decimal(str(output_kg))
                if out_dec <= Decimal('0.000') or out_dec > order.input_kg:
                    raise ValidationError(f"तयार पीठाचे वजन ० पेक्षा जास्त आणि मूळ वजनापेक्षा ({order.input_kg} KG) कमी किंवा समान असावे.")
                order.output_kg = out_dec
                order.wastage_kg = order.input_kg - out_dec
            except ValidationError as ve:
                messages.error(request, str(ve))
                return redirect('grinding_order_detail', order_id=order.id)
            except Exception:
                messages.error(request, "कृपया तयार पीठाचे वैध वजन टाका.")
                return redirect('grinding_order_detail', order_id=order.id)

        if new_status == 'CANCELLED':
            if hasattr(order, 'invoice') and order.invoice:
                try:
                    BillingPaymentService.void_invoice(order.invoice, reason=f"दळण ऑर्डर #{order.order_number} रद्द")
                except Exception as e:
                    messages.warning(request, f"बिल रद्द करताना नोंद: {str(e)}")
            if order.ownership_type == 'MILL':
                InventoryService.record_stock_movement(
                    product=order.grain,
                    movement_type='REVERSAL',
                    quantity_kg=order.input_kg,
                    reference_type='VOID_GRINDING',
                    reference_id=order.order_number,
                    notes=f"Grain restored for cancelled grinding #{order.order_number}"
                )

        order.status = new_status
        if new_status == 'DELIVERED':
            order.delivered_at = timezone.now()
        order.save()

        if new_status == 'COMPLETED':
            messages.success(request, f"दळण तयार झाले आहे! WhatsApp वरून {order.customer.name} यांना त्वरित सूचना पाठवा.")
        elif new_status == 'CANCELLED':
            messages.warning(request, f"दळण ऑर्डर #{order.order_number} रद्द करण्यात आली.")
        else:
            messages.success(request, f"दळण स्थिती बदलली: {order.get_status_display()}.")

    return redirect('grinding_order_detail', order_id=order.id)


# ==========================================
# OWN PRODUCTION / FLOUR PROCESSING
# ==========================================
@login_required
def production_list_view(request):
    batches = ProductionBatch.objects.select_related('raw_product', 'flour_product').all().order_by('-batch_date', '-id')
    paginator = Paginator(batches, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'girni/production_list.html', {'batches': page_obj, 'page_obj': page_obj})


@login_required
def production_create_view(request):
    raw_products = Product.objects.filter(product_type='RAW_GRAIN', is_active=True).order_by('name')
    flour_products = Product.objects.filter(product_type='FINISHED_FLOUR', is_active=True).order_by('name')

    if request.method == 'POST':
        raw_id = request.POST.get('raw_product_id')
        flour_id = request.POST.get('flour_product_id')
        input_kg = request.POST.get('input_kg', '0')
        output_kg = request.POST.get('output_kg', '0')
        wastage_kg = request.POST.get('wastage_kg', '0')
        batch_date = request.POST.get('batch_date') or timezone.now().date()
        notes = request.POST.get('notes', '')

        if not raw_id or not flour_id:
            messages.error(request, "कृपया धान्य आणि तयार पीठ दोन्ही निवडा.")
            return render(request, 'girni/production_form.html', {
                'raw_products': raw_products,
                'flour_products': flour_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })

        if raw_id == flour_id:
            messages.error(request, "कच्चे धान्य आणि तयार पीठ एकच असू शकत नाही.")
            return render(request, 'girni/production_form.html', {
                'raw_products': raw_products,
                'flour_products': flour_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })

        try:
            inp_val = Decimal(str(input_kg or 0))
            out_val = Decimal(str(output_kg or 0))
            if inp_val <= Decimal('0.000') or out_val <= Decimal('0.000'):
                raise ValueError("वजन ० पेक्षा जास्त असणे आवश्यक आहे.")
            if out_val > inp_val:
                raise ValueError(f"तयार पीठ ({out_val} KG) धान्यापेक्षा ({inp_val} KG) जास्त असू शकत नाही.")
        except Exception as e:
            messages.error(request, f"वजन अयोग्य: {str(e)}")
            return render(request, 'girni/production_form.html', {
                'raw_products': raw_products,
                'flour_products': flour_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })

        raw_prod = get_object_or_404(Product, id=raw_id)
        flour_prod = get_object_or_404(Product, id=flour_id)

        try:
            batch = ProductionService.process_production_batch(
                raw_product=raw_prod,
                flour_product=flour_prod,
                input_kg=inp_val,
                output_kg=out_val,
                wastage_kg=Decimal(str(wastage_kg or (inp_val - out_val))),
                batch_date=batch_date,
                notes=notes
            )
            messages.success(
                request,
                f"भरडाई बॅच #{batch.batch_number} नोंदवली! "
                f"उतारा (Yield): {batch.yield_percentage}% ({flour_prod.display_name} साठा +{output_kg} KG)."
            )
            return redirect('production_list')
        except ValidationError as ve:
            messages.error(request, f"भरडाई त्रुटी: {str(ve)}")
        except Exception as e:
            messages.error(request, f"भरडाई नोंदवताना त्रुटी: {str(e)}")

        return render(request, 'girni/production_form.html', {
            'raw_products': raw_products,
            'flour_products': flour_products,
            'today': timezone.now().date(),
            'post_data': request.POST
        })

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
    sales = Sale.objects.select_related('customer').prefetch_related('items__product').all().order_by('-sale_date', '-id')
    paginator = Paginator(sales, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'girni/sale_list.html', {'sales': page_obj, 'page_obj': page_obj})


@login_required
def sale_create_view(request):
    customers = Customer.objects.filter(is_active=True).order_by('name')
    all_products = Product.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        customer_id = request.POST.get('customer_id')
        discount = request.POST.get('discount', '0')
        amount_paid = request.POST.get('amount_paid', '0')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        notes = request.POST.get('notes', '')
        quick_name = request.POST.get('quick_customer_name', '').strip()
        quick_mobile = request.POST.get('quick_customer_mobile', '').strip()

        if not customer_id and not quick_name:
            messages.error(request, "Please select an existing customer or enter walk-in customer details. / कृपया ग्राहक निवडा किंवा रोख ग्राहकाचे नाव लिहा.")
            return render(request, 'girni/sale_form.html', {
                'customers': customers,
                'products': all_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })

        if not customer_id and quick_name:
            clean_mob = clean_mobile(quick_mobile) if quick_mobile else '9999999999'
            customer, _ = Customer.objects.get_or_create(
                name=quick_name,
                mobile=clean_mob or '9999999999',
                defaults={'customer_type': 'WALKIN'}
            )
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
            messages.error(request, "कृपया विक्रीसाठी किमान एक माल जोडा (वजन ० पेक्षा जास्त).")
            return render(request, 'girni/sale_form.html', {
                'customers': customers,
                'products': all_products,
                'today': timezone.now().date(),
                'post_data': request.POST
            })

        try:
            sale, invoice = SalesService.create_sale(
                customer=customer,
                items_data=items_data,
                discount=discount,
                amount_paid=amount_paid,
                payment_mode=payment_mode,
                notes=notes
            )
            messages.success(request, f"विक्री #{sale.sale_number} यशस्वी! बिल क्र. {invoice.invoice_number} तयार झाले.")
            return redirect('invoice_detail', invoice_id=invoice.id)
        except ValidationError as ve:
            messages.error(request, f"विक्री त्रुटी: {str(ve)}")
        except Exception as e:
            messages.error(request, f"विक्री पूर्ण करताना त्रुटी: {str(e)}")

        return render(request, 'girni/sale_form.html', {
            'customers': customers,
            'products': all_products,
            'today': timezone.now().date(),
            'post_data': request.POST
        })

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
    status_filter = request.GET.get('status', '').strip()
    inv_type = request.GET.get('type', '').strip()
    search_query = request.GET.get('q', '').strip()

    invoices = Invoice.objects.select_related('customer', 'sale', 'grinding_order').all().order_by('-invoice_date', '-id')
    if status_filter:
        invoices = invoices.filter(status=status_filter)
    if inv_type:
        invoices = invoices.filter(invoice_type=inv_type)
    if search_query:
        invoices = invoices.filter(
            Q(invoice_number__icontains=search_query) |
            Q(customer__name__icontains=search_query) |
            Q(customer__mobile__icontains=search_query)
        )

    paginator = Paginator(invoices, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'girni/invoice_list.html', {
        'invoices': page_obj,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'selected_type': inv_type,
        'search_query': search_query
    })


@login_required
def invoice_detail_view(request, invoice_id):
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'sale', 'grinding_order').prefetch_related('payments'),
        id=invoice_id
    )
    settings_obj = ShopSettings.get_settings()

    # Generate WhatsApp message link
    msg = f"*{settings_obj.shop_name}* (गिरणी बिल)\n"
    msg += f"बिल क्र.: {invoice.invoice_number}\n"
    msg += f"ग्राहक: {invoice.customer.name}\n"
    msg += f"तारीख: {invoice.invoice_date.strftime('%d-%m-%Y')}\n"
    msg += f"एकूण रक्कम: ₹{invoice.total:.2f}\n"
    msg += f"जमा रक्कम: ₹{invoice.amount_paid:.2f}\n"
    msg += f"बाकी रक्कम: ₹{invoice.balance_due:.2f}\n"
    if settings_obj.upi_id:
        msg += f"UPI पेमेंट: {settings_obj.upi_id}\n"
    msg += f"{settings_obj.footer_message}"

    encoded_msg = urllib.parse.quote(msg)
    mobile_clean = invoice.customer.mobile.replace("+", "").replace("-", "").replace(" ", "")
    if len(mobile_clean) == 10:
        mobile_clean = "91" + mobile_clean
    whatsapp_url = f"https://wa.me/{mobile_clean}?text={encoded_msg}"

    return render(request, 'girni/invoice_detail.html', {
        'invoice': invoice,
        'whatsapp_url': whatsapp_url,
        'raw_message': msg,
        'settings': settings_obj
    })


@login_required
def invoice_pdf_view(request, invoice_id):
    from .pdf_utils import generate_invoice_pdf
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
            messages.error(request, "बिल क्रमांक सापडला नाही. / Invoice ID is missing.")
            return redirect('invoice_list')

        invoice = get_object_or_404(Invoice, id=invoice_id)
        if not amount:
            messages.error(request, "कृपया जमा रक्कम टाका.")
            return redirect('invoice_detail', invoice_id=invoice.id)

        try:
            payment = BillingPaymentService.record_payment(
                invoice=invoice,
                amount=amount,
                payment_mode=payment_mode,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"बिल {invoice.invoice_number} साठी ₹{payment.amount} ची रक्कम यशस्वीरीत्या जमा झाली.")
        except ValidationError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f"पेमेंट त्रुटी: {str(e)}")

        return redirect('invoice_detail', invoice_id=invoice.id)

    return redirect('invoice_list')


@login_required
def void_invoice_view(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip() or "मालकाने बिल रद्द केले"
        try:
            BillingPaymentService.void_invoice(invoice, reason=reason)
            messages.success(request, f"बिल #{invoice.invoice_number} यशस्वीरीत्या रद्द (Void) केले आणि साठा पूर्ववत केला!")
        except ValidationError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f"बिल रद्द करताना त्रुटी: {str(e)}")

    return redirect('invoice_detail', invoice_id=invoice.id)


@login_required
def customer_khata_payment_view(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    if request.method == 'POST':
        amount = request.POST.get('amount')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        reference_number = request.POST.get('reference_number', '')
        notes = request.POST.get('notes', '')

        try:
            payments = BillingPaymentService.record_customer_khata_payment(
                customer=customer,
                amount=amount,
                payment_mode=payment_mode,
                reference_number=reference_number,
                notes=notes
            )
            messages.success(request, f"ग्राहकाच्या खात्यात ₹{amount} यशस्वीपणे जमा झाले! ({len(payments)} बिलांची बाकी कमी झाली).")
        except ValidationError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f"खाते जमा त्रुटी: {str(e)}")

    return redirect('customer_detail', customer_id=customer.id)


@login_required
def payment_list_view(request):
    payments = Payment.objects.select_related('customer', 'invoice').all().order_by('-payment_date', '-id')
    paginator = Paginator(payments, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'girni/payment_list.html', {'payments': page_obj, 'page_obj': page_obj})


# ==========================================
# EXPENSES
# ==========================================
ALLOWED_RECEIPT_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}
MAX_RECEIPT_BYTES = 5 * 1024 * 1024  # 5MB

@login_required
def expense_list_view(request):
    category_filter = request.GET.get('category', '').strip()
    expenses = Expense.objects.all().order_by('-expense_date', '-id')
    if category_filter:
        expenses = expenses.filter(category=category_filter)

    total_expense = expenses.aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')

    paginator = Paginator(expenses, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'girni/expense_list.html', {
        'expenses': page_obj,
        'page_obj': page_obj,
        'total_expense': total_expense,
        'categories': Expense.CATEGORY_CHOICES,
        'selected_category': category_filter
    })


@login_required
def expense_create_view(request):
    if request.method == 'POST':
        category = request.POST.get('category')
        amount = request.POST.get('amount')
        expense_date_str = request.POST.get('expense_date')
        payment_mode = request.POST.get('payment_mode', 'CASH')
        description = request.POST.get('description', '').strip()
        receipt = request.FILES.get('receipt_file')

        valid_cats = dict(Expense.CATEGORY_CHOICES)
        if category not in valid_cats:
            messages.error(request, "कृपया खर्चाचा वैध वर्ग निवडा.")
            return render(request, 'girni/expense_form.html', {
                'today': timezone.now().date(),
                'categories': Expense.CATEGORY_CHOICES,
                'payment_modes': Expense.PAYMENT_MODE_CHOICES,
                'action': 'Create'
            })

        try:
            amt_dec = Decimal(str(amount or 0))
            if amt_dec <= Decimal('0.00'):
                raise ValueError("Amount must be greater than zero.")
        except Exception:
            messages.error(request, "कृपया खर्चाची वैध रक्कम टाका (० पेक्षा जास्त).")
            return render(request, 'girni/expense_form.html', {
                'today': timezone.now().date(),
                'categories': Expense.CATEGORY_CHOICES,
                'payment_modes': Expense.PAYMENT_MODE_CHOICES,
                'action': 'Create'
            })

        if expense_date_str:
            try:
                exp_date = datetime.strptime(expense_date_str, "%Y-%m-%d").date()
                if exp_date > timezone.now().date():
                    messages.error(request, "खर्चाची तारीख भविष्यातील असू शकत नाही.")
                    return render(request, 'girni/expense_form.html', {
                        'today': timezone.now().date(),
                        'categories': Expense.CATEGORY_CHOICES,
                        'payment_modes': Expense.PAYMENT_MODE_CHOICES,
                        'action': 'Create'
                    })
            except ValueError:
                exp_date = timezone.now().date()
        else:
            exp_date = timezone.now().date()

        if receipt:
            ext = receipt.name.split('.')[-1].lower()
            if ext not in ALLOWED_RECEIPT_EXTENSIONS:
                messages.error(request, f"पावतीची फाइल केवळ JPG, PNG किंवा PDF फॉरमॅटमध्ये असावी (दिलेली: {ext}).")
                return render(request, 'girni/expense_form.html', {
                    'today': timezone.now().date(),
                    'categories': Expense.CATEGORY_CHOICES,
                    'payment_modes': Expense.PAYMENT_MODE_CHOICES,
                    'action': 'Create'
                })
            if receipt.size > MAX_RECEIPT_BYTES:
                messages.error(request, "पावती फाइलचा आकार 5MB पेक्षा कमी असणे आवश्यक आहे.")
                return render(request, 'girni/expense_form.html', {
                    'today': timezone.now().date(),
                    'categories': Expense.CATEGORY_CHOICES,
                    'payment_modes': Expense.PAYMENT_MODE_CHOICES,
                    'action': 'Create'
                })

        exp = Expense.objects.create(
            category=category,
            amount=amt_dec,
            expense_date=exp_date,
            payment_mode=payment_mode,
            description=description,
            receipt_file=receipt
        )
        messages.success(request, f"₹{exp.amount} चा खर्च यशस्वीरीत्या नोंदवला!")
        return redirect('expense_list')

    return render(request, 'girni/expense_form.html', {
        'today': timezone.now().date(),
        'categories': Expense.CATEGORY_CHOICES,
        'payment_modes': Expense.PAYMENT_MODE_CHOICES,
        'action': 'Create'
    })


@login_required
def expense_edit_view(request, expense_id):
    exp = get_object_or_404(Expense, id=expense_id)
    if request.method == 'POST':
        category = request.POST.get('category')
        amount = request.POST.get('amount')
        expense_date_str = request.POST.get('expense_date')
        payment_mode = request.POST.get('payment_mode', exp.payment_mode)
        description = request.POST.get('description', '').strip()
        receipt = request.FILES.get('receipt_file')

        if category in dict(Expense.CATEGORY_CHOICES):
            exp.category = category
        try:
            amt_dec = Decimal(str(amount or 0))
            if amt_dec > Decimal('0.00'):
                exp.amount = amt_dec
        except Exception:
            pass

        if expense_date_str:
            try:
                exp_date = datetime.strptime(expense_date_str, "%Y-%m-%d").date()
                if exp_date <= timezone.now().date():
                    exp.expense_date = exp_date
            except ValueError:
                pass

        exp.payment_mode = payment_mode
        exp.description = description
        if receipt:
            ext = receipt.name.split('.')[-1].lower()
            if ext in ALLOWED_RECEIPT_EXTENSIONS and receipt.size <= MAX_RECEIPT_BYTES:
                exp.receipt_file = receipt
        exp.save()
        messages.success(request, "खर्च नोंद अद्ययावत झाली.")
        return redirect('expense_list')

    return render(request, 'girni/expense_form.html', {
        'expense': exp,
        'today': exp.expense_date,
        'categories': Expense.CATEGORY_CHOICES,
        'payment_modes': Expense.PAYMENT_MODE_CHOICES,
        'action': 'Edit'
    })


@login_required
def expense_delete_view(request, expense_id):
    exp = get_object_or_404(Expense, id=expense_id)
    if request.method == 'POST':
        amt = exp.amount
        exp.delete()
        messages.success(request, f"₹{amt} ची खर्च नोंद हटवली.")
    return redirect('expense_list')


# ==========================================
# COMPREHENSIVE REPORTS (SRS 4.13)
# ==========================================
@login_required
def reports_view(request):
    today = timezone.now().date()
    from_date_str = request.GET.get('from_date', '').strip()
    to_date_str = request.GET.get('to_date', '').strip()

    try:
        from_date = datetime.strptime(from_date_str, "%Y-%m-%d").date() if from_date_str else (today - timedelta(days=30))
    except ValueError:
        from_date = today - timedelta(days=30)

    try:
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d").date() if to_date_str else today
    except ValueError:
        to_date = today

    # Swap dates if entered in reverse
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    from_str = from_date.strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")

    # Sales in range
    sales_qs = Sale.objects.filter(sale_date__gte=from_date, sale_date__lte=to_date, status='COMPLETED')
    total_sales = sales_qs.aggregate(tot=Sum('total'))['tot'] or Decimal('0.00')

    # Grinding charges in range
    grinding_qs = GrindingOrder.objects.filter(order_date__date__gte=from_date, order_date__date__lte=to_date).exclude(status='CANCELLED')
    total_grinding = grinding_qs.aggregate(tot=Sum('charges'))['tot'] or Decimal('0.00')
    total_grinding_orders = grinding_qs.count()

    # Grain Purchases in range (Cost of Goods)
    purchase_qs = Purchase.objects.filter(purchase_date__gte=from_date, purchase_date__lte=to_date)
    total_purchases = purchase_qs.aggregate(tot=Sum('total'))['tot'] or Decimal('0.00')

    # Operating Expenses in range
    expense_qs = Expense.objects.filter(expense_date__gte=from_date, expense_date__lte=to_date)
    total_expenses = expense_qs.aggregate(tot=Sum('amount'))['tot'] or Decimal('0.00')

    # Financial Summary
    gross_revenue = total_sales + total_grinding
    total_costs = total_purchases + total_expenses
    net_profit = gross_revenue - total_costs

    # Item-wise sales breakdown
    item_sales = SaleItem.objects.filter(
        sale__sale_date__gte=from_date,
        sale__sale_date__lte=to_date,
        sale__status='COMPLETED'
    ).values('product__name', 'product__name_mr', 'product__product_type').annotate(
        total_kg=Sum('quantity_kg'),
        total_revenue=Sum('line_total')
    ).order_by('-total_revenue')

    # Production & Yield summary
    batches = ProductionBatch.objects.filter(batch_date__gte=from_date, batch_date__lte=to_date)

    # Customer outstanding balances
    top_debtors = Customer.objects.filter(
        invoices__status__in=['UNPAID', 'PARTIAL']
    ).annotate(
        due=Sum('invoices__balance_due')
    ).filter(due__gt=0).order_by('-due')[:15]

    return render(request, 'girni/reports.html', {
        'from_date': from_str,
        'to_date': to_str,
        'total_sales': total_sales,
        'total_grinding': total_grinding,
        'total_grinding_orders': total_grinding_orders,
        'total_purchases': total_purchases,
        'total_expenses': total_expenses,
        'gross_revenue': gross_revenue,
        'total_costs': total_costs,
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
    settings_obj = ShopSettings.get_settings()
    if request.method == 'POST':
        settings_obj.shop_name = request.POST.get('shop_name', settings_obj.shop_name).strip()
        settings_obj.shop_name_mr = request.POST.get('shop_name_mr', settings_obj.shop_name_mr).strip()
        settings_obj.owner_name = request.POST.get('owner_name', settings_obj.owner_name).strip()
        settings_obj.mobile = request.POST.get('mobile', settings_obj.mobile).strip()
        settings_obj.secondary_mobile = request.POST.get('secondary_mobile', '').strip()
        settings_obj.address = request.POST.get('address', settings_obj.address).strip()
        settings_obj.address_mr = request.POST.get('address_mr', settings_obj.address_mr).strip()
        settings_obj.default_language = request.POST.get('default_language', 'mr')
        settings_obj.currency_symbol = request.POST.get('currency_symbol', '₹').strip()
        settings_obj.gst_enabled = request.POST.get('gst_enabled') == 'on'
        settings_obj.gst_number = request.POST.get('gst_number', '').strip()
        settings_obj.upi_id = request.POST.get('upi_id', '').strip()
        settings_obj.footer_message = request.POST.get('footer_message', settings_obj.footer_message).strip()
        settings_obj.save()

        # Update current session language if default changed
        request.session['lang'] = settings_obj.default_language
        messages.success(request, "Shop settings saved successfully! / दुकानाची माहिती जतन झाली!")
        return redirect('shop_settings')

    return render(request, 'girni/settings.html', {'settings': settings_obj})


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


# ==========================================
# HEALTH CHECK & KEEP-ALIVE PING (ZERO COLD-START)
# ==========================================
def ping_health_view(request):
    """
    Lightweight health check and keep-alive ping endpoint.
    Returns HTTP 200 with server status in <5ms.
    Used by uptime pingers (UptimeRobot, cron-job.org) to prevent Render free-tier idle spin-down.
    """
    return JsonResponse({
        'status': 'ok',
        'app': 'ChakkiMate',
        'tagline': 'Flour Mill ERP & POS',
        'timestamp': timezone.now().isoformat(),
        'uptime_status': 'warm',
        'version': '2.0.0'
    }, status=200)
