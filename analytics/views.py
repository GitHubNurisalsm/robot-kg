import csv

from django.contrib.auth.decorators import login_required, permission_required
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone

from orders.models import OrderItem

from . import charts, metrics
from .models import Event

PERM = "analytics.view_dashboard"
EXPORT_CHUNK = 2000
# Ячейки, начинающиеся с этих символов, Excel/LibreOffice выполнят как формулу.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def staff_dashboard(view):
    # Аноним → страница входа; вошедший без права → 403.
    return login_required(permission_required(PERM, raise_exception=True)(view))


@staff_dashboard
def dashboard(request):
    period = metrics.make_period(metrics.parse_days(request.GET.get("days")))
    data = metrics.dashboard(period)
    daily = data["daily"]
    for step in data["funnel"]:
        step["of_prev_pct"] = charts.pct(step["of_prev"])
        step["of_first_pct"] = charts.pct(step["of_first"])
    for row in data["products"]["by_views"]:
        row["extra"] = f"в корзину: {charts.pct(row['cart_rate'])}"
    ctx = {
        "conversion_pct": charts.pct(data["kpis"]["conversion"]),
        **data,
        "period": period,
        "allowed_days": metrics.ALLOWED_DAYS,
        "revenue_chart": charts.column_chart([(r["date"], r["revenue"]) for r in daily], " сом"),
        "views_chart": charts.line_chart([(r["date"], r["views"]) for r in daily], " просм."),
        "funnel_rows": charts.bar_rows(data["funnel"], "count", "label"),
        "views_rows": charts.bar_rows(data["products"]["by_views"], "n", "product__name"),
        "revenue_rows": charts.bar_rows(data["products"]["by_revenue"], "revenue", "product_name", money=True),
        "category_rows": charts.bar_rows(data["categories"], "revenue", "name", money=True),
        "rental_rows": charts.bar_rows(data["rentals"]["by_status"], "count", "label"),
        "contact_rows": charts.bar_rows(data["contacts"]["by_subject"], "n", "subject"),
    }
    return render(request, "analytics/dashboard.html", ctx)


# ---------------------------------------------------------------------------
class _Echo:
    def write(self, value):
        return value


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value  # защита от CSV/формульной инъекции
    return value


def _stream_csv(filename: str, header: list[str], rows):
    writer = csv.writer(_Echo())

    def generate():
        yield "﻿"  # BOM: Excel корректно откроет кириллицу
        yield writer.writerow(header)
        for row in rows:
            yield writer.writerow([safe_cell(v) for v in row])

    response = StreamingHttpResponse(generate(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _local(dt):
    return timezone.localtime(dt).isoformat(timespec="seconds")


@staff_dashboard
def export_events(request):
    """Сырые события за период. Без персональных данных: посетитель — псевдоним."""
    period = metrics.make_period(metrics.parse_days(request.GET.get("days")))
    qs = (Event.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
          .select_related("product", "category").order_by("created_at", "id"))
    rows = (
        (_local(e.created_at), e.event_type, e.visitor_id or e.session_key, e.user_id or "",
         e.product_id or "", e.product.name if e.product else "",
         e.category.name if e.category else "", e.query, e.results_count, e.quantity, e.value)
        for e in qs.iterator(chunk_size=EXPORT_CHUNK)
    )
    header = ["created_at", "event_type", "visitor", "user_id", "product_id", "product_name",
              "category", "query", "results_count", "quantity", "value"]
    return _stream_csv(f"events_{period.days}d_{timezone.localdate():%Y%m%d}.csv", header, rows)


@staff_dashboard
def export_order_items(request):
    """Позиции заказов за период. Имена, телефоны и email покупателей не выгружаются."""
    period = metrics.make_period(metrics.parse_days(request.GET.get("days")))
    qs = (OrderItem.objects.filter(order__created_at__gte=period.start, order__created_at__lt=period.end)
          .select_related("order", "product__category").order_by("order__created_at", "id"))
    rows = (
        (i.order.number, _local(i.order.created_at), i.order.status, i.order.delivery_method,
         i.order.user_id or "", i.product_id, i.product_name, i.product.category.name,
         i.unit_price, i.quantity, i.line_total)
        for i in qs.iterator(chunk_size=EXPORT_CHUNK)
    )
    header = ["order_number", "created_at", "status", "delivery_method", "user_id", "product_id",
              "product_name", "category", "unit_price", "quantity", "line_total"]
    return _stream_csv(f"order_items_{period.days}d_{timezone.localdate():%Y%m%d}.csv", header, rows)
