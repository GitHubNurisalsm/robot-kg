from django.conf import settings
from urllib.parse import urlencode

from django.urls import NoReverseMatch, reverse

# (url name, подпись). Пункт без зарегистрированного маршрута показывается
# как «скоро» — разделы подключаются поэтапно, и навигация не ломается.
NAV_ITEMS = (
    ("core:home", "Главная"),
    ("catalog:product_list", "Каталог"),
    ("rentals:rental", "Аренда"),
    ("inquiries:contact", "Контакты"),
)


def _safe_reverse(name: str):
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


def _with_next(url, request):
    """Ссылка на вход/регистрацию возвращает пользователя туда, где он был."""
    if not url or request.path.startswith("/accounts/"):
        return url
    return f"{url}?{urlencode({'next': request.get_full_path()})}"


def site(request):
    current = request.path
    nav = []
    for name, label in NAV_ITEMS:
        url = _safe_reverse(name)
        nav.append(
            {
                "label": label,
                "url": url,
                "active": bool(url) and (current == url if url == "/" else current.startswith(url)),
            }
        )
    return {
        "brand": settings.SITE_BRAND,
        "nav_items": nav,
        "cart_url": _safe_reverse("cart:detail"),
        "login_url": _with_next(_safe_reverse("accounts:login"), request),
        "logout_url": _safe_reverse("accounts:logout"),
        "signup_url": _with_next(_safe_reverse("accounts:signup"), request),
    }
