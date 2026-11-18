from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from analytics.models import Event
from analytics.services import track

from .models import RentalRequest

DUPLICATE_WINDOW = timedelta(minutes=10)


@dataclass
class RentalResult:
    rental: RentalRequest
    created: bool


def _session_key(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key or ""


def create_rental_request(request, form) -> RentalResult:
    """Создаёт заявку из валидной формы.

    - цена фиксируется на момент заявки (снимок);
    - повтор той же заявки той же сессией за DUPLICATE_WINDOW не создаёт дубль
      (двойной клик, F5 после POST, кнопка «назад»).
    """
    data = form.cleaned_data
    product = data["product"]
    session_key = _session_key(request)

    with transaction.atomic():
        existing = RentalRequest.objects.filter(
            session_key=session_key,
            product=product,
            start_date=data["start_date"],
            end_date=data["end_date"],
            phone=data["phone"],
            created_at__gte=timezone.now() - DUPLICATE_WINDOW,
        ).first()
        if existing:
            return RentalResult(existing, created=False)

        rental = form.save(commit=False)
        rental.session_key = session_key
        rental.user = request.user if request.user.is_authenticated else None
        rental.price_per_day = product.rental_price_per_day
        rental.estimated_total = product.rental_price_per_day * rental.days
        rental.status = RentalRequest.Status.NEW
        rental.save()

    # Аналитика — после успешного создания, вне бизнес-транзакции.
    track(request, Event.Type.RENTAL_REQUEST, product=product, category=product.category,
          quantity=rental.days, value=rental.estimated_total)
    return RentalResult(rental, created=True)
