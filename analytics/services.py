"""Запись аналитических событий.

Аналитика — вторичная функция: её сбой не должен ломать страницу
или откатывать бизнес-транзакцию (заказ, заявку).
"""

import logging
import re
import uuid
from datetime import timedelta

from django.db import DatabaseError, transaction
from django.utils import timezone

from .models import Event

logger = logging.getLogger(__name__)

# Окно, в котором повторный просмотр/поиск той же сессией не считается.
DEDUP_WINDOW = timedelta(minutes=30)
DEDUP_TYPES = {Event.Type.PRODUCT_VIEW, Event.Type.SEARCH}
MAX_QUERY_LEN = 200
VISITOR_SESSION_KEY = "visitor_id"
# Явные боты и скрипты. Пустой User-Agent НЕ считается ботом (тестовый клиент,
# некоторые браузеры с приватностью). Сам User-Agent нигде не сохраняется.
BOT_UA_RE = re.compile(
    r"bot|crawl|spider|slurp|curl/|wget|python-requests|python-urllib|httpx|aiohttp|"
    r"headless|phantomjs|scrapy|go-http-client|okhttp|java/|libwww",
    re.IGNORECASE,
)


def normalize_query(q: str) -> str:
    return " ".join(q.lower().split())[:MAX_QUERY_LEN]


def _session_key(request) -> str:
    session = request.session
    if not session.session_key:
        session.save()  # гарантируем псевдонимный идентификатор посетителя
    return session.session_key or ""


def is_bot(request) -> bool:
    return bool(BOT_UA_RE.search(request.META.get("HTTP_USER_AGENT", "")))


def visitor_id(request) -> str:
    vid = request.session.get(VISITOR_SESSION_KEY)
    if not isinstance(vid, str) or not vid:
        vid = uuid.uuid4().hex
        request.session[VISITOR_SESSION_KEY] = vid
    return vid


def should_track(request) -> bool:
    # Сотрудники тестируют сайт и искажают метрики — их не считаем. Боты тоже.
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return False
    return not is_bot(request)


def track(request, event_type: str, **fields) -> Event | None:
    """Записать событие. Никогда не бросает исключение наружу."""
    if not should_track(request):
        return None
    try:
        vid = visitor_id(request)
        session_key = _session_key(request)
        if "query" in fields and fields["query"]:
            fields["query"] = normalize_query(fields["query"])
        user = request.user if request.user.is_authenticated else None

        # Savepoint: ошибка записи не «отравит» внешнюю транзакцию.
        with transaction.atomic():
            if event_type in DEDUP_TYPES:
                dup = Event.objects.filter(
                    event_type=event_type,
                    visitor_id=vid,
                    created_at__gte=timezone.now() - DEDUP_WINDOW,
                    product=fields.get("product"),
                    query=fields.get("query", ""),
                ).exists()
                if dup:
                    return None
            return Event.objects.create(
                event_type=event_type, session_key=session_key, visitor_id=vid, user=user, **fields
            )
    except DatabaseError:
        logger.exception("Не удалось записать аналитическое событие %s", event_type)
        return None
