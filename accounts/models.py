from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class User(AbstractUser):
    """Собственная модель пользователя.

    Создана с первой миграции, чтобы в будущем можно было добавлять поля
    (телефон и т.п.) без болезненной замены AUTH_USER_MODEL.
    """

    phone = models.CharField("Телефон", max_length=32, blank=True)

    class Meta(AbstractUser.Meta):
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        constraints = [
            # Email уникален без учёта регистра. Пустые email (например, у
            # пользователей, созданных через createsuperuser без email) не мешают.
            models.UniqueConstraint(
                Lower("email"),
                name="user_email_ci_unique",
                condition=~Q(email=""),
                violation_error_message="Пользователь с таким email уже зарегистрирован.",
            ),
        ]
