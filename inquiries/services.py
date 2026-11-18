import time
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from analytics.models import Event
from analytics.services import track

from .models import ContactMessage

DUPLICATE_WINDOW = timedelta(minutes=10)
RATE_LIMIT = 5              # обращений
RATE_WINDOW_SECONDS = 3600  # за час, на сессию
RATE_SESSION_KEY = "contact_sent_at"


class RateLimited(Exception):
    pass


@dataclass
class ContactResult:
    message: ContactMessage | None
    created: bool


def _recent_timestamps(request) -> list[float]:
    now = time.time()
    raw = request.session.get(RATE_SESSION_KEY, [])
    if not isinstance(raw, list):
        raw = []
    return [t for t in raw if isinstance(t, (int, float)) and now - t < RATE_WINDOW_SECONDS]


def submit_contact(request, form) -> ContactResult:
    """Сохраняет обращение из валидной формы.

    - honeypot заполнен → ничего не сохраняем, но отвечаем «успехом» (не учим бота);
    - лимит RATE_LIMIT в час на сессию → RateLimited;
    - то же сообщение с того же email за DUPLICATE_WINDOW → дубль не создаём.
    """
    if form.is_spam:
        return ContactResult(None, created=False)

    sent = _recent_timestamps(request)
    if len(sent) >= RATE_LIMIT:
        raise RateLimited

    data = form.cleaned_data
    existing = ContactMessage.objects.filter(
        email=data["email"], subject=data["subject"], message=data["message"],
        created_at__gte=timezone.now() - DUPLICATE_WINDOW,
    ).first()
    if existing:
        return ContactResult(existing, created=False)

    msg = form.save(commit=False)
    msg.user = request.user if request.user.is_authenticated else None
    msg.save()

    request.session[RATE_SESSION_KEY] = [*sent, time.time()]
    track(request, Event.Type.CONTACT)
    return ContactResult(msg, created=True)
