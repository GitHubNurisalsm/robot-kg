"""Демо-данные для дашборда: события, заказы, аренда, обращения за N дней.

Все записи помечены и удаляются только они:
- события — visitor_id с префиксом DEMO_PREFIX;
- заказы, заявки, обращения — принадлежат пользователю DEMO_USERNAME.
Остатки на складе НЕ меняются (это синтетика, а не продажи).
Генерация детерминирована (--seed), повторный запуск пересоздаёт данные.
"""

import datetime
import random
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from analytics.models import Event
from catalog.models import Product
from inquiries.forms import SUBJECTS
from inquiries.models import ContactMessage
from orders.models import Order, OrderItem, generate_order_number
from rentals.models import RentalRequest

DEMO_USERNAME = "demo_analytics"
DEMO_PREFIX = "demo-"
QUERIES_FOUND = ["робот", "дрон", "манипулятор", "stembot", "квадрокоптер", "конструктор", "гуманоид"]
QUERIES_MISSING = ["пылесос", "3d принтер", "робот-собака", "lego", "vr очки"]
# Популярность в демо: дешёвые образовательные товары смотрят и покупают чаще.
POPULARITY = {"stembot-go": 10, "skyedu-quad": 8, "builder-x-200": 7, "stembot-pro": 6,
              "baiel-mini-h": 5, "armlab-a4": 4, "baiel-nova-h1": 4, "builder-lab-kit": 3,
              "servo-waiter-s2": 2, "promo-guide-p1": 2, "skyedu-racer": 2, "armlab-cobot-6": 1}
BATCH = 1000


def clear_demo(stdout=None) -> dict:
    User = get_user_model()
    user = User.objects.filter(username=DEMO_USERNAME).first()
    result = {"events": Event.objects.filter(visitor_id__startswith=DEMO_PREFIX).delete()[0]}
    if user:
        result["orders"] = Order.objects.filter(user=user).delete()[0]
        result["rentals"] = RentalRequest.objects.filter(user=user).delete()[0]
        result["contacts"] = ContactMessage.objects.filter(user=user).delete()[0]
        Event.objects.filter(user=user).delete()
        user.delete()
    return result


class Command(BaseCommand):
    help = "Генерирует помеченные демо-данные для дашборда аналитики (--clear — удалить их)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--visitors", type=int, default=25, help="посетителей в обычный день")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true", help="только удалить демо-данные")

    @transaction.atomic
    def handle(self, *args, days, visitors, seed, clear, **options):
        removed = clear_demo()
        if clear:
            self.stdout.write(self.style.SUCCESS(f"Демо-данные удалены: {removed}"))
            return
        if not 1 <= days <= 365:
            raise SystemExit("--days: от 1 до 365")

        products = list(Product.objects.available().select_related("category"))
        if not products:
            raise SystemExit("Каталог пуст — сначала выполните seed_demo")
        rentable = [p for p in products if p.is_rentable]
        weights = [POPULARITY.get(p.slug, 1) for p in products]
        found_counts = {q: Product.objects.available().filter(search_index__contains=q).count()
                        for q in QUERIES_FOUND}

        rng = random.Random(seed)
        user = get_user_model().objects.create_user(DEMO_USERNAME, "demo-analytics@example.test")
        user.set_unusable_password()
        user.is_active = False
        user.save()

        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        events, stamps = [], []
        orders_plan = []  # (created_at, [(product, qty)], visitor)
        rentals, contacts = [], []

        def at(day, hour_from=8, hour_to=23):
            return datetime.datetime.combine(
                day, datetime.time(rng.randint(hour_from, hour_to - 1), rng.randint(0, 59), rng.randint(0, 59)),
                tzinfo=tz)

        def ev(ts, vid, etype, **kw):
            events.append(Event(event_type=etype, visitor_id=vid, session_key=vid[:40], **kw))
            stamps.append(ts)

        for i in range(days):
            day = today - datetime.timedelta(days=days - 1 - i)
            weekend = day.weekday() >= 5
            trend = 1 + 0.5 * i / max(days - 1, 1)           # рост трафика
            n_visitors = max(1, int(rng.gauss(visitors * trend * (0.7 if weekend else 1), visitors * 0.15)))
            for _ in range(n_visitors):
                vid = f"{DEMO_PREFIX}{uuid.UUID(int=rng.getrandbits(128)).hex}"
                ts = at(day)
                if rng.random() < 0.3:
                    if rng.random() < 0.75:
                        q = rng.choice(QUERIES_FOUND)
                        ev(ts, vid, Event.Type.SEARCH, query=q, results_count=found_counts[q])
                    else:
                        ev(ts, vid, Event.Type.SEARCH, query=rng.choice(QUERIES_MISSING), results_count=0)
                viewed = {p.pk: p for p in rng.choices(products, weights=weights, k=rng.randint(1, 4))}.values()
                cart = []
                for p in viewed:
                    ts += datetime.timedelta(seconds=rng.randint(20, 300))
                    ev(ts, vid, Event.Type.PRODUCT_VIEW, product=p, category=p.category)
                    cheap = p.price < 100000
                    if rng.random() < (0.22 if cheap else 0.07):
                        qty = rng.choice([1, 1, 1, 2, 3]) if cheap else 1
                        ts += datetime.timedelta(seconds=rng.randint(10, 120))
                        ev(ts, vid, Event.Type.ADD_TO_CART, product=p, category=p.category,
                           quantity=qty, value=p.price * qty)
                        cart.append((p, qty))
                if cart and rng.random() < 0.38:
                    ts += datetime.timedelta(minutes=rng.randint(2, 20))
                    total = sum((p.price * q for p, q in cart), Decimal("0"))
                    ev(ts, vid, Event.Type.CHECKOUT, user=user, quantity=sum(q for _, q in cart), value=total)
                    orders_plan.append((ts, cart, total, (today - day).days))

            if rentable and rng.random() < 0.45:
                p = rng.choice(rentable)
                start = day + datetime.timedelta(days=rng.randint(2, 20))
                length = rng.choice([1, 1, 2, 3, 5, 7])
                age = (today - day).days
                status = rng.choices(
                    [s for s, _ in RentalRequest.Status.choices],
                    weights=[1, 1, 1, 0.5, 0.2] if age < 7 else [0.1, 0.3, 1, 0.6, 2])[0]
                ts = at(day, 9, 20)
                r = RentalRequest(product=p, user=user, full_name="Демо-клиент", phone="+996555000000",
                                  organization="Демо", start_date=start, end_date=start + datetime.timedelta(days=length - 1),
                                  status=status, price_per_day=p.rental_price_per_day,
                                  estimated_total=p.rental_price_per_day * length, session_key="demo")
                rentals.append((ts, r))
                vid = f"{DEMO_PREFIX}{uuid.UUID(int=rng.getrandbits(128)).hex}"
                ev(ts, vid, Event.Type.RENTAL_REQUEST, product=p, category=p.category,
                   quantity=length, value=r.estimated_total)

            if rng.random() < 0.3:
                ts = at(day, 9, 20)
                subject = rng.choice([v for v, _ in SUBJECTS if v])
                contacts.append((ts, ContactMessage(user=user, name="Демо-клиент", email="demo-analytics@example.test",
                                                    subject=subject, message="Демонстрационное обращение.",
                                                    is_processed=(today - day).days > 3)))
                ev(ts, f"{DEMO_PREFIX}{uuid.UUID(int=rng.getrandbits(128)).hex}", Event.Type.CONTACT)

        created = Event.objects.bulk_create(events, batch_size=BATCH)
        self._restamp(Event, created, stamps)

        orders, items, order_stamps = [], [], []
        for ts, cart, total, age in orders_plan:
            status = (rng.choices([Order.Status.NEW, Order.Status.CONFIRMED, Order.Status.CANCELLED], [3, 2, 0.4])[0]
                      if age < 3 else
                      rng.choices([Order.Status.COMPLETED, Order.Status.SHIPPED, Order.Status.CANCELLED], [8, 1, 1])[0])
            o = Order(number=generate_order_number(), user=user, full_name="Демо-покупатель", phone="+996555000000",
                      email="demo-analytics@example.test", total=total, status=status, checkout_token=uuid.uuid4())
            orders.append(o)
            order_stamps.append(ts)
            items.append(cart)
        orders = Order.objects.bulk_create(orders, batch_size=BATCH)
        self._restamp(Order, orders, order_stamps, extra=("updated_at",))
        OrderItem.objects.bulk_create([
            OrderItem(order=o, product=p, product_name=p.name, unit_price=p.price, quantity=q, line_total=p.price * q)
            for o, cart in zip(orders, items) for p, q in cart
        ], batch_size=BATCH)

        r_objs = RentalRequest.objects.bulk_create([r for _, r in rentals], batch_size=BATCH)
        self._restamp(RentalRequest, r_objs, [ts for ts, _ in rentals])
        c_objs = ContactMessage.objects.bulk_create([c for _, c in contacts], batch_size=BATCH)
        self._restamp(ContactMessage, c_objs, [ts for ts, _ in contacts])

        self.stdout.write(self.style.SUCCESS(
            f"Демо за {days} дн.: событий {len(created)}, заказов {len(orders)}, "
            f"аренд {len(r_objs)}, обращений {len(c_objs)}. Удалить: seed_analytics --clear"))

    @staticmethod
    def _restamp(model, objs, stamps, extra=()):
        """bulk_create ставит auto_now_add=now; возвращаем нужные даты через bulk_update."""
        for o, ts in zip(objs, stamps):
            o.created_at = ts
            for f in extra:
                setattr(o, f, ts)
        model.objects.bulk_update(objs, ["created_at", *extra], batch_size=BATCH)
