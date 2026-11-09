# -*- coding: utf-8 -*-
from decimal import Decimal
from django.db.models import F
from django.utils import timezone
from .models import ShopSettings, Product, GrindingOrder
from .translations import TRANSLATIONS, get_text

def chakkimate_context(request):
    """
    Context processor providing active language, translation dictionary,
    shop settings, low stock alerts, and quick count metrics to all templates.
    """
    try:
        settings = ShopSettings.get_settings()
    except Exception:
        settings = None
    
    current_lang = 'mr'
    if hasattr(request, 'session'):
        current_lang = request.session.get('lang', settings.default_language if settings else 'mr')
    if current_lang not in ('mr', 'en'):
        current_lang = 'mr'

    tr_dict = TRANSLATIONS.get(current_lang, TRANSLATIONS['mr'])

    pending_grinding = 0
    low_stock_count = 0
    try:
        pending_grinding = GrindingOrder.objects.filter(status__in=['PENDING', 'IN_PROGRESS']).count()
        low_stock_count = Product.objects.filter(is_active=True, current_stock__lte=F('low_stock_threshold')).count()
    except Exception:
        pass

    return {
        'shop_settings': settings,
        'current_lang': current_lang,
        'tr': tr_dict,
        'pending_grinding_badge_count': pending_grinding,
        'low_stock_badge_count': low_stock_count,
        'now_date': timezone.now().date(),
    }
