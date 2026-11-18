from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from analytics.models import Event
from inquiries.models import ContactMessage
from inquiries.services import RATE_LIMIT


class ContactBase(TestCase):
    url = reverse("inquiries:contact")

    def data(self, **over):
        data = {"name": "Бакыт", "email": "Bakyt@Example.com", "phone": "+996 700 111 222",
                "subject": "Покупка оборудования", "message": "Хочу купить 10 наборов STEMBot Go для школы.",
                "website": ""}
        data.update(over)
        return data


class ContactPageTests(ContactBase):
    def test_page_renders_contact_info(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        for text in ("г. Бишкек", "+996 (555) 000-000", "info@robot-kg-baiel.example", "Пн–Пт"):
            self.assertContains(resp, text)

    def test_nav_link_enabled(self):
        self.assertContains(self.client.get(reverse("core:home")), 'href="/contacts/"')

    def test_honeypot_hidden_from_users(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, '<div class="hp" aria-hidden="true">')

    def test_prefill_for_user(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "x-Strong-1", first_name="Нурлан")
        self.client.force_login(user)
        initial = self.client.get(self.url).context["form"].initial
        self.assertEqual((initial["name"], initial["email"]), ("Нурлан", "u@example.com"))


class ContactSubmitTests(ContactBase):
    def test_happy_path(self):
        resp = self.client.post(self.url, self.data())
        self.assertRedirects(resp, self.url + "#contact-form", fetch_redirect_response=False)
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.email, "bakyt@example.com")
        self.assertFalse(msg.is_processed)
        self.assertIsNone(msg.user)

    def test_success_message_after_redirect(self):
        resp = self.client.post(self.url, self.data(), follow=True)
        self.assertContains(resp, "Спасибо! Сообщение отправлено")

    def test_client_cannot_mark_processed_or_set_user(self):
        self.client.post(self.url, self.data(is_processed="on", user="1"))
        msg = ContactMessage.objects.get()
        self.assertFalse(msg.is_processed)
        self.assertIsNone(msg.user)

    def test_user_linked(self):
        user = get_user_model().objects.create_user("u", "u@example.com", "x-Strong-1")
        self.client.force_login(user)
        self.client.post(self.url, self.data())
        self.assertEqual(ContactMessage.objects.get().user, user)

    def test_validation(self):
        cases = {
            "email": dict(email="not-an-email"),
            "phone": dict(phone="звоните"),
            "subject": dict(subject="Взлом"),
            "message": dict(message="  коротко "),
            "name": dict(name=""),
        }
        for field, over in cases.items():
            with self.subTest(field):
                resp = self.client.post(self.url, self.data(**over))
                self.assertEqual(resp.status_code, 200)
                self.assertIn(field, resp.context["form"].errors)
        self.assertFalse(ContactMessage.objects.exists())

    def test_message_max_length(self):
        resp = self.client.post(self.url, self.data(message="x" * 5001))
        self.assertIn("message", resp.context["form"].errors)

    def test_phone_optional(self):
        self.client.post(self.url, self.data(phone=""))
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_honeypot_silently_dropped(self):
        """Бот получает «успех», но ничего не сохраняется и не считается."""
        resp = self.client.post(self.url, self.data(website="http://spam.example"))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ContactMessage.objects.exists())
        self.assertFalse(Event.objects.filter(event_type=Event.Type.CONTACT).exists())

    def test_double_submit_not_duplicated(self):
        self.client.post(self.url, self.data())
        self.client.post(self.url, self.data())
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_duplicate_window_expires(self):
        self.client.post(self.url, self.data())
        ContactMessage.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        self.client.post(self.url, self.data())
        self.assertEqual(ContactMessage.objects.count(), 2)

    def test_rate_limit_per_session(self):
        for i in range(RATE_LIMIT):
            self.client.post(self.url, self.data(message=f"Вопрос номер {i} про роботов"))
        resp = self.client.post(self.url, self.data(message="Ещё один вопрос про роботов"))
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(ContactMessage.objects.count(), RATE_LIMIT)
        # Форма с введёнными данными не теряется.
        self.assertEqual(resp.context["form"]["name"].value(), "Бакыт")

    def test_rate_limit_other_session_unaffected(self):
        for i in range(RATE_LIMIT):
            self.client.post(self.url, self.data(message=f"Вопрос номер {i} про роботов"))
        resp = Client().post(self.url, self.data(message="Другой посетитель спрашивает"))
        self.assertEqual(resp.status_code, 302)

    def test_rate_limit_tampered_session_safe(self):
        session = self.client.session
        session["contact_sent_at"] = "garbage"
        session.save()
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 302)

    def test_csrf_enforced(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.data()).status_code, 403)

    def test_analytics_event(self):
        self.client.post(self.url, self.data())
        self.client.post(self.url, self.data())  # дубль — без события
        self.assertEqual(Event.objects.filter(event_type=Event.Type.CONTACT).count(), 1)

    def test_xss_escaped_in_admin_view(self):
        """Текст обращения выводится экранированным."""
        self.client.post(self.url, self.data(name="<script>alert(1)</script>"))
        admin = get_user_model().objects.create_superuser("boss", "b@example.com", "x-Strong-1")
        self.client.force_login(admin)
        msg = ContactMessage.objects.get()
        resp = self.client.get(reverse("admin:inquiries_contactmessage_change", args=[msg.pk]))
        self.assertNotContains(resp, "<script>alert(1)</script>")
        self.assertContains(resp, "&lt;script&gt;")


class ContactAdminTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("boss", "b@example.com", "x-Strong-1")
        self.client.force_login(self.admin)
        self.m1 = ContactMessage.objects.create(name="A", email="a@e.com", subject="Другое", message="x" * 20)
        self.m2 = ContactMessage.objects.create(name="B", email="b@e.com", subject="Другое", message="y" * 20)

    def test_mark_processed_action(self):
        url = reverse("admin:inquiries_contactmessage_changelist")
        self.client.post(url, {"action": "mark_processed", "_selected_action": [self.m1.pk, self.m2.pk]})
        self.assertEqual(ContactMessage.objects.filter(is_processed=True).count(), 2)

    def test_add_disabled(self):
        resp = self.client.get(reverse("admin:inquiries_contactmessage_add"))
        self.assertEqual(resp.status_code, 403)

    def test_message_text_not_editable(self):
        url = reverse("admin:inquiries_contactmessage_change", args=[self.m1.pk])
        self.client.post(url, {"is_processed": "on", "message": "подменённый текст"})
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.message, "x" * 20)
