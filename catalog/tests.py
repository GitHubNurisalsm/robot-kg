from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from catalog.models import Category, Product


class ProductConstraintTests(TestCase):
    """Инварианты закреплены на уровне БД, а не только в формах."""

    def setUp(self):
        self.cat = Category.objects.create(name="Тест", slug="test")

    def make(self, **kw):
        data = dict(category=self.cat, name="P", slug="p", short_description="s",
                    description="d", price=Decimal("100"))
        data.update(kw)
        return Product.objects.create(**data)

    def test_negative_price_rejected(self):
        with self.assertRaises(IntegrityError):
            self.make(price=Decimal("-1"))

    def test_old_price_must_exceed_price(self):
        with self.assertRaises(IntegrityError):
            self.make(old_price=Decimal("50"))

    def test_rentable_requires_rental_price(self):
        with self.assertRaises(IntegrityError):
            self.make(is_rentable=True)

    def test_image_url_falls_back_to_illustration(self):
        p = self.make(illustration="drone")
        self.assertTrue(p.image_url.endswith("img/robots/drone.svg"))


# ---------------------------------------------------------------------------
# Каталог: список, фильтры, страница товара
# ---------------------------------------------------------------------------
import io

from django.core.management import call_command
from django.urls import reverse


def seed():
    call_command("seed_demo", stdout=io.StringIO())


class ProductListTests(TestCase):
    url = reverse("catalog:product_list")

    @classmethod
    def setUpTestData(cls):
        seed()

    def names(self, resp):
        return [p.name for p in resp.context["products"]]

    def test_lists_only_available(self):
        Product.objects.filter(slug="stembot-go").update(is_available=False)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("STEMBot Go", self.names(resp))
        self.assertEqual(resp.context["page_obj"].paginator.count, 11)

    def test_cyrillic_search_case_insensitive(self):
        """Регрессия: SQLite LIKE не понижает регистр кириллицы."""
        upper = self.client.get(self.url, {"q": "КВАДРОКОПТЕР"})
        lower = self.client.get(self.url, {"q": "квадрокоптер"})
        self.assertIn("SkyEdu Quad", self.names(upper))
        self.assertEqual(self.names(upper), self.names(lower))

    def test_search_multiple_terms_is_and(self):
        both = self.client.get(self.url, {"q": "манипулятор захват"})
        self.assertEqual(set(self.names(both)), {"ArmLab A4", "STEMBot Pro"})
        narrowed = self.client.get(self.url, {"q": "манипулятор гравировки"})
        self.assertEqual(self.names(narrowed), ["ArmLab A4"])

    def test_search_index_updated_on_save(self):
        p = Product.objects.get(slug="builder-x-200")
        p.description = "Уникальнаяфраза в описании"
        p.save(update_fields=["description"])
        resp = self.client.get(self.url, {"q": "уникальнаяфраза"})
        self.assertEqual(self.names(resp), ["Builder X-200"])

    def test_category_filter(self):
        resp = self.client.get(self.url, {"category": "drones"})
        self.assertEqual(set(self.names(resp)), {"SkyEdu Quad", "SkyEdu Racer FPV"})

    def test_inactive_category_not_selectable(self):
        Category.objects.filter(slug="drones").update(is_active=False)
        resp = self.client.get(self.url, {"category": "drones"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("category", resp.context["form"].errors)
        self.assertNotIn("SkyEdu Quad", self.names(resp))

    def test_price_range_and_sort(self):
        resp = self.client.get(self.url, {"min_price": "10000", "max_price": "30000", "sort": "price_asc"})
        prices = [p.price for p in resp.context["products"]]
        self.assertTrue(prices)
        self.assertEqual(prices, sorted(prices))
        self.assertTrue(all(10000 <= p <= 30000 for p in prices))

    def test_min_greater_than_max_is_validation_error_not_500(self):
        resp = self.client.get(self.url, {"min_price": "500", "max_price": "100"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("max_price", resp.context["form"].errors)

    def test_garbage_params_do_not_crash(self):
        """Ввод пользователя не попадает в order_by и не роняет страницу."""
        for params in ({"sort": "-password"}, {"min_price": "abc"}, {"page": "999"},
                       {"page": "-1"}, {"category": "nope"}, {"q": "x" * 500}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 200)

    def test_in_stock_filter(self):
        resp = self.client.get(self.url, {"in_stock": "on"})
        self.assertNotIn("SkyEdu Racer FPV", self.names(resp))  # stock=0

    def test_pagination_bounded_page_size(self):
        resp = self.client.get(self.url)
        self.assertLessEqual(len(resp.context["products"]), 12)

    def test_query_count_bounded(self):
        """Регрессия N+1: категория подтягивается через select_related."""
        self.client.get(self.url)  # прогрев сессии
        # slug→категория (валидация) + count + страница + опции select категорий
        with self.assertNumQueries(4):
            self.client.get(self.url, {"category": "kits"})


class ProductDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()

    def url(self, slug):
        return reverse("catalog:product_detail", kwargs={"slug": slug})

    def test_renders_specs_and_price(self):
        resp = self.client.get(self.url("baiel-nova-h1"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Степени свободы")
        self.assertContains(resp, "1\xa0850\xa0000")  # intcomma: неразрывный пробел
        self.assertContains(resp, "45\xa0000")  # аренда/сутки

    def test_hidden_product_404(self):
        Product.objects.filter(slug="baiel-nova-h1").update(is_available=False)
        self.assertEqual(self.client.get(self.url("baiel-nova-h1")).status_code, 404)

    def test_product_in_inactive_category_404(self):
        Category.objects.filter(slug="humanoid").update(is_active=False)
        self.assertEqual(self.client.get(self.url("baiel-nova-h1")).status_code, 404)

    def test_unknown_slug_404(self):
        self.assertEqual(self.client.get(self.url("no-such-robot")).status_code, 404)

    def test_related_excludes_self(self):
        resp = self.client.get(self.url("baiel-nova-h1"))
        related = [p.slug for p in resp.context["related_products"]]
        self.assertNotIn("baiel-nova-h1", related)
        self.assertIn("baiel-mini-h", related)

    def test_out_of_stock_buy_disabled(self):
        resp = self.client.get(self.url("skyedu-racer"))
        self.assertContains(resp, "Нет на складе")
