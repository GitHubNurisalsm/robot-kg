import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from analytics.models import Event
from cart.cart import MAX_LINES, SESSION_KEY
from catalog.models import Category, Product


class CartTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.arm = Product.objects.get(slug="armlab-a4")       # stock 4, 145 000
        cls.go = Product.objects.get(slug="stembot-go")       # stock 40, 18 900
        cls.racer = Product.objects.get(slug="skyedu-racer")  # stock 0

    def add(self, product, qty=1, **extra):
        return self.client.post(reverse("cart:add", args=[product.pk]), {"quantity": qty, **extra})

    def session_cart(self):
        return self.client.session.get(SESSION_KEY, {})

    def msgs(self, resp):
        return [str(m) for m in resp.wsgi_request._messages]


class AddTests(CartTestBase):
    def test_add_happy_path(self):
        resp = self.add(self.go, 2)
        self.assertRedirects(resp, reverse("cart:detail"))
        self.assertEqual(self.session_cart(), {str(self.go.pk): 2})

    def test_add_accumulates(self):
        self.add(self.go, 2)
        self.add(self.go, 3)
        self.assertEqual(self.session_cart()[str(self.go.pk)], 5)

    def test_quick_add_without_quantity_defaults_to_one(self):
        self.client.post(reverse("cart:add", args=[self.go.pk]))
        self.assertEqual(self.session_cart()[str(self.go.pk)], 1)

    def test_get_not_allowed(self):
        """Изменение состояния только через POST (защита от CSRF через <img src>)."""
        resp = self.client.get(reverse("cart:add", args=[self.go.pk]))
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(self.session_cart(), {})

    def test_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        resp = client.post(reverse("cart:add", args=[self.go.pk]), {"quantity": 1})
        self.assertEqual(resp.status_code, 403)

    def test_quantity_clamped_to_stock(self):
        resp = self.add(self.arm, 10, next=reverse("cart:detail"))
        self.assertEqual(self.session_cart()[str(self.arm.pk)], 4)
        self.assertTrue(any("больше нет на складе" in m for m in self.msgs(resp)))

    def test_repeated_add_cannot_exceed_stock(self):
        """Регрессия: повторные добавления по 3 шт. не обходят остаток 4."""
        self.add(self.arm, 3)
        self.add(self.arm, 3)
        self.assertEqual(self.session_cart()[str(self.arm.pk)], 4)

    def test_out_of_stock_refused(self):
        self.add(self.racer, 1)
        self.assertEqual(self.session_cart(), {})

    def test_unavailable_or_missing_product_404(self):
        Product.objects.filter(pk=self.go.pk).update(is_available=False)
        self.assertEqual(self.add(self.go).status_code, 404)
        self.assertEqual(self.client.post(reverse("cart:add", args=[999999])).status_code, 404)

    def test_invalid_quantity_rejected_without_change(self):
        for bad in ("0", "-3", "abc", "100", "1.5", ""):
            with self.subTest(qty=bad):
                resp = self.add(self.go, bad)
                self.assertEqual(resp.status_code, 302)
                self.assertNotIn(str(self.go.pk), self.session_cart())

    def test_open_redirect_blocked(self):
        resp = self.add(self.go, 1, next="https://evil.example/phish")
        self.assertRedirects(resp, reverse("cart:detail"))
        resp = self.add(self.go, 1, next="//evil.example/")
        self.assertRedirects(resp, reverse("cart:detail"))

    def test_safe_next_respected(self):
        url = reverse("catalog:product_detail", kwargs={"slug": self.go.slug})
        resp = self.add(self.go, 1, next=url)
        self.assertRedirects(resp, url)

    def test_max_lines_bound(self):
        cat = Category.objects.get(slug="kits")
        products = [
            Product.objects.create(category=cat, name=f"Bulk {i}", slug=f"bulk-{i}",
                                   short_description="s", description="d",
                                   price=Decimal("10"), stock=5)
            for i in range(MAX_LINES + 1)
        ]
        for p in products[:MAX_LINES]:
            self.add(p)
        self.assertEqual(len(self.session_cart()), MAX_LINES)
        self.add(products[-1])
        self.assertEqual(len(self.session_cart()), MAX_LINES)
        # Существующую позицию увеличить по-прежнему можно.
        self.add(products[0])
        self.assertEqual(self.session_cart()[str(products[0].pk)], 2)


class DetailTests(CartTestBase):
    def test_empty_cart(self):
        resp = self.client.get(reverse("cart:detail"))
        self.assertContains(resp, "Корзина пуста")

    def test_total_calculated(self):
        self.add(self.go, 2)
        self.add(self.arm, 1)
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual(resp.context["cart"].total, Decimal("18900") * 2 + Decimal("145000"))
        self.assertContains(resp, "182\xa0800")

    def test_total_uses_current_db_price(self):
        """Цена в сессии не хранится: изменение цены сразу отражается в итоге."""
        self.add(self.go, 1)
        Product.objects.filter(pk=self.go.pk).update(price=Decimal("15000"))
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual(resp.context["cart"].total, Decimal("15000"))

    def test_tampered_session_ignored(self):
        session = self.client.session
        session[SESSION_KEY] = {str(self.go.pk): 2, "evil": 5, str(self.arm.pk): -4, "x": "y"}
        session.save()
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([l.product.pk for l in resp.context["lines"]], [self.go.pk])

    def test_unavailable_product_dropped_with_message(self):
        self.add(self.go, 1)
        self.add(self.arm, 1)
        Product.objects.filter(pk=self.arm.pk).update(is_available=False)
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual([l.product.pk for l in resp.context["lines"]], [self.go.pk])
        self.assertNotIn(str(self.arm.pk), self.session_cart())
        self.assertTrue(any("ArmLab A4" in m for m in self.msgs(resp)))

    def test_stock_decrease_adjusts_quantity(self):
        self.add(self.arm, 4)
        Product.objects.filter(pk=self.arm.pk).update(stock=2)
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual(resp.context["lines"][0].quantity, 2)
        self.assertEqual(self.session_cart()[str(self.arm.pk)], 2)

    def test_query_count_bounded(self):
        """Регрессия N+1: один запрос на товары независимо от числа позиций."""
        for p in (self.go, self.arm, Product.objects.get(slug="skyedu-quad")):
            self.add(p)
        with self.assertNumQueries(2):  # загрузка сессии + все товары одним запросом
            self.client.get(reverse("cart:detail"))

    def test_header_badge_count(self):
        self.add(self.go, 3)
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, '<span class="badge">3</span>', html=True)

    def test_cart_survives_login(self):
        self.add(self.go, 2)
        user = get_user_model().objects.create_user("buyer", password="x-Strong-pass-1")
        self.client.force_login(user)  # login() меняет ключ сессии, но сохраняет данные
        self.assertEqual(self.session_cart(), {str(self.go.pk): 2})


class UpdateRemoveTests(CartTestBase):
    def update(self, product, qty):
        return self.client.post(reverse("cart:update", args=[product.pk]), {"quantity": qty})

    def test_update_sets_quantity(self):
        self.add(self.go, 1)
        self.update(self.go, 7)
        self.assertEqual(self.session_cart()[str(self.go.pk)], 7)

    def test_update_zero_removes(self):
        self.add(self.go, 2)
        self.update(self.go, 0)
        self.assertNotIn(str(self.go.pk), self.session_cart())

    def test_update_clamped_to_stock(self):
        self.add(self.arm, 1)
        self.update(self.arm, 50)
        self.assertEqual(self.session_cart()[str(self.arm.pk)], 4)

    def test_update_product_not_in_cart_does_not_add(self):
        """update не должен быть обходным путём добавления."""
        self.update(self.go, 5)
        self.assertEqual(self.session_cart(), {})

    def test_update_invalid_value(self):
        self.add(self.go, 2)
        self.update(self.go, "abc")
        self.assertEqual(self.session_cart()[str(self.go.pk)], 2)

    def test_remove(self):
        self.add(self.go, 2)
        self.add(self.arm, 1)
        self.client.post(reverse("cart:remove", args=[self.go.pk]))
        self.assertEqual(self.session_cart(), {str(self.arm.pk): 1})

    def test_remove_twice_is_idempotent(self):
        self.add(self.go, 2)
        self.client.post(reverse("cart:remove", args=[self.go.pk]))
        resp = self.client.post(reverse("cart:remove", args=[self.go.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Event.objects.filter(event_type=Event.Type.REMOVE_FROM_CART).count(), 1)

    def test_clear(self):
        self.add(self.go, 2)
        self.client.post(reverse("cart:clear"))
        self.assertEqual(self.session_cart(), {})


class CartAnalyticsTests(CartTestBase):
    def events(self, t):
        return Event.objects.filter(event_type=t)

    def test_add_event_records_actual_quantity_and_value(self):
        """В событие пишется фактически добавленное, а не запрошенное."""
        self.add(self.arm, 10)  # остаток 4
        ev = self.events(Event.Type.ADD_TO_CART).get()
        self.assertEqual((ev.product, ev.quantity, ev.value), (self.arm, 4, Decimal("580000")))

    def test_no_event_when_nothing_added(self):
        self.add(self.arm, 4)
        self.add(self.arm, 1)  # уже максимум
        self.add(self.racer, 1)  # нет на складе
        self.assertEqual(self.events(Event.Type.ADD_TO_CART).count(), 1)

    def test_update_records_delta(self):
        self.add(self.go, 5)
        self.client.post(reverse("cart:update", args=[self.go.pk]), {"quantity": 2})
        ev = self.events(Event.Type.REMOVE_FROM_CART).get()
        self.assertEqual(ev.quantity, 3)

    def test_add_events_not_deduplicated(self):
        """В отличие от просмотров, каждое добавление — отдельное действие."""
        self.add(self.go, 1)
        self.add(self.go, 1)
        self.assertEqual(self.events(Event.Type.ADD_TO_CART).count(), 2)
