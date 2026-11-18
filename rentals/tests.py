import datetime
import io
from decimal import Decimal

from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from analytics.models import Event
from catalog.models import Category, Product
from rentals.forms import MAX_RENTAL_DAYS
from rentals.models import RentalRequest

S = RentalRequest.Status


def d(days):
    return timezone.localdate() + datetime.timedelta(days=days)


class RentalConstraintTests(TestCase):
    def test_end_before_start_rejected(self):
        cat = Category.objects.create(name="Т", slug="t")
        p = Product.objects.create(category=cat, name="P", slug="p", short_description="s",
                                   description="d", price=Decimal("1"), is_rentable=True,
                                   rental_price_per_day=Decimal("1"))
        with self.assertRaises(IntegrityError):
            RentalRequest.objects.create(product=p, full_name="A", phone="1",
                                         start_date=datetime.date(2026, 1, 5),
                                         end_date=datetime.date(2026, 1, 4))


class RentalBase(TestCase):
    url = reverse("rentals:rental")

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=io.StringIO())
        cls.arm = Product.objects.get(slug="armlab-a4")       # 6 000/сутки
        cls.cobot = Product.objects.get(slug="armlab-cobot-6")  # не арендуется

    def data(self, **over):
        data = {"product": self.arm.slug, "start_date": d(3).isoformat(), "end_date": d(5).isoformat(),
                "full_name": "Айгерим", "phone": "+996 555 123 456", "email": "a@example.com",
                "organization": "", "comment": ""}
        data.update(over)
        return data


class RentalPageTests(RentalBase):
    def test_lists_only_rentable_available(self):
        Product.objects.filter(slug="skyedu-quad").update(is_available=False)
        resp = self.client.get(self.url)
        slugs = {p.slug for p in resp.context["products"]}
        self.assertIn("armlab-a4", slugs)
        self.assertNotIn("armlab-cobot-6", slugs)  # не арендуется
        self.assertNotIn("skyedu-quad", slugs)     # снят с продажи

    def test_nav_item_enabled(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, 'href="/rental/"')

    def test_preselect_product_from_query(self):
        resp = self.client.get(self.url, {"product": "armlab-a4"})
        self.assertEqual(resp.context["form"].initial["product"], "armlab-a4")
        resp = self.client.get(self.url, {"product": "armlab-cobot-6"})
        self.assertNotIn("product", resp.context["form"].initial)

    def test_prefill_from_user(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "x-Strong-1", first_name="Нурлан", phone="+996700000000")
        self.client.force_login(user)
        initial = self.client.get(self.url).context["form"].initial
        self.assertEqual((initial["full_name"], initial["email"], initial["phone"]),
                         ("Нурлан", "u@example.com", "+996700000000"))


class RentalSubmitTests(RentalBase):
    def test_happy_path_snapshot_and_redirect(self):
        resp = self.client.post(self.url, self.data())
        self.assertRedirects(resp, self.url + "#rental-form", fetch_redirect_response=False)
        r = RentalRequest.objects.get()
        self.assertEqual(r.status, S.NEW)
        self.assertEqual(r.days, 3)
        self.assertEqual(r.price_per_day, Decimal("6000"))
        self.assertEqual(r.estimated_total, Decimal("18000"))

    def test_price_snapshot_survives_price_change(self):
        """Регрессия: изменение цены товара не меняет уже созданную заявку."""
        self.client.post(self.url, self.data())
        Product.objects.filter(pk=self.arm.pk).update(rental_price_per_day=Decimal("9999"))
        self.assertEqual(RentalRequest.objects.get().estimated_total, Decimal("18000"))

    def test_client_cannot_set_status_or_price(self):
        """Mass assignment: status/цены/user из POST игнорируются."""
        self.client.post(self.url, self.data(status="approved", estimated_total="1",
                                             price_per_day="1", user="1"))
        r = RentalRequest.objects.get()
        self.assertEqual((r.status, r.estimated_total, r.user), (S.NEW, Decimal("18000"), None))

    def test_non_rentable_product_rejected(self):
        resp = self.client.post(self.url, self.data(product=self.cobot.slug))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("product", resp.context["form"].errors)
        self.assertFalse(RentalRequest.objects.exists())

    def test_date_rules(self):
        cases = {
            "сегодня": dict(start_date=d(0).isoformat(), end_date=d(2).isoformat()),
            "прошлое": dict(start_date=d(-5).isoformat(), end_date=d(-1).isoformat()),
            "конец раньше начала": dict(start_date=d(5).isoformat(), end_date=d(3).isoformat()),
            "слишком долго": dict(start_date=d(1).isoformat(), end_date=d(1 + MAX_RENTAL_DAYS).isoformat()),
            "больше года вперёд": dict(start_date=d(400).isoformat(), end_date=d(401).isoformat()),
            "мусор": dict(start_date="31.31.2026", end_date="abc"),
        }
        for name, over in cases.items():
            with self.subTest(name):
                resp = self.client.post(self.url, self.data(**over))
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.context["form"].errors)
        self.assertFalse(RentalRequest.objects.exists())

    def test_boundaries_accepted(self):
        """Граничные значения: завтра и ровно MAX_RENTAL_DAYS дней — допустимы."""
        resp = self.client.post(self.url, self.data(start_date=d(1).isoformat(),
                                                    end_date=d(MAX_RENTAL_DAYS).isoformat()))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RentalRequest.objects.get().days, MAX_RENTAL_DAYS)

    def test_one_day_rental(self):
        self.client.post(self.url, self.data(start_date=d(2).isoformat(), end_date=d(2).isoformat()))
        self.assertEqual(RentalRequest.objects.get().estimated_total, Decimal("6000"))

    def test_bad_phone_and_required(self):
        resp = self.client.post(self.url, self.data(phone="позвоните", full_name=""))
        errors = resp.context["form"].errors
        self.assertIn("phone", errors)
        self.assertIn("full_name", errors)

    def test_double_submit_not_duplicated(self):
        """Двойной клик / повтор POST той же сессией — одна заявка и одно событие."""
        self.client.post(self.url, self.data())
        self.client.post(self.url, self.data())
        self.assertEqual(RentalRequest.objects.count(), 1)
        self.assertEqual(Event.objects.filter(event_type=Event.Type.RENTAL_REQUEST).count(), 1)

    def test_different_dates_are_separate_requests(self):
        self.client.post(self.url, self.data())
        self.client.post(self.url, self.data(end_date=d(6).isoformat()))
        self.assertEqual(RentalRequest.objects.count(), 2)

    def test_other_session_not_deduplicated(self):
        self.client.post(self.url, self.data())
        Client().post(self.url, self.data())
        self.assertEqual(RentalRequest.objects.count(), 2)

    def test_user_linked_when_authenticated(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "x-Strong-1")
        self.client.force_login(user)
        self.client.post(self.url, self.data())
        self.assertEqual(RentalRequest.objects.get().user, user)

    def test_csrf_enforced(self):
        resp = Client(enforce_csrf_checks=True).post(self.url, self.data())
        self.assertEqual(resp.status_code, 403)

    def test_analytics_event(self):
        self.client.post(self.url, self.data())
        ev = Event.objects.get(event_type=Event.Type.RENTAL_REQUEST)
        self.assertEqual((ev.product, ev.quantity, ev.value), (self.arm, 3, Decimal("18000")))


class StatusTransitionTests(RentalBase):
    def make(self, status=S.NEW):
        return RentalRequest.objects.create(
            product=self.arm, full_name="A", phone="+996555000000",
            start_date=d(2), end_date=d(3), status=status)

    def test_allowed_transitions(self):
        r = self.make()
        for nxt in (S.IN_PROGRESS, S.APPROVED, S.COMPLETED):
            r.status = nxt
            r.full_clean()
            r.save()

    def test_forbidden_transitions(self):
        for old, new in ((S.COMPLETED, S.NEW), (S.REJECTED, S.APPROVED),
                         (S.NEW, S.COMPLETED), (S.APPROVED, S.IN_PROGRESS)):
            with self.subTest(f"{old}->{new}"):
                r = self.make(old)
                r.status = new
                with self.assertRaises(ValidationError) as cm:
                    r.full_clean()
                self.assertIn("status", cm.exception.message_dict)

    def test_admin_list_editable_respects_transitions(self):
        """Правка статуса прямо в списке админки тоже проходит проверку переходов."""
        admin_user = get_user_model().objects.create_superuser("boss", "b@example.com", "x-Strong-1")
        self.client.force_login(admin_user)
        r = self.make(S.COMPLETED)
        url = reverse("admin:rentals_rentalrequest_changelist")
        resp = self.client.post(url, {
            "form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
            "form-0-id": str(r.pk), "form-0-status": S.NEW, "_save": "Сохранить",
        })
        self.assertEqual(resp.status_code, 200)  # форма с ошибкой, не редирект
        r.refresh_from_db()
        self.assertEqual(r.status, S.COMPLETED)

    def test_admin_registered(self):
        self.assertIn(RentalRequest, admin_site._registry)
