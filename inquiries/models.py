from django.conf import settings
from django.db import models


class ContactMessage(models.Model):
    """Обращение со страницы «Контакты»."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_messages",
    )
    name = models.CharField("Имя", max_length=150)
    email = models.EmailField("Email")
    phone = models.CharField("Телефон", max_length=32, blank=True)
    subject = models.CharField("Тема", max_length=200)
    message = models.TextField("Сообщение", max_length=5000)
    is_processed = models.BooleanField("Обработано", default=False, db_index=True)
    created_at = models.DateTimeField("Получено", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Обращение"
        verbose_name_plural = "Обращения"

    def __str__(self):
        return f"{self.subject} — {self.name}"
