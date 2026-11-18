import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analytics.models import Event
from catalog.models import Product


class TrackingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.product = Product.objects.get(slug="armlab-a4")
        cls.detail = reverse("catalog:product_detail", kwargs={"slug": "armlab-a4"})
        cls.listing = reverse("catalog:product_list")

    def views(self):
        return Event.objects.filter(event_type=Event.Type.PRODUCT_VIEW)

    def test_product_view_tracked_with_product_and_category(self):
        self.client.get(self.detail)
        ev = self.views().get()
        self.assertEqual(ev.product, self.product)
        self.assertEqual(ev.category, self.product.category)
        self.assertTrue(ev.session_key)

    def test_refresh_not_double_counted(self):
        """Обновление страницы в течение окна не накручивает просмотры."""
        self.client.get(self.detail)
        self.client.get(self.detail)
        self.assertEqual(self.views().count(), 1)

    def test_view_counted_again_after_window(self):
        self.client.get(self.detail)
        self.views().update(created_at=timezone.now() - timedelta(minutes=31))
        self.client.get(self.detail)
        self.assertEqual(self.views().count(), 2)

    def test_different_sessions_counted_separately(self):
        self.client.get(self.detail)
        self.client_class().get(self.detail)
        self.assertEqual(self.views().count(), 2)

    def test_search_tracked_normalized_with_results(self):
        self.client.get(self.listing, {"q": "  Манипулятор   ГРАВИРОВКИ "})
        ev = Event.objects.get(event_type=Event.Type.SEARCH)
        self.assertEqual(ev.query, "манипулятор гравировки")
        self.assertEqual(ev.results_count, 1)

    def test_zero_result_search_tracked(self):
        """Поиски без результатов — ценный сигнал о спросе."""
        self.client.get(self.listing, {"q": "пылесос"})
        self.assertEqual(Event.objects.get(event_type=Event.Type.SEARCH).results_count, 0)

    def test_search_not_tracked_on_other_pages_or_without_query(self):
        self.client.get(self.listing)
        # Регрессия: page=2 при одной странице результатов прижимается к 1 — не считать.
        self.client.get(self.listing, {"q": "робот", "page": "2"})
        self.assertFalse(Event.objects.filter(event_type=Event.Type.SEARCH).exists())

    def test_staff_not_tracked(self):
        staff = get_user_model().objects.create_user("admin1", password="x-Strong-pass-1", is_staff=True)
        self.client.force_login(staff)
        self.client.get(self.detail)
        self.assertFalse(self.views().exists())

    def test_authenticated_user_linked(self):
        user = get_user_model().objects.create_user("buyer", password="x-Strong-pass-1")
        self.client.force_login(user)
        self.client.get(self.detail)
        self.assertEqual(self.views().get().user, user)

    def test_tracking_failure_does_not_break_page(self):
        with mock.patch("analytics.services.Event.objects.create", side_effect=DatabaseError("boom")), \
             self.assertLogs("analytics.services", level="ERROR"):
            resp = self.client.get(self.detail)
        self.assertEqual(resp.status_code, 200)

    def test_product_deletion_keeps_history(self):
        self.client.get(self.detail)
        self.product.specs.all().delete()
        self.product.delete()
        self.assertIsNone(self.views().get().product)


# ===========================================================================
# Этап 8: visitor_id, фильтр ботов, метрики, дашборд, CSV, демо-данные
# ===========================================================================
import csv as _csv
import datetime as _dt
import io as _io
import uuid as _uuid
from decimal import Decimal as _D

from django.contrib.auth.models import Permission
from django.test import Client as _Client

from analytics import metrics
from analytics.charts import column_chart, line_chart, pct
from analytics.management.commands.seed_analytics import DEMO_PREFIX, DEMO_USERNAME
from analytics.views import safe_cell
from inquiries.models import ContactMessage
from orders.models import Order, OrderItem

PW = "Robo-Strong-Pass-2026"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"


def make_order(user, product, qty=1, status=Order.Status.NEW, when=None):
    o = Order.objects.create(number=f"RB-T{_uuid.uuid4().hex[:7].upper()}", user=user, full_name="x",
                             phone="+996555000000", email="x@e.com", total=product.price * qty,
                             status=status, checkout_token=_uuid.uuid4())
    OrderItem.objects.create(order=o, product=product, product_name=product.name,
                             unit_price=product.price, quantity=qty, line_total=product.price * qty)
    if when:
        Order.objects.filter(pk=o.pk).update(created_at=when)
    return o


class VisitorAndBotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.user = get_user_model().objects.create_user("buyer", "b@example.com", PW)
        cls.detail = reverse("catalog:product_detail", kwargs={"slug": "stembot-go"})

    def test_visitor_survives_login(self):
        """Регрессия воронки: login() меняет session_key, но visitor_id сохраняется."""
        self.client.get(self.detail)
        before = Event.objects.get()
        self.client.post(reverse("accounts:login"), {"username": "buyer", "password": PW})
        p = Product.objects.get(slug="stembot-go")
        self.client.post(reverse("cart:add", args=[p.pk]), {"quantity": 1})
        after = Event.objects.get(event_type=Event.Type.ADD_TO_CART)
        self.assertNotEqual(before.session_key, after.session_key)
        self.assertEqual(before.visitor_id, after.visitor_id)
        self.assertTrue(before.visitor_id)

    def test_view_dedup_survives_login(self):
        self.client.get(self.detail)
        self.client.post(reverse("accounts:login"), {"username": "buyer", "password": PW})
        self.client.get(self.detail)
        self.assertEqual(Event.objects.filter(event_type=Event.Type.PRODUCT_VIEW).count(), 1)

    def test_bots_not_tracked(self):
        for ua in ("Googlebot/2.1 (+http://www.google.com/bot.html)", "curl/8.4.0",
                   "python-requests/2.31", "Mozilla/5.0 HeadlessChrome/120"):
            with self.subTest(ua=ua):
                _Client(HTTP_USER_AGENT=ua).get(self.detail)
        self.assertFalse(Event.objects.exists())

    def test_real_browser_tracked(self):
        _Client(HTTP_USER_AGENT=BROWSER_UA).get(self.detail)
        self.assertEqual(Event.objects.count(), 1)

    def test_empty_user_agent_still_tracked(self):
        """Осознанное решение: пустой UA не считаем ботом (приватные браузеры)."""
        self.client.get(self.detail)
        self.assertEqual(Event.objects.count(), 1)


class MetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.user = get_user_model().objects.create_user("buyer", "b@example.com", PW)
        cls.go = Product.objects.get(slug="stembot-go")      # 18 900, education
        cls.arm = Product.objects.get(slug="armlab-a4")      # 145 000, industrial

    def setUp(self):
        self.period = metrics.make_period(7)

    def ev(self, vid, etype, product=None, **kw):
        return Event.objects.create(event_type=etype, visitor_id=vid, session_key=vid, product=product,
                                    category=product.category if product else None, **kw)

    def test_revenue_excludes_cancelled(self):
        make_order(self.user, self.go, 2)
        make_order(self.user, self.arm, 1)
        make_order(self.user, self.arm, 3, status=Order.Status.CANCELLED)
        k = metrics.kpis(self.period)
        self.assertEqual(k["revenue"], _D("18900") * 2 + _D("145000"))
        self.assertEqual((k["orders"], k["cancelled"]), (2, 1))
        self.assertEqual(k["avg_check"], (_D("37800") + _D("145000")) / 2)

    def test_funnel_counts_unique_visitors(self):
        for vid in ("a", "b", "c", "d"):
            self.ev(vid, Event.Type.PRODUCT_VIEW, self.go)
        self.ev("a", Event.Type.PRODUCT_VIEW, self.arm)   # второй просмотр того же посетителя
        self.ev("a", Event.Type.ADD_TO_CART, self.go)
        self.ev("b", Event.Type.ADD_TO_CART, self.go)
        self.ev("a", Event.Type.CHECKOUT)
        steps = metrics.funnel(self.period)
        self.assertEqual([s["count"] for s in steps], [4, 2, 1])
        self.assertEqual((steps[1]["of_prev"], steps[2]["of_prev"], steps[2]["of_first"]), (0.5, 0.5, 0.25))

    def test_funnel_old_events_fallback_to_session_key(self):
        Event.objects.create(event_type=Event.Type.PRODUCT_VIEW, session_key="old", visitor_id="", product=self.go)
        Event.objects.create(event_type=Event.Type.PRODUCT_VIEW, session_key="old", visitor_id="", product=self.arm)
        self.assertEqual(metrics.funnel(self.period)[0]["count"], 1)

    def test_conversion(self):
        for vid in "abcd":
            self.ev(vid, Event.Type.PRODUCT_VIEW, self.go)
        self.ev("a", Event.Type.CHECKOUT)
        self.assertEqual(metrics.kpis(self.period)["conversion"], 0.25)

    def test_empty_db_no_division_by_zero(self):
        data = metrics.dashboard(self.period)
        self.assertIsNone(data["kpis"]["conversion"])
        self.assertIsNone(data["kpis"]["avg_check"])
        self.assertEqual(data["kpis"]["revenue"], 0)
        self.assertEqual(len(data["daily"]), 7)
        self.assertTrue(all(d["revenue"] == 0 for d in data["daily"]))

    def test_period_boundaries_in_local_timezone(self):
        """Заказ в 00:30 по Бишкеку относится к «сегодня», хотя в UTC это ещё вчера."""
        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        just_after_midnight = _dt.datetime.combine(today, _dt.time(0, 30), tzinfo=tz)
        before_period = _dt.datetime.combine(today - _dt.timedelta(days=7), _dt.time(23, 59), tzinfo=tz)
        make_order(self.user, self.go, 1, when=just_after_midnight)
        make_order(self.user, self.arm, 1, when=before_period)
        daily = metrics.daily(self.period)
        self.assertEqual(daily[-1]["date"], today)
        self.assertEqual(daily[-1]["orders"], 1)
        self.assertEqual(metrics.kpis(self.period)["orders"], 1)  # заказ за 8 дней до — вне периода

    def test_top_products_and_cart_rate(self):
        for vid in "abcd":
            self.ev(vid, Event.Type.PRODUCT_VIEW, self.go)
        self.ev("a", Event.Type.PRODUCT_VIEW, self.arm)
        self.ev("a", Event.Type.ADD_TO_CART, self.go)
        top = metrics.top_products(self.period)["by_views"]
        self.assertEqual(top[0]["product__name"], "STEMBot Go")
        self.assertEqual(top[0]["cart_rate"], 0.25)

    def test_revenue_by_category_and_product(self):
        make_order(self.user, self.go, 2)
        make_order(self.user, self.arm, 1)
        make_order(self.user, self.arm, 5, status=Order.Status.CANCELLED)
        cats = {r["name"]: r["revenue"] for r in metrics.revenue_by_category(self.period)}
        self.assertEqual(cats, {"Манипуляторы": _D("145000"), "Образовательные роботы": _D("37800")})
        top = metrics.top_products(self.period)["by_revenue"]
        self.assertEqual(top[0]["product_name"], "ArmLab A4")

    def test_zero_result_searches(self):
        self.ev("a", Event.Type.SEARCH, query="пылесос", results_count=0)
        self.ev("b", Event.Type.SEARCH, query="пылесос", results_count=0)
        self.ev("c", Event.Type.SEARCH, query="дрон", results_count=2)
        s = metrics.search(self.period)
        self.assertEqual(s["zero"], [{"query": "пылесос", "n": 2}])
        self.assertEqual(s["total"], 3)

    def test_parse_days_whitelist(self):
        for raw, expected in (("7", 7), ("90", 90), ("abc", 30), ("9999", 30), (None, 30), ("-7", 30)):
            self.assertEqual(metrics.parse_days(raw), expected)


class ChartTests(TestCase):
    def test_column_specs(self):
        days = [(_dt.date(2026, 11, d), v) for d, v in ((1, 0), (2, 100), (3, 50))]
        c = column_chart(days)
        self.assertEqual(c["bars"][0]["path"], "")          # ноль — без столбца
        self.assertIn("Q", c["bars"][1]["path"])            # скруглённый верх
        self.assertEqual(c["peak"]["text"], "100")
        self.assertFalse(c["empty"])

    def test_bar_width_capped(self):
        c = column_chart([(_dt.date(2026, 11, 1), 5)])
        # Единственный столбец не шире 24px.
        import re
        xs = [float(x) for x in re.findall(r"[MH]([\d.]+)", c["bars"][0]["path"])]
        self.assertLessEqual(max(xs) - min(xs), 24.01)

    def test_line_and_empty(self):
        days = [(_dt.date(2026, 11, d), 0) for d in range(1, 8)]
        self.assertTrue(line_chart(days)["empty"])
        self.assertTrue(column_chart(days)["empty"])

    def test_pct(self):
        self.assertEqual((pct(None), pct(0.25), pct(0.1234), pct(1)), ("—", "25 %", "12,3 %", "100 %"))


class DashboardAccessTests(TestCase):
    url = reverse("analytics:dashboard")

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        U = get_user_model()
        cls.customer = U.objects.create_user("customer", "c@example.com", PW)
        cls.staff_no_perm = U.objects.create_user("staff", "s@example.com", PW, is_staff=True)
        cls.manager = U.objects.create_user("manager", "m@example.com", PW, is_staff=True)
        cls.manager.user_permissions.add(Permission.objects.get(codename="view_dashboard"))
        cls.admin = U.objects.create_superuser("boss", "boss@example.com", PW)

    def as_user(self, user):
        c = _Client()
        c.force_login(user)
        return c

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(self.url)
        self.assertRedirects(resp, f"{reverse('accounts:login')}?next={self.url}")

    def test_without_permission_403(self):
        for user in (self.customer, self.staff_no_perm):
            with self.subTest(user=user.username):
                self.assertEqual(self.as_user(user).get(self.url).status_code, 403)

    def test_with_permission_200(self):
        for user in (self.manager, self.admin):
            with self.subTest(user=user.username):
                self.assertEqual(self.as_user(user).get(self.url).status_code, 200)

    def test_csv_exports_protected(self):
        for name in ("analytics:export_events", "analytics:export_order_items"):
            with self.subTest(name):
                self.assertEqual(self.as_user(self.customer).get(reverse(name)).status_code, 403)
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_header_link_only_for_permitted_staff(self):
        home = reverse("core:home")
        self.assertContains(self.as_user(self.manager).get(home), 'href="/analytics/"')
        self.assertNotContains(self.as_user(self.customer).get(home), 'href="/analytics/"')
        self.assertNotContains(self.as_user(self.staff_no_perm).get(home), 'href="/analytics/"')

    def test_customer_header_has_no_extra_permission_queries(self):
        """Регрессия производительности: у покупателя шапка не проверяет права."""
        c = self.as_user(self.customer)
        c.get(reverse("core:home"))
        with self.assertNumQueries(5):  # сессия + пользователь + главная (3)
            c.get(reverse("core:home"))

    def test_empty_db_renders(self):
        resp = self.as_user(self.admin).get(self.url)
        self.assertContains(resp, "Нет данных за период", status_code=200)
        self.assertContains(resp, "—")  # конверсия без базы

    def test_bad_days_param_falls_back(self):
        resp = self.as_user(self.admin).get(self.url, {"days": "100000"})
        self.assertEqual(resp.context["period"].days, 30)

    def test_query_count_constant_with_data(self):
        """Число запросов не растёт с объёмом данных (нет N+1)."""
        c = self.as_user(self.admin)
        c.get(self.url)
        with self.assertNumQueries(21) as _:
            c.get(self.url)
        call_command("seed_analytics", "--days", "14", "--visitors", "15", stdout=io.StringIO())
        with self.assertNumQueries(21):
            c.get(self.url)

    def test_svg_coordinates_not_localized(self):
        """Регрессия: русская локаль печатала y="148,0" — невалидные координаты SVG."""
        import re
        call_command("seed_analytics", "--days", "7", "--visitors", "10", stdout=io.StringIO())
        html = self.as_user(self.admin).get(self.url, {"days": 7}).content.decode()
        coords = re.findall(r'\s(?:x|y|x1|x2|y1|y2|cx|cy|width|height)="([^"]*)"', html)
        self.assertTrue(coords)
        self.assertFalse([c for c in coords if "," in c])

    def test_user_text_escaped(self):
        Event.objects.create(event_type=Event.Type.SEARCH, visitor_id="x", query="<script>alert(1)</script>",
                             results_count=0)
        resp = self.as_user(self.admin).get(self.url)
        self.assertNotContains(resp, "<script>alert(1)</script>")
        self.assertContains(resp, "&lt;script&gt;")


class CsvExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.admin = get_user_model().objects.create_superuser("boss", "boss@example.com", PW)
        cls.buyer = get_user_model().objects.create_user("buyer", "secret-buyer@example.com", PW)

    def setUp(self):
        self.client.force_login(self.admin)

    def read(self, name, **params):
        resp = self.client.get(reverse(name), params)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment;", resp["Content-Disposition"])
        body = b"".join(resp.streaming_content).decode("utf-8")
        self.assertTrue(body.startswith("﻿"))
        return list(_csv.reader(_io.StringIO(body.lstrip("﻿"))))

    def test_events_export(self):
        p = Product.objects.get(slug="stembot-go")
        Event.objects.create(event_type=Event.Type.PRODUCT_VIEW, visitor_id="v1", product=p, category=p.category)
        rows = self.read("analytics:export_events", days=7)
        self.assertEqual(rows[0][:3], ["created_at", "event_type", "visitor"])
        self.assertEqual(rows[1][1:3], ["product_view", "v1"])
        self.assertEqual(rows[1][5], "STEMBot Go")

    def test_csv_formula_injection_neutralized(self):
        Event.objects.create(event_type=Event.Type.SEARCH, visitor_id="v", query='=HYPERLINK("http://evil")',
                             results_count=0)
        rows = self.read("analytics:export_events")
        self.assertTrue(rows[1][7].startswith("'="))
        self.assertEqual((safe_cell("+1"), safe_cell("@x"), safe_cell("ok"), safe_cell(5), safe_cell(None)),
                         ("'+1", "'@x", "ok", 5, ""))

    def test_order_items_export_has_no_pii(self):
        make_order(self.buyer, Product.objects.get(slug="armlab-a4"), 2)
        rows = self.read("analytics:export_order_items")
        flat = ",".join(",".join(r) for r in rows)
        self.assertEqual(rows[1][6], "ArmLab A4")
        self.assertNotIn("secret-buyer@example.com", flat)
        self.assertNotIn("+996555000000", flat)
        self.assertNotIn("x@e.com", flat)

    def test_period_filter(self):
        old = Event.objects.create(event_type=Event.Type.CONTACT, visitor_id="old")
        Event.objects.filter(pk=old.pk).update(created_at=timezone.now() - _dt.timedelta(days=40))
        Event.objects.create(event_type=Event.Type.CONTACT, visitor_id="new")
        rows = self.read("analytics:export_events", days=30)
        self.assertEqual([r[2] for r in rows[1:]], ["new"])


class SeedAnalyticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())

    def test_seed_marks_and_clear_removes_only_demo(self):
        p = Product.objects.get(slug="stembot-go")
        stock_before = dict(Product.objects.values_list("slug", "stock"))
        real_user = get_user_model().objects.create_user("real", "r@example.com", PW)
        real_event = Event.objects.create(event_type=Event.Type.PRODUCT_VIEW, visitor_id="real-visitor", product=p)
        real_order = make_order(real_user, p, 1)
        real_msg = ContactMessage.objects.create(name="R", email="r@example.com", subject="Другое", message="x" * 20)

        call_command("seed_analytics", "--days", "10", "--visitors", "10", stdout=io.StringIO())
        demo_user = get_user_model().objects.get(username=DEMO_USERNAME)
        self.assertFalse(demo_user.is_active)
        self.assertFalse(demo_user.has_usable_password())
        self.assertTrue(Event.objects.filter(visitor_id__startswith=DEMO_PREFIX).exists())
        self.assertTrue(Order.objects.filter(user=demo_user).exists())
        self.assertEqual(dict(Product.objects.values_list("slug", "stock")), stock_before)  # склад не тронут

        call_command("seed_analytics", "--clear", stdout=io.StringIO())
        self.assertFalse(Event.objects.filter(visitor_id__startswith=DEMO_PREFIX).exists())
        self.assertFalse(get_user_model().objects.filter(username=DEMO_USERNAME).exists())
        for obj in (real_event, real_order, real_msg, real_user):
            self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists(), obj)

    def test_deterministic_and_rerun_replaces(self):
        call_command("seed_analytics", "--days", "5", "--visitors", "8", stdout=io.StringIO())
        first = (Event.objects.count(), Order.objects.count())
        call_command("seed_analytics", "--days", "5", "--visitors", "8", stdout=io.StringIO())
        self.assertEqual(first, (Event.objects.count(), Order.objects.count()))

    def test_demo_order_totals_match_items(self):
        call_command("seed_analytics", "--days", "10", "--visitors", "20", stdout=io.StringIO())
        from django.db.models import Sum
        for o in Order.objects.annotate(s=Sum("items__line_total")):
            self.assertEqual(o.total, o.s)
