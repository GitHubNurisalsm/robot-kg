"""Корзина в сессии.

Хранит только {product_id: quantity}. Цены и названия НЕ хранятся:
итог всегда считается по актуальным данным из БД, поэтому подменить
или «заморозить» цену через сессию нельзя.

Остаток на складе не резервируется — это задача оформления заказа.
"""

from dataclasses import dataclass
from decimal import Decimal

from catalog.models import Product

from .forms import MAX_QTY_PER_ITEM

SESSION_KEY = "cart"
MAX_LINES = 50


class CartLimitError(Exception):
    """Превышено число разных товаров в корзине."""


class OutOfStockError(Exception):
    """Товара нет на складе."""


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int

    @property
    def unit_price(self) -> Decimal:
        return self.product.price

    @property
    def total(self) -> Decimal:
        return self.product.price * self.quantity

    @property
    def max_quantity(self) -> int:
        return min(self.product.stock, MAX_QTY_PER_ITEM)


def allowed_quantity(product: Product, requested: int) -> int:
    """Сколько реально можно положить: не больше остатка и лимита."""
    return max(0, min(requested, product.stock, MAX_QTY_PER_ITEM))


class Cart:
    def __init__(self, request):
        self.session = request.session
        raw = self.session.get(SESSION_KEY)
        # Защита от мусора в сессии: оставляем только пары int -> int > 0.
        self._data: dict[str, int] = {}
        if isinstance(raw, dict):
            for key, qty in raw.items():
                if str(key).isdigit() and isinstance(qty, int) and qty > 0:
                    self._data[str(key)] = qty
        self._lines_cache: list[CartLine] | None = None
        self.removed_names: list[str] = []
        self.adjusted_names: list[str] = []

    # ---- чтение -----------------------------------------------------------
    def __len__(self) -> int:
        """Общее количество единиц (для бейджа в шапке, без запросов к БД)."""
        return sum(self._data.values())

    def __contains__(self, product_id) -> bool:
        return str(product_id) in self._data

    def quantity_of(self, product_id) -> int:
        return self._data.get(str(product_id), 0)

    def lines(self) -> list[CartLine]:
        """Позиции с актуальными товарами (один запрос к БД).

        Снятые с продажи товары удаляются, количество сверх остатка
        уменьшается — изменения сохраняются в сессию.
        """
        if self._lines_cache is not None:
            return self._lines_cache
        ids = [int(k) for k in self._data]
        products = {
            p.pk: p
            for p in Product.objects.available().filter(pk__in=ids).select_related("category")
        }
        lines = []
        changed = False
        for key, qty in list(self._data.items()):
            product = products.get(int(key))
            if product is None:
                self.removed_names.append(f"товар #{key}")
                del self._data[key]
                changed = True
                continue
            allowed = allowed_quantity(product, qty)
            if allowed == 0:
                self.removed_names.append(product.name)
                del self._data[key]
                changed = True
                continue
            if allowed != qty:
                self.adjusted_names.append(product.name)
                self._data[key] = allowed
                changed = True
            lines.append(CartLine(product=product, quantity=allowed))
        if changed:
            self._save()
        self._lines_cache = lines
        return lines

    @property
    def total(self) -> Decimal:
        return sum((line.total for line in self.lines()), Decimal("0"))

    @property
    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.lines())

    # ---- запись -----------------------------------------------------------
    def add(self, product: Product, quantity: int) -> int:
        """Добавляет quantity к текущему. Возвращает фактически добавленное."""
        key = str(product.pk)
        if key not in self._data and len(self._data) >= MAX_LINES:
            raise CartLimitError
        if product.stock <= 0:
            raise OutOfStockError
        current = self._data.get(key, 0)
        new_qty = allowed_quantity(product, current + quantity)
        self._data[key] = new_qty
        self._save()
        return new_qty - current

    def set(self, product: Product, quantity: int) -> int:
        """Устанавливает количество; 0 — удалить. Возвращает итоговое."""
        if quantity <= 0:
            self.remove(product.pk)
            return 0
        new_qty = allowed_quantity(product, quantity)
        if new_qty == 0:
            self.remove(product.pk)
            return 0
        self._data[str(product.pk)] = new_qty
        self._save()
        return new_qty

    def remove(self, product_id) -> int:
        """Удаляет позицию. Возвращает удалённое количество (0, если не было)."""
        removed = self._data.pop(str(product_id), 0)
        if removed:
            self._save()
        return removed

    def clear(self) -> None:
        self._data = {}
        self._save()

    def _save(self) -> None:
        self.session[SESSION_KEY] = dict(self._data)
        self.session.modified = True
        self._lines_cache = None
