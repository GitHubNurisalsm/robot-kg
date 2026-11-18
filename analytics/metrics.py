"""Метрики дашборда.

Каждая функция принимает Period и возвращает простые структуры — их легко
тестировать отдельно от шаблона. Все запросы ограничены периодом и топ-N;
число запросов фиксировано и не зависит от объёма данных.

Определения:
- Посетитель — visitor_id (переживает вход в аккаунт); для старых событий
  без него — session_key.
- Выручка — сумма заказов, кроме отменённых.
- Воронка нестрогая: на каждом шаге — число уникальных посетителей,
  совершивших действие в периоде.
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Avg, Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce, NullIf, TruncDate
from django.utils import timezone

from inquiries.models import ContactMessage
from orders.models import Order, OrderItem
from rentals.models import RentalRequest

from .models import Event

ALLOWED_DAYS = (7, 30, 90)
DEFAULT_DAYS = 30
TOP_N = 8
ZERO = Decimal("0")

VISITOR = Coalesce(NullIf(F("visitor_id"), Value("")), F("session_key"))


@dataclass(frozen=True)
class Period:
    days: int
    start: datetime.datetime  # включительно, полночь по Бишкеку
    end: datetime.datetime    # исключительно

    @property
    def dates(self) -> list[datetime.date]:
        first = timezone.localtime(self.start).date()
        return [first + datetime.timedelta(days=i) for i in range(self.days)]


def parse_days(raw) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return days if days in ALLOWED_DAYS else DEFAULT_DAYS


def make_period(days: int, now: datetime.datetime | None = None) -> Period:
    """Последние `days` календарных дней по местному времени, включая сегодня."""
    local_now = timezone.localtime(now or timezone.now())
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_start - datetime.timedelta(days=days - 1)
    end = today_start + datetime.timedelta(days=1)
    return Period(days=days, start=start, end=end)


def _events(period: Period):
    return Event.objects.filter(created_at__gte=period.start, created_at__lt=period.end)


def _paid_orders(period: Period):
    return Order.objects.filter(created_at__gte=period.start, created_at__lt=period.end).exclude(
        status=Order.Status.CANCELLED
    )


def _paid_items(period: Period):
    return OrderItem.objects.filter(
        order__created_at__gte=period.start, order__created_at__lt=period.end
    ).exclude(order__status=Order.Status.CANCELLED)


def _ratio(part, whole) -> float | None:
    return (part / whole) if whole else None


# ---------------------------------------------------------------------------
def kpis(period: Period) -> dict:
    orders = _paid_orders(period).aggregate(
        revenue=Coalesce(Sum("total"), ZERO), count=Count("id"), avg=Avg("total")
    )
    ev = _events(period).aggregate(
        visitors=Count(VISITOR, distinct=True),
        buyers=Count(VISITOR, distinct=True, filter=Q(event_type=Event.Type.CHECKOUT)),
    )
    cancelled = Order.objects.filter(
        created_at__gte=period.start, created_at__lt=period.end, status=Order.Status.CANCELLED
    ).count()
    return {
        "revenue": orders["revenue"],
        "orders": orders["count"],
        "avg_check": orders["avg"],
        "visitors": ev["visitors"],
        "conversion": _ratio(ev["buyers"], ev["visitors"]),
        "cancelled": cancelled,
    }


FUNNEL_STEPS = (
    (Event.Type.PRODUCT_VIEW, "Смотрели товар"),
    (Event.Type.ADD_TO_CART, "Добавили в корзину"),
    (Event.Type.CHECKOUT, "Оформили заказ"),
)


def funnel(period: Period) -> list[dict]:
    counts = _events(period).aggregate(**{
        step: Count(VISITOR, distinct=True, filter=Q(event_type=step)) for step, _ in FUNNEL_STEPS
    })
    first = counts[FUNNEL_STEPS[0][0]]
    steps, prev = [], None
    for step, label in FUNNEL_STEPS:
        n = counts[step]
        steps.append({
            "label": label,
            "count": n,
            "of_first": _ratio(n, first),
            "of_prev": _ratio(n, prev) if prev is not None else None,
        })
        prev = n
    return steps


def daily(period: Period) -> list[dict]:
    """Ряд по дням (по Бишкеку) с нулями для пустых дней."""
    tz = timezone.get_current_timezone()
    orders = {
        r["day"]: r for r in _paid_orders(period)
        .annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day").annotate(revenue=Sum("total"), count=Count("id"))
    }
    views = {
        r["day"]: r["n"] for r in _events(period).filter(event_type=Event.Type.PRODUCT_VIEW)
        .annotate(day=TruncDate("created_at", tzinfo=tz))
        .values("day").annotate(n=Count("id"))
    }
    return [
        {
            "date": d,
            "revenue": orders.get(d, {}).get("revenue") or ZERO,
            "orders": orders.get(d, {}).get("count") or 0,
            "views": views.get(d, 0),
        }
        for d in period.dates
    ]


def top_products(period: Period) -> dict:
    ev = _events(period).filter(product__isnull=False)
    views = list(
        ev.filter(event_type=Event.Type.PRODUCT_VIEW)
        .values("product_id", "product__name").annotate(n=Count("id")).order_by("-n", "product__name")[:TOP_N]
    )
    carts = {
        r["product_id"]: r["n"] for r in ev.filter(event_type=Event.Type.ADD_TO_CART)
        .values("product_id").annotate(n=Count(VISITOR, distinct=True))
    }
    viewers = {
        r["product_id"]: r["n"] for r in ev.filter(event_type=Event.Type.PRODUCT_VIEW)
        .values("product_id").annotate(n=Count(VISITOR, distinct=True))
    }
    for row in views:
        pid = row["product_id"]
        row["cart_rate"] = _ratio(carts.get(pid, 0), viewers.get(pid, 0))
    revenue = list(
        _paid_items(period).values("product_name")
        .annotate(revenue=Sum("line_total"), qty=Sum("quantity")).order_by("-revenue")[:TOP_N]
    )
    return {"by_views": views, "by_revenue": revenue}


def revenue_by_category(period: Period) -> list[dict]:
    # Ограничение: категория берётся текущая (в позиции заказа она не фиксируется).
    return list(
        _paid_items(period).values(name=F("product__category__name"))
        .annotate(revenue=Sum("line_total"), qty=Sum("quantity")).order_by("-revenue")
    )


def search(period: Period) -> dict:
    ev = _events(period).filter(event_type=Event.Type.SEARCH)
    top = list(ev.values("query").annotate(n=Count("id"), results=Avg("results_count"))
               .order_by("-n", "query")[:TOP_N])
    zero = list(ev.filter(results_count=0).values("query").annotate(n=Count("id"))
                .order_by("-n", "query")[:TOP_N])
    return {"top": top, "zero": zero, "total": ev.count()}


def rentals(period: Period) -> dict:
    qs = RentalRequest.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
    by_status_raw = dict(qs.values_list("status").annotate(n=Count("id")))
    by_status = [
        {"label": label, "status": value, "count": by_status_raw.get(value, 0)}
        for value, label in RentalRequest.Status.choices
    ]
    open_statuses = (RentalRequest.Status.NEW, RentalRequest.Status.IN_PROGRESS, RentalRequest.Status.APPROVED)
    pipeline = qs.filter(status__in=open_statuses).aggregate(s=Coalesce(Sum("estimated_total"), ZERO))["s"]
    top = list(qs.values("product__name").annotate(n=Count("id"), value=Sum("estimated_total"))
               .order_by("-n", "product__name")[:5])
    return {"by_status": by_status, "pipeline": pipeline, "total": sum(by_status_raw.values()), "top": top}


def contacts(period: Period) -> dict:
    qs = ContactMessage.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
    by_subject = list(qs.values("subject").annotate(n=Count("id")).order_by("-n", "subject"))
    return {
        "by_subject": by_subject,
        "total": sum(r["n"] for r in by_subject),
        "unprocessed": ContactMessage.objects.filter(is_processed=False).count(),  # за всё время
    }


def dashboard(period: Period) -> dict:
    return {
        "kpis": kpis(period),
        "funnel": funnel(period),
        "daily": daily(period),
        "products": top_products(period),
        "categories": revenue_by_category(period),
        "search": search(period),
        "rentals": rentals(period),
        "contacts": contacts(period),
    }
