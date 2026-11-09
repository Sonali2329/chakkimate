# -*- coding: utf-8 -*-
from django.urls import path
from . import views

urlpatterns = [
    # Auth & Language
    path('login/', views.girni_login_view, name='girni_login'),
    path('logout/', views.girni_logout_view, name='girni_logout'),
    path('set-language/<str:lang>/', views.set_language_view, name='set_language'),

    # Dashboard
    path('', views.dashboard_view, name='dashboard'),

    # Customers
    path('customers/', views.customer_list_view, name='customer_list'),
    path('customers/new/', views.customer_create_view, name='customer_create'),
    path('customers/<int:customer_id>/', views.customer_detail_view, name='customer_detail'),
    path('customers/<int:customer_id>/edit/', views.customer_edit_view, name='customer_edit'),

    # Suppliers
    path('suppliers/', views.supplier_list_view, name='supplier_list'),
    path('suppliers/new/', views.supplier_create_view, name='supplier_create'),
    path('suppliers/<int:supplier_id>/', views.supplier_detail_view, name='supplier_detail'),
    path('suppliers/<int:supplier_id>/edit/', views.supplier_edit_view, name='supplier_edit'),

    # Products & Grains
    path('products/', views.product_list_view, name='product_list'),
    path('products/new/', views.product_create_view, name='product_create'),
    path('products/<int:product_id>/edit/', views.product_edit_view, name='product_edit'),

    # Purchases
    path('purchases/', views.purchase_list_view, name='purchase_list'),
    path('purchases/new/', views.purchase_create_view, name='purchase_create'),
    path('purchases/<int:purchase_id>/', views.purchase_detail_view, name='purchase_detail'),

    # Stock & Inventory
    path('stock/', views.stock_summary_view, name='stock_summary'),
    path('stock/ledger/', views.stock_ledger_view, name='stock_ledger'),
    path('stock/adjust/', views.stock_adjust_view, name='stock_adjust'),

    # Grinding Orders
    path('grinding/', views.grinding_order_list_view, name='grinding_order_list'),
    path('grinding/new/', views.grinding_order_create_view, name='grinding_order_create'),
    path('grinding/<int:order_id>/', views.grinding_order_detail_view, name='grinding_order_detail'),
    path('grinding/<int:order_id>/status/', views.grinding_order_status_update_view, name='grinding_order_status'),

    # Own Production Batches
    path('production/', views.production_list_view, name='production_list'),
    path('production/new/', views.production_create_view, name='production_create'),

    # Sales
    path('sales/', views.sale_list_view, name='sale_list'),
    path('sales/new/', views.sale_create_view, name='sale_create'),

    # Invoices & Billing
    path('invoices/', views.invoice_list_view, name='invoice_list'),
    path('invoices/<int:invoice_id>/', views.invoice_detail_view, name='invoice_detail'),
    path('invoices/<int:invoice_id>/pdf/', views.invoice_pdf_view, name='invoice_pdf'),
    path('payments/', views.payment_list_view, name='payment_list'),
    path('payments/record/', views.record_payment_view, name='record_payment'),

    # Expenses
    path('expenses/', views.expense_list_view, name='expense_list'),
    path('expenses/new/', views.expense_create_view, name='expense_create'),

    # Reports
    path('reports/', views.reports_view, name='reports'),

    # Settings
    path('settings/', views.shop_settings_view, name='shop_settings'),

    # PWA Endpoints
    path('manifest.json', views.manifest_view, name='pwa_manifest'),
    path('service-worker.js', views.service_worker_view, name='pwa_service_worker'),
    path('offline/', views.offline_view, name='pwa_offline'),
]
