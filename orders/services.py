"""Оформление и отмена заказа.

Граница транзакции — весь place_order(): списание остатков, создание заказа
и позиций. Любая ошибка откатывает всё — частичного списания не бывает.

Защита остатка от гонок: условный UPDATE
    UPDATE product SET stock = stock - N WHERE id = X AND stock >= N
Если обновлено 0 строк — товара не хватило. select_for_update() здесь
не используется намеренно: в SQLite Django его молча игнорирует.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from analytics.models import Event
from analytics.services import track
from cart.cart import Cart
from catalog.models import Product

from .models import Order, OrderItem, generate_order_number

NUMBER_ATTEMPTS = 5


class CheckoutError(Exception):
    """Базовая ошибка оформления — заказ не создан, остатки не изменены."""


class EmptyCart(CheckoutError):
    pass


class CartChanged(CheckoutError):
    """Корзина скорректирована (товар снят / остаток уменьшился) — покажите её."""


class PriceChanged(CheckoutError):
    def __init__(self, new_total: Decimal):
        super().__init__(new_total)
        self.new_total = new_total


class InsufficientStock(CheckoutError):
    def __init__(self, product_name: str):
        super().__init__(product_name)
        self.product_name = product_name


@dataclass
class OrderResult:
    order: Order
    created: bool


def _decrement_stock(product_id: int, quantity: int) -> bool:
    updated = Product.objects.filter(
        pk=product_id, stock__gte=quantity, is_available=True
    ).update(stock=F("stock") - quantity)
    return updated == 1


def _create_order(**fields) -> Order:
    """Создаёт заказ с уникальным случайным номером (повтор при коллизии)."""
    for attempt in range(NUMBER_ATTEMPTS):
        try:
            with transaction.atomic():  # savepoint: коллизия номера не ломает внешнюю транзакцию
                return Order.objects.create(number=generate_order_number(), **fields)
        except IntegrityError:
            # Коллизия по checkout_token — это не про номер; пробрасываем.
            if Order.objects.filter(checkout_token=fields["checkout_token"]).exists():
                raise
            if attempt == NUMBER_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def place_order(request, form) -> OrderResult:
    user = request.user
    data = form.cleaned_data
    token: uuid.UUID = data["checkout_token"]

    # Повтор той же формы (двойной клик, F5, «назад») — возвращаем уже созданный заказ.
    existing = Order.objects.filter(checkout_token=token, user=user).first()
    if existing:
        return OrderResult(existing, created=False)

    cart = Cart(request)
    lines = cart.lines()
    if cart.removed_names or cart.adjusted_names:
        raise CartChanged
    if not lines:
        raise EmptyCart

    total = sum((line.total for line in lines), Decimal("0"))
    if total != data["expected_total"]:
        raise PriceChanged(total)

    try:
        with transaction.atomic():
            # Сортировка по id — единый порядок блокировок (важно для PostgreSQL).
            for line in sorted(lines, key=lambda l: l.product.pk):
                if not _decrement_stock(line.product.pk, line.quantity):
                    raise InsufficientStock(line.product.name)

            order = _create_order(
                user=user,
                full_name=data["full_name"],
                phone=data["phone"],
                email=data["email"],
                delivery_method=data["delivery_method"],
                address=data["address"] if data["delivery_method"] == Order.Delivery.DELIVERY else "",
                comment=data["comment"],
                total=total,
                checkout_token=token,
                status=Order.Status.NEW,
            )
            OrderItem.objects.bulk_create([
                OrderItem(order=order, product=line.product, product_name=line.product.name,
                          unit_price=line.unit_price, quantity=line.quantity, line_total=line.total)
                for line in lines
            ])
            items_count = sum(line.quantity for line in lines)
            # Аналитика — только после успешного commit.
            transaction.on_commit(lambda: track(
                request, Event.Type.CHECKOUT, quantity=items_count, value=total
            ))
    except IntegrityError:
        # Параллельный запрос с тем же токеном успел первым — его заказ и вернём.
        existing = Order.objects.filter(checkout_token=token, user=user).first()
        if existing:
            return OrderResult(existing, created=False)
        raise

    cart.clear()
    return OrderResult(order, created=True)


def cancel_order(order_id: int) -> bool:
    """Отменяет заказ и возвращает товар на склад. Идемпотентна.

    Условный UPDATE статуса гарантирует, что возврат на склад произойдёт
    ровно один раз, даже при двух одновременных отменах.
    """
    with transaction.atomic():
        changed = Order.objects.filter(
            pk=order_id, status__in=Order.CANCELLABLE
        ).update(status=Order.Status.CANCELLED, updated_at=timezone.now())  # update() обходит auto_now
        if not changed:
            return False
        for item in OrderItem.objects.filter(order_id=order_id).only("product_id", "quantity"):
            Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)
    return True
