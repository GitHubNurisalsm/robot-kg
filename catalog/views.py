from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, reverse

from analytics.models import Event
from analytics.services import track
from cart.cart import Cart

from .forms import SORT_ORDERING, ProductFilterForm
from .models import Product

PAGE_SIZE = 12
RELATED_LIMIT = 4
MAX_SEARCH_TERMS = 5


def filter_products(queryset, data: dict):
    """Применяет только валидные фильтры из cleaned_data формы."""
    q = (data.get("q") or "").strip()
    if q:
        # Каждое слово должно встречаться (AND); число слов ограничено.
        for term in q.lower().split()[:MAX_SEARCH_TERMS]:
            queryset = queryset.filter(search_index__contains=term)
    if data.get("category"):
        queryset = queryset.filter(category=data["category"])
    if data.get("min_price") is not None:
        queryset = queryset.filter(price__gte=data["min_price"])
    if data.get("max_price") is not None:
        queryset = queryset.filter(price__lte=data["max_price"])
    if data.get("in_stock"):
        queryset = queryset.filter(stock__gt=0)
    if data.get("rentable"):
        queryset = queryset.filter(is_rentable=True)
    ordering = SORT_ORDERING.get(data.get("sort") or "new", SORT_ORDERING["new"])
    return queryset.order_by(*ordering)


def product_list(request):
    form = ProductFilterForm(request.GET or None)
    data = {}
    if form.is_bound:
        form.is_valid()
        # cleaned_data содержит только валидные поля: невалидный фильтр
        # отбрасывается (и показывается ошибка), остальные продолжают работать.
        data = form.cleaned_data

    products = filter_products(Product.objects.available().select_related("category"), data)
    page_obj = Paginator(products, PAGE_SIZE).get_page(request.GET.get("page"))

    q = (data.get("q") or "").strip()
    # Считаем поиск по запрошенной странице, а не по фактической:
    # get_page() прижимает ?page=99 к последней странице, и было бы двойное засчитывание.
    first_page_requested = request.GET.get("page", "1") in ("", "1")
    if q and first_page_requested:
        track(request, Event.Type.SEARCH, query=q, results_count=page_obj.paginator.count,
              category=data.get("category"))

    # Параметры фильтра без page — для ссылок пагинации.
    params = request.GET.copy()
    params.pop("page", None)

    return render(
        request,
        "catalog/product_list.html",
        {
            "form": form,
            "page_obj": page_obj,
            "products": page_obj.object_list,
            "active_category": data.get("category"),
            "querystring": params.urlencode(),
            "has_filters": any(v not in (None, "", False) for k, v in data.items() if k != "sort"),
        },
    )


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.available().select_related("category").prefetch_related("specs"),
        slug=slug,
    )
    related = (
        Product.objects.available()
        .filter(category=product.category)
        .exclude(pk=product.pk)
        .select_related("category")
        .order_by("-is_featured", "-created_at")[:RELATED_LIMIT]
    )
    track(request, Event.Type.PRODUCT_VIEW, product=product, category=product.category)

    try:
        cart_add_url = reverse("cart:add", kwargs={"product_id": product.pk})
    except NoReverseMatch:
        cart_add_url = None  # корзина подключается на этапе 3

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "related_products": related,
            "cart_add_url": cart_add_url,
            "in_cart_qty": Cart(request).quantity_of(product.pk),
        },
    )
