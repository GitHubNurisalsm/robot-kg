import io
import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from analytics.models import Event
from cart.cart import SESSION_KEY
from catalog.models import Product
from orders.models import Order, OrderItem
from orders.services import _decrement_stock, cancel_order

PASSWORD = "Robo-Strong-Pass-2026"
S = Order.Status


class OrderBase(TestCase):
    checkout_url = reverse("orders:checkout")

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.user = get_user_model().objects.create_user("buyer", "buyer@example.com", PASSWORD,
                                                        first_name="Айбек", phone="+996555111222")
        cls.other = get_user_model().objects.create_user("other", "other@example.com", PASSWORD)

    def setUp(self):
        self.arm = Product.objects.get(slug="armlab-a4")   # 145 000, stock 4
        self.go = Product.objects.get(slug="stembot-go")   # 18 900, stock 40
        self.client.force_login(self.user)

    def add(self, product, qty):
        self.client.post(reverse("cart:add", args=[product.pk]), {"quantity": qty})

    def form_data(self, **over):
        """Берём токен и сумму из реальной GET-страницы оформления."""
        form = self.client.get(self.checkout_url).context["form"]
        data = {"checkout_token": form.initial["checkout_token"],
                "expected_total": form.initial["expected_total"],
                "full_name": "Айбек", "phone": "+996 555 111 222", "email": "Buyer@Example.com",
                "delivery_method": "pickup", "address": "", "comment": ""}
        data.update(over)
        return data

    def place(self, **over):
        return self.client.post(self.checkout_url, self.form_data(**over))

    def stock(self, product):
        return Product.objects.get(pk=product.pk).stock


class CheckoutHappyPathTests(OrderBase):
    def test_order_created_stock_decremented_cart_cleared(self):
        self.add(self.arm, 2)
        self.add(self.go, 3)
        resp = self.place()
        order = Order.objects.get()
        self.assertRedirects(resp, reverse("orders:detail", args=[order.number]))
        self.assertEqual(order.total, Decimal("145000") * 2 + Decimal("18900") * 3)
        self.assertEqual((order.user, order.status, order.email), (self.user, S.NEW, "buyer@example.com"))
        self.assertEqual(self.stock(self.arm), 2)
        self.assertEqual(self.stock(self.go), 37)
        self.assertEqual(self.client.session.get(SESSION_KEY), {})
        self.assertRegex(order.number, r"^RB-[2-9A-HJ-NP-Z]{8}$")

    def test_items_snapshot_name_and_price(self):
        """Регрессия: последующее изменение цены/названия не меняет заказ."""
        self.add(self.arm, 1)
        self.place()
        Product.objects.filter(pk=self.arm.pk).update(price=Decimal("1"), name="Переименован")
        item = OrderItem.objects.get()
        self.assertEqual((item.product_name, item.unit_price, item.line_total),
                         ("ArmLab A4", Decimal("145000"), Decimal("145000")))

    def test_delivery_requires_address(self):
        self.add(self.go, 1)
        resp = self.place(delivery_method="delivery", address="  ")
        self.assertIn("address", resp.context["form"].errors)
        self.assertFalse(Order.objects.exists())
        self.place(delivery_method="delivery", address="Бишкек, ул. Киевская, 1")
        self.assertEqual(Order.objects.get().address, "Бишкек, ул. Киевская, 1")

    def test_pickup_drops_address(self):
        self.add(self.go, 1)
        self.place(delivery_method="pickup", address="лишний адрес")
        self.assertEqual(Order.objects.get().address, "")

    def test_client_cannot_set_status_total_user(self):
        self.add(self.go, 1)
        self.place(status="completed", total="1", user=str(self.other.pk), number="RB-HACKED")
        order = Order.objects.get()
        self.assertEqual((order.status, order.total, order.user), (S.NEW, Decimal("18900"), self.user))
        self.assertNotEqual(order.number, "RB-HACKED")

    def test_checkout_event_after_commit(self):
        self.add(self.arm, 2)
        with self.captureOnCommitCallbacks(execute=True):
            self.place()
        ev = Event.objects.get(event_type=Event.Type.CHECKOUT)
        self.assertEqual((ev.quantity, ev.value), (2, Decimal("290000")))


class CheckoutAccessTests(OrderBase):
    def test_login_required_and_returns_to_checkout(self):
        client = Client()
        resp = client.get(self.checkout_url)
        self.assertRedirects(resp, f"{reverse('accounts:login')}?next={self.checkout_url}")

    def test_empty_cart_redirects(self):
        self.assertRedirects(self.client.get(self.checkout_url), reverse("cart:detail"))

    def test_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.checkout_url, {}).status_code, 403)

    def test_order_detail_owner_only(self):
        self.add(self.go, 1)
        self.place()
        url = reverse("orders:detail", args=[Order.objects.get().number])
        self.assertEqual(self.client.get(url).status_code, 200)
        intruder = Client()
        intruder.force_login(self.other)
        self.assertEqual(intruder.get(url).status_code, 404)  # IDOR: 404, а не 403
        self.assertEqual(Client().get(url).status_code, 302)  # аноним → вход

    def test_staff_can_view_any_order(self):
        self.add(self.go, 1)
        self.place()
        staff = get_user_model().objects.create_user("mgr", "m@example.com", PASSWORD, is_staff=True)
        c = Client()
        c.force_login(staff)
        self.assertEqual(c.get(reverse("orders:detail", args=[Order.objects.get().number])).status_code, 200)

    def test_order_list_only_own(self):
        self.add(self.go, 1)
        self.place()
        Order.objects.create(number="RB-OTHER001", user=self.other, full_name="x", phone="1",
                             email="o@e.com", total=Decimal("1"), checkout_token=uuid.uuid4())
        resp = self.client.get(reverse("orders:list"))
        self.assertEqual([o.user for o in resp.context["orders"]], [self.user])
        self.assertEqual(resp.context["orders"][0].items_count, 1)

    def test_detail_query_count_bounded(self):
        for p in (self.go, self.arm, Product.objects.get(slug="skyedu-quad")):
            self.add(p, 1)
        self.place()
        url = reverse("orders:detail", args=[Order.objects.get().number])
        self.client.get(url)
        with self.assertNumQueries(5):  # session + user + order + items + products
            self.client.get(url)


class StockAndConsistencyTests(OrderBase):
    def test_insufficient_stock_rolls_back_everything(self):
        """Частичного списания не бывает: нехватка второй позиции откатывает первую."""
        self.add(self.go, 5)
        self.add(self.arm, 3)
        data = self.form_data()
        Product.objects.filter(pk=self.arm.pk).update(stock=2)  # кто-то купил, пока заполняли форму
        # Корзина при этом ещё «думает», что 3 доступно — эмулируем гонку в обход Cart.lines().
        with mock.patch("orders.services.Cart.lines", autospec=True) as lines:
            from cart.cart import CartLine
            lines.return_value = [CartLine(self.go, 5), CartLine(Product.objects.get(pk=self.arm.pk), 3)]
            resp = self.client.post(self.checkout_url, data)
        self.assertRedirects(resp, reverse("cart:detail"), fetch_redirect_response=False)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertEqual(self.stock(self.go), 40)  # откат первой позиции
        self.assertEqual(self.stock(self.arm), 2)

    def test_conditional_decrement_is_race_safe(self):
        """Последний экземпляр: второй списатель получает отказ, остаток не уходит в минус."""
        Product.objects.filter(pk=self.arm.pk).update(stock=1)
        self.assertTrue(_decrement_stock(self.arm.pk, 1))
        self.assertFalse(_decrement_stock(self.arm.pk, 1))
        self.assertEqual(self.stock(self.arm), 0)

    def test_db_check_blocks_negative_stock(self):
        """Последний рубеж: даже прямой UPDATE не уведёт остаток в минус."""
        from django.db.models import F
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.filter(pk=self.arm.pk).update(stock=F("stock") - 100)

    def test_unavailable_product_not_sold(self):
        self.add(self.go, 1)
        data = self.form_data()
        with mock.patch("orders.services.Cart.lines", autospec=True) as lines:
            from cart.cart import CartLine
            go = Product.objects.get(pk=self.go.pk)
            Product.objects.filter(pk=self.go.pk).update(is_available=False)
            lines.return_value = [CartLine(go, 1)]
            self.client.post(self.checkout_url, data)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.stock(self.go), 40)

    def test_cart_adjusted_before_checkout_redirects_to_cart(self):
        self.add(self.arm, 4)
        Product.objects.filter(pk=self.arm.pk).update(stock=1)
        self.assertRedirects(self.client.get(self.checkout_url), reverse("cart:detail"))

    def test_price_changed_requires_reconfirmation(self):
        self.add(self.go, 2)
        data = self.form_data()
        Product.objects.filter(pk=self.go.pk).update(price=Decimal("20000"))
        resp = self.client.post(self.checkout_url, data)
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.stock(self.go), 40)
        # Повторное подтверждение с новой суммой проходит.
        new_total = resp.context["form"].initial["expected_total"]
        self.assertEqual(Decimal(new_total), Decimal("40000"))
        self.client.post(self.checkout_url, {**data, "expected_total": new_total})
        self.assertEqual(Order.objects.get().total, Decimal("40000"))

    def test_tampered_expected_total_rejected(self):
        self.add(self.go, 1)
        self.place(expected_total="1.00")
        self.assertFalse(Order.objects.exists())


class IdempotencyTests(OrderBase):
    def test_double_submit_one_order(self):
        """Регрессия: второй POST той же формы ведёт к заказу, а не в «пустую корзину»."""
        self.add(self.arm, 1)
        data = self.form_data()
        r1 = self.client.post(self.checkout_url, data)
        r2 = self.client.post(self.checkout_url, data)
        order = Order.objects.get()
        self.assertEqual(r1.url, r2.url)
        self.assertEqual(r2.url, reverse("orders:detail", args=[order.number]))
        self.assertEqual(self.stock(self.arm), 3)  # списано один раз

    def test_token_unique_in_db(self):
        token = uuid.uuid4()
        Order.objects.create(number="RB-AAAA2222", user=self.user, full_name="x", phone="1",
                             email="a@e.com", total=Decimal("1"), checkout_token=token)
        with self.assertRaises(IntegrityError):
            Order.objects.create(number="RB-BBBB3333", user=self.user, full_name="x", phone="1",
                                 email="a@e.com", total=Decimal("1"), checkout_token=token)

    def test_other_users_token_does_not_leak_order(self):
        self.add(self.go, 1)
        data = self.form_data()
        self.client.post(self.checkout_url, data)
        intruder = Client()
        intruder.force_login(self.other)
        resp = intruder.post(self.checkout_url, data)
        self.assertNotEqual(getattr(resp, "url", ""), reverse("orders:detail", args=[Order.objects.get().number]))

    def test_order_number_collision_retried(self):
        Order.objects.create(number="RB-SAME2222", user=self.other, full_name="x", phone="1",
                             email="a@e.com", total=Decimal("1"), checkout_token=uuid.uuid4())
        self.add(self.go, 1)
        with mock.patch("orders.services.generate_order_number", side_effect=["RB-SAME2222", "RB-FRESH333"]):
            self.place()
        self.assertTrue(Order.objects.filter(number="RB-FRESH333", user=self.user).exists())


class StatusAndCancelTests(OrderBase):
    def make_order(self, qty=2):
        self.add(self.arm, qty)
        self.place()
        return Order.objects.get()

    def test_cancel_restocks_once(self):
        order = self.make_order(2)
        self.assertEqual(self.stock(self.arm), 2)
        self.assertTrue(cancel_order(order.pk))
        self.assertFalse(cancel_order(order.pk))  # повтор — ничего
        self.assertEqual(self.stock(self.arm), 4)
        order.refresh_from_db()
        self.assertEqual(order.status, S.CANCELLED)

    def test_cannot_cancel_shipped(self):
        order = self.make_order()
        Order.objects.filter(pk=order.pk).update(status=S.SHIPPED)
        self.assertFalse(cancel_order(order.pk))
        self.assertEqual(self.stock(self.arm), 2)

    def test_transitions(self):
        order = self.make_order()
        for nxt in (S.CONFIRMED, S.SHIPPED, S.COMPLETED):
            order.status = nxt
            order.full_clean()
            order.save()
        for bad in (S.NEW, S.CANCELLED):
            order.status = bad
            with self.assertRaises(ValidationError):
                order.full_clean()

    def test_admin_cancel_via_status_restocks(self):
        order = self.make_order(2)
        admin = get_user_model().objects.create_superuser("boss", "b@example.com", PASSWORD)
        c = Client()
        c.force_login(admin)
        url = reverse("admin:orders_order_changelist")
        c.post(url, {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
                     "form-0-id": str(order.pk), "form-0-status": S.CANCELLED, "_save": "Сохранить"})
        order.refresh_from_db()
        self.assertEqual(order.status, S.CANCELLED)
        self.assertEqual(self.stock(self.arm), 4)

    def test_admin_action_cancel(self):
        order = self.make_order(1)
        admin = get_user_model().objects.create_superuser("boss", "b@example.com", PASSWORD)
        c = Client()
        c.force_login(admin)
        c.post(reverse("admin:orders_order_changelist"),
               {"action": "cancel_selected", "_selected_action": [order.pk]})
        self.assertEqual(self.stock(self.arm), 4)

    def test_admin_cannot_add_or_delete(self):
        order = self.make_order(1)
        admin = get_user_model().objects.create_superuser("boss", "b@example.com", PASSWORD)
        c = Client()
        c.force_login(admin)
        self.assertEqual(c.get(reverse("admin:orders_order_add")).status_code, 403)
        self.assertEqual(c.get(reverse("admin:orders_order_delete", args=[order.pk])).status_code, 403)

    def test_product_with_orders_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        self.make_order(1)
        with self.assertRaises(ProtectedError):
            Product.objects.get(pk=self.arm.pk).delete()
