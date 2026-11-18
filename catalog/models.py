from django.db import models
from django.db.models import Q
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse


class Illustration(models.TextChoices):
    """Встроенные SVG-иллюстрации — используются, если фото не загружено."""

    HUMANOID = "humanoid", "Гуманоид"
    EDUCATIONAL = "educational", "Образовательный"
    INDUSTRIAL = "industrial", "Промышленный манипулятор"
    DRONE = "drone", "Дрон"
    SERVICE = "service", "Сервисный"
    KIT = "kit", "Конструктор"


def illustration_url(key: str) -> str:
    return static(f"img/robots/{key}.svg")


class ActiveCategoryQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Category(models.Model):
    name = models.CharField("Название", max_length=100, unique=True)
    slug = models.SlugField("Slug", max_length=120, unique=True)
    description = models.TextField("Описание", blank=True)
    illustration = models.CharField(
        "Иллюстрация", max_length=20, choices=Illustration.choices, default=Illustration.HUMANOID
    )
    sort_order = models.PositiveSmallIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активна", default=True)

    objects = ActiveCategoryQuerySet.as_manager()

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __str__(self):
        return self.name

    @property
    def image_url(self) -> str:
        return illustration_url(self.illustration)


class ProductQuerySet(models.QuerySet):
    def available(self):
        return self.filter(is_available=True, category__is_active=True)

    def featured(self):
        return self.available().filter(is_featured=True)

    def rentable(self):
        return self.available().filter(is_rentable=True)


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        verbose_name="Категория",
        on_delete=models.PROTECT,  # нельзя удалить категорию, пока в ней есть товары
        related_name="products",
    )
    name = models.CharField("Название", max_length=200)
    slug = models.SlugField("Slug", max_length=220, unique=True)
    short_description = models.CharField("Краткое описание", max_length=300)
    description = models.TextField("Описание")
    price = models.DecimalField("Цена, сом", max_digits=12, decimal_places=2)
    old_price = models.DecimalField(
        "Старая цена, сом", max_digits=12, decimal_places=2, null=True, blank=True
    )
    image = models.ImageField("Фото", upload_to="products/%Y/%m/", blank=True)
    illustration = models.CharField(
        "Иллюстрация (если нет фото)",
        max_length=20,
        choices=Illustration.choices,
        default=Illustration.HUMANOID,
    )
    stock = models.PositiveIntegerField("Остаток на складе", default=0)
    is_available = models.BooleanField("В продаже", default=True)
    is_featured = models.BooleanField("Показывать на главной", default=False)
    is_rentable = models.BooleanField("Доступен для аренды", default=False)
    rental_price_per_day = models.DecimalField(
        "Аренда, сом/сутки", max_digits=12, decimal_places=2, null=True, blank=True
    )
    # Текст для поиска в нижнем регистре. Нужен, потому что LIKE в SQLite
    # регистронезависим только для ASCII: «робот» не нашёл бы «Робот».
    search_index = models.TextField("Поисковый индекс", blank=True, editable=False)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        indexes = [
            models.Index(fields=["is_available", "is_featured"]),
            models.Index(fields=["is_available", "is_rentable"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="product_price_non_negative"),
            models.CheckConstraint(
                condition=Q(old_price__isnull=True) | Q(old_price__gt=models.F("price")),
                name="product_old_price_gt_price",
            ),
            # Арендуемый товар обязан иметь цену аренды >= 0.
            models.CheckConstraint(
                condition=Q(is_rentable=False)
                | Q(rental_price_per_day__isnull=False, rental_price_per_day__gte=0),
                name="product_rentable_has_rental_price",
            ),
        ]

    def __str__(self):
        return self.name

    def build_search_index(self) -> str:
        return " ".join([self.name, self.short_description, self.description]).lower()

    def save(self, *args, **kwargs):
        # Внимание: QuerySet.update() обходит save() — индекс нужно обновлять вручную.
        self.search_index = self.build_search_index()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "search_index"}
        super().save(*args, **kwargs)

    @property
    def image_url(self) -> str:
        if self.image:
            return self.image.url
        return illustration_url(self.illustration)

    @property
    def in_stock(self) -> bool:
        return self.is_available and self.stock > 0

    def get_absolute_url(self) -> str:
        # Маршрут страницы товара добавляется на этапе «Каталог»;
        # до этого возвращаем якорь, чтобы шаблоны не падали.
        try:
            return reverse("catalog:product_detail", kwargs={"slug": self.slug})
        except NoReverseMatch:
            return "#"


class ProductSpecification(models.Model):
    product = models.ForeignKey(
        Product, verbose_name="Товар", on_delete=models.CASCADE, related_name="specs"
    )
    name = models.CharField("Характеристика", max_length=100)
    value = models.CharField("Значение", max_length=200)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=0)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Характеристика"
        verbose_name_plural = "Характеристики"
        constraints = [
            models.UniqueConstraint(fields=["product", "name"], name="unique_spec_per_product"),
        ]

    def __str__(self):
        return f"{self.name}: {self.value}"
