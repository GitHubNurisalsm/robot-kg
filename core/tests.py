from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from catalog.models import Category, Product
from core.templatetags.ru_format import ru_plural


class HomePageTests(TestCase):
    def test_empty_db_renders(self):
        """Главная не падает на пустой БД и показывает empty state."""
        resp = self.client.get(reverse("core:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Robot.KG.Baiel")
        self.assertContains(resp, "Технологии будущего сегодня.")
        self.assertContains(resp, "Пока нет избранных товаров")

    def test_featured_shows_only_available_featured(self):
        """В блок «Популярные» не попадают скрытые и неизбранные товары."""
        call_command("seed_demo", stdout=open("/dev/null", "w"))
        hidden = Product.objects.filter(is_featured=True).first()
        hidden.is_available = False
        hidden.save()
        resp = self.client.get(reverse("core:home"))
        names = [p.name for p in resp.context["featured_products"]]
        self.assertNotIn(hidden.name, names)
        self.assertTrue(names)
        self.assertTrue(all(p.is_featured and p.is_available for p in resp.context["featured_products"]))

    def test_inactive_category_hidden(self):
        call_command("seed_demo", stdout=open("/dev/null", "w"))
        Category.objects.filter(slug="drones").update(is_active=False)
        resp = self.client.get(reverse("core:home"))
        self.assertNotIn("drones", [c.slug for c in resp.context["categories"]])
        self.assertFalse(any(p.category.slug == "drones" for p in resp.context["featured_products"]))

    def test_home_query_count_bounded(self):
        """Регрессия N+1: число запросов не растёт с количеством карточек."""
        call_command("seed_demo", stdout=open("/dev/null", "w"))
        with self.assertNumQueries(3):  # featured + categories + count
            self.client.get(reverse("core:home"))

    def test_authenticated_user_without_logout_route_renders(self):
        """Залогиненный (например, через админку) пользователь не ломает шапку."""
        user = get_user_model().objects.create_user("u1", password="x-Strong-pass-123")
        self.client.force_login(user)
        resp = self.client.get(reverse("core:home"))
        self.assertEqual(resp.status_code, 200)


class SeedDemoTests(TestCase):
    def test_idempotent(self):
        call_command("seed_demo", stdout=open("/dev/null", "w"))
        first = (Category.objects.count(), Product.objects.count())
        call_command("seed_demo", stdout=open("/dev/null", "w"))
        self.assertEqual(first, (Category.objects.count(), Product.objects.count()))
        self.assertEqual(Product.objects.get(slug="baiel-nova-h1").specs.count(), 6)


class RuPluralTests(TestCase):
    def test_forms(self):
        forms = "товар,товара,товаров"
        cases = {0: "товаров", 1: "товар", 2: "товара", 5: "товаров", 11: "товаров",
                 12: "товаров", 21: "товар", 22: "товара", 111: "товаров"}
        for n, expected in cases.items():
            self.assertEqual(ru_plural(n, forms), expected, n)
