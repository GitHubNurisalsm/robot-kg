from django.conf import settings
from django.db import models


class Event(models.Model):
    """Сырое событие поведения посетителя — источник данных для дашборда.

    Персональные данные не храним: ни IP, ни User-Agent. Посетитель
    идентифицируется псевдонимно — ключом сессии.
    """

    class Type(models.TextChoices):
        PRODUCT_VIEW = "product_view", "Просмотр товара"
        SEARCH = "search", "Поиск"
        ADD_TO_CART = "add_to_cart", "Добавление в корзину"
        REMOVE_FROM_CART = "remove_from_cart", "Удаление из корзины"
        CHECKOUT = "checkout", "Оформление заказа"
        RENTAL_REQUEST = "rental_request", "Заявка на аренду"
        CONTACT = "contact", "Обращение"

    event_type = models.CharField("Тип", max_length=32, choices=Type.choices)
    # SET_NULL: удаление товара не должно уничтожать историю.
    product = models.ForeignKey(
        "catalog.Product", verbose_name="Товар", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="events",
    )
    category = models.ForeignKey(
        "catalog.Category", verbose_name="Категория", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="events",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Пользователь", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="events",
    )
    session_key = models.CharField("Сессия", max_length=40, blank=True, db_index=True)
    # Псевдонимный посетитель: хранится в ДАННЫХ сессии, поэтому переживает
    # вход в аккаунт (login() меняет ключ сессии, но сохраняет данные).
    # Именно по нему строится воронка «просмотр → корзина → заказ».
    visitor_id = models.CharField("Посетитель", max_length=40, blank=True, db_index=True)
    query = models.CharField("Поисковый запрос", max_length=200, blank=True)
    results_count = models.PositiveIntegerField("Найдено результатов", null=True, blank=True)
    quantity = models.PositiveIntegerField("Количество", null=True, blank=True)
    value = models.DecimalField("Сумма, сом", max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField("Время", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Событие"
        verbose_name_plural = "События"
        permissions = [("view_dashboard", "Может просматривать дашборд аналитики")]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["product", "event_type"]),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} @ {self.created_at:%Y-%m-%d %H:%M}"
