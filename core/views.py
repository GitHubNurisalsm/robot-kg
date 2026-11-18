from django.db.models import Count, Q
from django.shortcuts import render

from catalog.models import Category, Product

FEATURED_LIMIT = 8


def home(request):
    featured = Product.objects.featured().select_related("category")[:FEATURED_LIMIT]
    categories = Category.objects.active().annotate(
        product_count=Count("products", filter=Q(products__is_available=True))
    )
    return render(
        request,
        "core/home.html",
        {
            "featured_products": featured,
            "categories": categories,
            "product_total": Product.objects.available().count(),
        },
    )
