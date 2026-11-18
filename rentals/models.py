from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class RentalRequest(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новая"
        IN_PROGRESS = "in_progress", "В работе"
        APPROVED = "approved", "Одобрена"
        REJECTED = "rejected", "Отклонена"
        COMPLETED = "completed", "Завершена"

    # Допустимые переходы статусов. Отклонена/Завершена — конечные.
    TRANSITIONS = {
        Status.NEW: {Status.IN_PROGRESS, Status.APPROVED, Status.REJECTED},
        Status.IN_PROGRESS: {Status.APPROVED, Status.REJECTED},
        Status.APPROVED: {Status.COMPLETED, Status.REJECTED},
        Status.REJECTED: set(),
        Status.COMPLETED: set(),
    }

    product = models.ForeignKey(
        "catalog.Product",
        verbose_name="Робот",
        on_delete=models.PROTECT,  # заявки — история, товар с заявками удалять нельзя
        related_name="rental_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rental_requests",
    )
    full_name = models.CharField("Имя", max_length=150)
    phone = models.CharField("Телефон", max_length=32)
    email = models.EmailField("Email", blank=True)
    organization = models.CharField("Организация", max_length=200, blank=True)
    start_date = models.DateField("Дата начала")
    end_date = models.DateField("Дата окончания")
    comment = models.TextField("Комментарий", blank=True, max_length=2000)
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.NEW, db_index=True
    )
    # Снимок цены на момент заявки: последующее изменение цены товара
    # не должно менять уже рассчитанную заявку и аналитику.
    price_per_day = models.DecimalField(
        "Цена за сутки на момент заявки, сом", max_digits=12, decimal_places=2, null=True, blank=True
    )
    estimated_total = models.DecimalField(
        "Предварительная стоимость, сом", max_digits=14, decimal_places=2, null=True, blank=True
    )
    session_key = models.CharField("Сессия", max_length=40, blank=True, editable=False)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Заявка на аренду"
        verbose_name_plural = "Заявки на аренду"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")), name="rental_end_after_start"
            ),
        ]

    def __str__(self):
        return f"{self.product} — {self.full_name} ({self.start_date}–{self.end_date})"

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Дата окончания не может быть раньше даты начала."})
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if old and old != self.status and self.status not in self.TRANSITIONS[old]:
                raise ValidationError({
                    "status": (
                        f"Нельзя перевести заявку из «{self.Status(old).label}» "
                        f"в «{self.Status(self.status).label}»."
                    )
                })
