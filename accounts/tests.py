import io

from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.forms import SignUpForm
from accounts.models import User
from cart.cart import SESSION_KEY
from catalog.models import Product

PASSWORD = "Robo-Strong-Pass-2026"


def signup_data(**over):
    data = {"username": "aibek", "email": "Aibek@Example.com", "first_name": "Айбек",
            "phone": "+996 555 123 456", "password1": PASSWORD, "password2": PASSWORD}
    data.update(over)
    return data


class SignUpTests(TestCase):
    url = reverse("accounts:signup")

    def test_signup_creates_user_and_logs_in(self):
        resp = self.client.post(self.url, signup_data())
        self.assertRedirects(resp, reverse("core:home"))
        user = User.objects.get(username="aibek")
        self.assertEqual(user.email, "aibek@example.com")  # нормализован
        self.assertEqual(user.phone, "+996 555 123 456")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_cannot_escalate_privileges_via_post(self):
        """Mass assignment: is_staff/is_superuser из POST игнорируются."""
        self.client.post(self.url, signup_data(is_staff="on", is_superuser="on"))
        user = User.objects.get(username="aibek")
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_duplicate_email_case_insensitive(self):
        User.objects.create_user("first", "aibek@example.com", PASSWORD)
        resp = self.client.post(self.url, signup_data(email="AIBEK@EXAMPLE.COM"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("email", resp.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_error_shown_once(self):
        User.objects.create_user("first", "aibek@example.com", PASSWORD)
        resp = self.client.post(self.url, signup_data())
        self.assertContains(resp, "уже зарегистрирован", count=1)

    def test_db_constraint_blocks_race(self):
        """Гарантия на уровне БД: обход формы (гонка) не создаст дубль."""
        User.objects.create_user("a", "same@example.com", PASSWORD)
        with self.assertRaises(IntegrityError):
            User.objects.create_user("b", "SAME@example.com", PASSWORD)

    def test_integrity_error_race_handled_in_view(self):
        """Если дубль появился между проверкой формы и save() — 200 с ошибкой, не 500."""
        from unittest import mock
        with mock.patch.object(SignUpForm, "save", side_effect=IntegrityError):
            resp = self.client.post(self.url, signup_data())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].non_field_errors())

    def test_empty_emails_do_not_conflict(self):
        User.objects.create_user("x1", "", PASSWORD)
        User.objects.create_user("x2", "", PASSWORD)  # не должно падать

    def test_weak_password_rejected(self):
        resp = self.client.post(self.url, signup_data(password1="12345678", password2="12345678"))
        self.assertIn("password2", resp.context["form"].errors)
        self.assertFalse(User.objects.exists())

    def test_password_mismatch(self):
        resp = self.client.post(self.url, signup_data(password2="Other-Pass-2026"))
        self.assertIn("password2", resp.context["form"].errors)

    def test_bad_phone(self):
        resp = self.client.post(self.url, signup_data(phone="позвоните мне"))
        self.assertIn("phone", resp.context["form"].errors)

    def test_required_email(self):
        resp = self.client.post(self.url, signup_data(email=""))
        self.assertIn("email", resp.context["form"].errors)

    def test_safe_next_and_open_redirect(self):
        resp = self.client.post(self.url, signup_data(next="/catalog/"))
        self.assertRedirects(resp, "/catalog/")
        self.client.logout()
        resp = self.client.post(self.url, signup_data(username="u2", email="u2@example.com",
                                                      next="https://evil.example/"))
        self.assertRedirects(resp, reverse("core:home"))

    def test_authenticated_user_redirected(self):
        user = User.objects.create_user("me", "me@example.com", PASSWORD)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), reverse("core:home"))

    def test_password_stored_hashed(self):
        self.client.post(self.url, signup_data())
        user = User.objects.get(username="aibek")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))


class LoginLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("aibek", "aibek@example.com", PASSWORD)

    def test_login_success(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "aibek", "password": PASSWORD})
        self.assertRedirects(resp, reverse("core:home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_wrong_password_generic_error(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "aibek", "password": "nope"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(resp.context["form"].non_field_errors())

    def test_login_unknown_user_same_error(self):
        """Не раскрываем, существует ли логин."""
        r1 = self.client.post(reverse("accounts:login"), {"username": "aibek", "password": "nope"})
        r2 = self.client.post(reverse("accounts:login"), {"username": "ghost", "password": "nope"})
        self.assertEqual(r1.context["form"].non_field_errors(), r2.context["form"].non_field_errors())

    def test_inactive_user_cannot_login(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.client.post(reverse("accounts:login"), {"username": "aibek", "password": PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_open_redirect_blocked(self):
        resp = self.client.post(reverse("accounts:login") + "?next=https://evil.example/",
                                {"username": "aibek", "password": PASSWORD})
        self.assertRedirects(resp, reverse("core:home"))

    def test_login_respects_safe_next(self):
        resp = self.client.post(reverse("accounts:login") + "?next=/cart/",
                                {"username": "aibek", "password": PASSWORD})
        self.assertRedirects(resp, "/cart/")

    def test_session_key_rotated_on_login(self):
        """Защита от session fixation."""
        self.client.get(reverse("catalog:product_list"), {"q": "робот"})  # создаёт сессию
        before = self.client.session.session_key
        self.client.post(reverse("accounts:login"), {"username": "aibek", "password": PASSWORD})
        self.assertNotEqual(before, self.client.session.session_key)

    def test_cart_preserved_after_login(self):
        call_command("seed_demo", stdout=io.StringIO())
        p = Product.objects.get(slug="stembot-go")
        self.client.post(reverse("cart:add", args=[p.pk]), {"quantity": 2})
        self.client.post(reverse("accounts:login"), {"username": "aibek", "password": PASSWORD})
        self.assertEqual(self.client.session[SESSION_KEY], {str(p.pk): 2})

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_post(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("accounts:logout"), follow=True)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(resp, "Вы вышли из аккаунта")

    def test_logout_csrf_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse("accounts:logout")).status_code, 403)


class HeaderTests(TestCase):
    def test_anonymous_sees_login_with_next(self):
        resp = self.client.get(reverse("catalog:product_list"))
        self.assertContains(resp, 'href="/accounts/login/?next=%2Fcatalog%2F"')
        self.assertContains(resp, "Регистрация")

    def test_authenticated_sees_name_and_logout(self):
        user = User.objects.create_user("aibek", "a@example.com", PASSWORD, first_name="Айбек")
        self.client.force_login(user)
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, "Айбек")
        self.assertContains(resp, 'action="/accounts/logout/"')
        self.assertNotContains(resp, "Регистрация")
