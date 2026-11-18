import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

# Без похожих символов (0/O, 1/I/L): номер диктуют по телефону.
NUMBER_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
NUMBER_LEN = 8


def generate_order_number() -> str:
    # Случайный, а не порядковый: номера нельзя перебрать.
    return "RB-" + "".join(secrets.choice(NUMBER_ALPHABET) for _ in range(NUMBER_LEN))


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новый"
        CONFIRMED = "confirmed", "Подтверждён"
        SHIPPED = "shipped", "Отправлен"
        COMPLETED = "completed", "Выполнен"
        CANCELLED = "cancelled", "Отменён"

    TRANSITIONS = {
        Status.NEW: {Status.CONFIRMED, Status.CANCELLED},
        Status.CONFIRMED: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.COMPLETED},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
    }
    CANCELLABLE = (Status.NEW, Status.CONFIRMED)

    class Delivery(models.TextChoices):
        PICKUP = "pickup", "Самовывоз (Бишкек)"
        DELIVERY = "delivery", "Доставка"

    number = models.CharField("Номер", max_length=16, unique=True, editable=False)
    # SET_NULL: заказ — финансовая история, она переживает удаление аккаунта.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Покупатель", on_delete=models.SET_NULL,
        null=True, related_name="orders",
    )
    full_name = models.CharField("Имя", max_length=150)
    phone = models.CharField("Телефон", max_length=32)
    email = models.EmailField("Email")
    delivery_method = models.CharField(
        "Способ получения", max_length=16, choices=Delivery.choices, default=Delivery.PICKUP
    )
    address = models.CharField("Адрес доставки", max_length=300, blank=True)
    comment = models.TextField("Комментарий", max_length=1000, blank=True)
    status = models.CharField("Статус", max_length=16, choices=Status.choices,
                              default=Status.NEW, db_index=True)
    total = models.DecimalField("Сумма, сом", max_digits=14, decimal_places=2)
    # Идемпотентность: одна форма оформления — ровно один заказ.
    checkout_token = models.UUIDField("Токен оформления", unique=True, editable=False)
    created_at = models.DateTimeField("Создан", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="order_total_non_negative"),
            models.CheckConstraint(
                condition=Q(delivery_method="pickup") | ~Q(address=""),
                name="order_delivery_requires_address",
            ),
        ]

    def __str__(self):
        return self.number

    @property
    def is_cancellable(self) -> bool:
        return self.status in self.CANCELLABLE

    def clean(self):
        super().clean()
        if self.delivery_method == self.Delivery.DELIVERY and not self.address.strip():
            raise ValidationError({"address": "Укажите адрес доставки."})
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if old and old != self.status and self.status not in self.TRANSITIONS[old]:
                raise ValidationError({
                    "status": f"Нельзя перевести заказ из «{self.Status(old).label}» "
                              f"в «{self.Status(self.status).label}»."
                })


class OrderItem(models.Model):
    order = models.ForeignKey(Order, verbose_name="Заказ", on_delete=models.CASCADE,
                              related_name="items")
    # PROTECT: товар, который покупали, удалить нельзя (можно снять с продажи).
    product = models.ForeignKey("catalog.Product", verbose_name="Товар",
                                on_delete=models.PROTECT, related_name="order_items")
    # Снимки на момент заказа.
    product_name = models.CharField("Название", max_length=200)
    unit_price = models.DecimalField("Цена, сом", max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField("Количество")
    line_total = models.DecimalField("Сумма, сом", max_digits=14, decimal_places=2)

    class Meta:
        ordering = ("id",)
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="unique_product_per_order"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="order_item_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="order_item_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"
