# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import (
    Customer, Supplier, Product, StockMovement,
    Purchase, PurchaseItem, GrindingOrder,
    ProductionBatch, Sale, SaleItem, Invoice, Payment, Expense, ShopSettings
)

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'mobile', 'customer_type', 'is_active', 'created_at')
    search_fields = ('name', 'mobile', 'address')
    list_filter = ('customer_type', 'is_active')

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'mobile', 'is_active')
    search_fields = ('name', 'mobile')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'name_mr', 'product_type', 'selling_rate', 'grinding_rate', 'current_stock', 'low_stock_threshold', 'is_active')
    list_filter = ('product_type', 'is_active')
    search_fields = ('name', 'name_mr')

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'product', 'movement_type', 'quantity_kg', 'balance_after_kg', 'reference_id')
    list_filter = ('movement_type', 'stock_type')
    search_fields = ('product__name', 'reference_id')

class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('purchase_number', 'supplier', 'purchase_date', 'total', 'amount_paid', 'payment_status', 'status')
    inlines = [PurchaseItemInline]

@admin.register(GrindingOrder)
class GrindingOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'token_number', 'customer', 'grain', 'ownership_type', 'input_kg', 'charges', 'status', 'is_paid')
    list_filter = ('status', 'ownership_type', 'is_paid')
    search_fields = ('order_number', 'token_number', 'customer__name', 'customer__mobile')

@admin.register(ProductionBatch)
class ProductionBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_number', 'batch_date', 'raw_product', 'flour_product', 'input_kg', 'output_kg', 'wastage_kg', 'yield_percentage')

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ('sale_number', 'customer', 'sale_date', 'total', 'status')
    inlines = [SaleItemInline]

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'invoice_type', 'customer', 'invoice_date', 'total', 'amount_paid', 'balance_due', 'status')
    list_filter = ('status', 'invoice_type')
    search_fields = ('invoice_number', 'customer__name')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('payment_date', 'customer', 'amount', 'payment_mode', 'reference_number')
    list_filter = ('payment_mode',)

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('expense_date', 'category', 'amount', 'payment_mode', 'description')
    list_filter = ('category', 'payment_mode')

@admin.register(ShopSettings)
class ShopSettingsAdmin(admin.ModelAdmin):
    list_display = ('shop_name', 'owner_name', 'mobile', 'default_language')
