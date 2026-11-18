"""Заполняет каталог демонстрационными данными.

Идемпотентна: повторный запуск обновляет записи по slug, а не создаёт дубли.
Все названия моделей вымышленные.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, Illustration, Product, ProductSpecification

CATEGORIES = [
    {
        "slug": "humanoid",
        "name": "Гуманоидные роботы",
        "description": "Человекоподобные роботы для презентаций, ресепшн-зон и исследований.",
        "illustration": Illustration.HUMANOID,
        "sort_order": 1,
    },
    {
        "slug": "education",
        "name": "Образовательные роботы",
        "description": "Программируемые роботы для школ, кружков и STEM-кабинетов.",
        "illustration": Illustration.EDUCATIONAL,
        "sort_order": 2,
    },
    {
        "slug": "kits",
        "name": "Конструкторы",
        "description": "Наборы для сборки и программирования роботов с нуля.",
        "illustration": Illustration.KIT,
        "sort_order": 3,
    },
    {
        "slug": "drones",
        "name": "Дроны",
        "description": "Квадрокоптеры для обучения, съёмки и соревнований.",
        "illustration": Illustration.DRONE,
        "sort_order": 4,
    },
    {
        "slug": "industrial",
        "name": "Манипуляторы",
        "description": "Настольные и промышленные роботы-манипуляторы для лабораторий.",
        "illustration": Illustration.INDUSTRIAL,
        "sort_order": 5,
    },
    {
        "slug": "service",
        "name": "Сервисные роботы",
        "description": "Роботы-официанты, промоутеры и гиды для бизнеса и мероприятий.",
        "illustration": Illustration.SERVICE,
        "sort_order": 6,
    },
]

# (category_slug, slug, name, short, description, price, old_price, stock,
#  featured, rentable, rental_price, illustration, specs)
PRODUCTS = [
    (
        "humanoid", "baiel-nova-h1", "Baiel Nova H1",
        "Гуманоид ростом 120 см с распознаванием речи и лиц.",
        "Nova H1 — флагманский гуманоидный робот для выставок, ресепшн-зон и университетских "
        "лабораторий. Поддерживает диалог на русском и английском языках, распознаёт лица, "
        "жестикулирует и перемещается по заданному маршруту. SDK на Python.",
        "1850000", "1990000", 2, True, True, "45000", Illustration.HUMANOID,
        [("Рост", "120 см"), ("Вес", "28 кг"), ("Степени свободы", "26"),
         ("Автономность", "до 4 ч"), ("Языки", "русский, английский"), ("SDK", "Python, ROS 2")],
    ),
    (
        "humanoid", "baiel-mini-h", "Baiel Mini H",
        "Компактный гуманоид для обучения программированию движений.",
        "Mini H — настольный гуманоид высотой 40 см. Идеален для изучения кинематики, "
        "программирования танцев и соревнований по робофутболу.",
        "289000", None, 6, True, True, "9000", Illustration.HUMANOID,
        [("Рост", "40 см"), ("Сервоприводы", "18"), ("Аккумулятор", "2200 мА·ч"),
         ("Программирование", "Blockly, Python")],
    ),
    (
        "education", "stembot-go", "STEMBot Go",
        "Первый робот школьника: колёсная платформа с датчиками.",
        "STEMBot Go обучает основам алгоритмов: движение по линии, объезд препятствий, "
        "управление со смартфона. В комплекте — 24 урока для учителя.",
        "18900", "22500", 40, True, False, None, Illustration.EDUCATIONAL,
        [("Возраст", "8+"), ("Датчики", "линии, расстояния, света"), ("Связь", "Bluetooth 5.0"),
         ("Программирование", "Scratch, Blockly")],
    ),
    (
        "education", "stembot-pro", "STEMBot Pro",
        "Расширенная платформа с камерой и модулем ИИ.",
        "STEMBot Pro добавляет камеру с распознаванием объектов, манипулятор-захват и Wi-Fi. "
        "Подходит для олимпиадной подготовки и проектной деятельности.",
        "54900", None, 15, True, True, "2500", Illustration.EDUCATIONAL,
        [("Возраст", "12+"), ("Камера", "2 Мп, распознавание цветов и меток"),
         ("Связь", "Wi-Fi, Bluetooth"), ("Программирование", "Python, C++")],
    ),
    (
        "kits", "builder-x-200", "Builder X-200",
        "Конструктор на 200+ деталей: 6 моделей в одном наборе.",
        "Набор Builder X-200 позволяет собрать шесть разных роботов — от гусеничного вездехода "
        "до манипулятора. Металлические детали, контроллер совместим с Arduino.",
        "12500", None, 60, False, False, None, Illustration.KIT,
        [("Деталей", "214"), ("Моделей", "6"), ("Контроллер", "совместим с Arduino"),
         ("Материал", "алюминий, ABS")],
    ),
    (
        "kits", "builder-lab-kit", "Builder Lab Kit",
        "Класс-комплект на 12 учеников с методическими материалами.",
        "Готовое решение для STEM-кабинета: 6 наборов, кейсы для хранения, "
        "зарядная станция и курс на 36 академических часов.",
        "168000", "185000", 5, True, False, None, Illustration.KIT,
        [("Учеников", "12"), ("Наборов", "6"), ("Курс", "36 ак. часов"), ("Гарантия", "12 месяцев")],
    ),
    (
        "drones", "skyedu-quad", "SkyEdu Quad",
        "Учебный квадрокоптер с защитой винтов и программированием полёта.",
        "SkyEdu Quad создан для занятий в помещении: лёгкий корпус, защита пропеллеров, "
        "оптический датчик позиционирования. Программируется на Python и блоками.",
        "24900", None, 25, True, True, "1500", Illustration.DRONE,
        [("Вес", "92 г"), ("Время полёта", "до 12 мин"), ("Камера", "720p"),
         ("Программирование", "Python, Scratch")],
    ),
    (
        "drones", "skyedu-racer", "SkyEdu Racer FPV",
        "Гоночный FPV-дрон для соревнований.",
        "Racer FPV — скоростной дрон с цифровой видеосвязью для подготовки к соревнованиям "
        "по дрон-рейсингу. Поставляется с очками и пультом.",
        "68500", None, 0, False, False, None, Illustration.DRONE,
        [("Скорость", "до 120 км/ч"), ("Видео", "цифровое, 1080p"), ("Время полёта", "до 6 мин")],
    ),
    (
        "industrial", "armlab-a4", "ArmLab A4",
        "Настольный 4-осевой манипулятор с захватом и присоской.",
        "ArmLab A4 — точный настольный манипулятор для обучения робототехнике, "
        "лазерной гравировки и 3D-печати. Повторяемость позиционирования 0,2 мм.",
        "145000", None, 4, True, True, "6000", Illustration.INDUSTRIAL,
        [("Оси", "4"), ("Нагрузка", "500 г"), ("Радиус", "320 мм"), ("Точность", "±0,2 мм")],
    ),
    (
        "industrial", "armlab-cobot-6", "ArmLab Cobot 6",
        "Коллаборативный 6-осевой робот для лабораторий и малого производства.",
        "Cobot 6 безопасно работает рядом с человеком благодаря датчикам усилия. "
        "Программирование обучением — достаточно провести рукой по траектории.",
        "1290000", None, 1, False, False, None, Illustration.INDUSTRIAL,
        [("Оси", "6"), ("Нагрузка", "5 кг"), ("Радиус", "850 мм"), ("Защита", "IP54")],
    ),
    (
        "service", "servo-waiter-s2", "ServoWaiter S2",
        "Робот-официант с тремя подносами и автономной навигацией.",
        "ServoWaiter S2 доставляет блюда к столам, объезжает гостей и возвращается на базу. "
        "Отлично подходит для ресторанов и банкетов.",
        "720000", "790000", 3, True, True, "18000", Illustration.SERVICE,
        [("Подносов", "3"), ("Нагрузка", "до 30 кг"), ("Автономность", "до 12 ч"),
         ("Навигация", "лидар + камеры")],
    ),
    (
        "service", "promo-guide-p1", "PromoGuide P1",
        "Робот-промоутер с сенсорным экраном для выставок.",
        "PromoGuide P1 приветствует посетителей, показывает презентации и собирает контакты. "
        "Популярен для аренды на выставки и открытия магазинов.",
        "540000", None, 2, False, True, "15000", Illustration.SERVICE,
        [("Экран", "21,5\" сенсорный"), ("Автономность", "до 8 ч"), ("Рост", "135 см")],
    ),
]


class Command(BaseCommand):
    help = "Заполняет каталог демонстрационными категориями и товарами Robot.KG.Baiel."

    @transaction.atomic
    def handle(self, *args, **options):
        categories = {}
        for data in CATEGORIES:
            slug = data["slug"]
            defaults = {k: v for k, v in data.items() if k != "slug"}
            categories[slug], _ = Category.objects.update_or_create(slug=slug, defaults=defaults)

        created_count = 0
        for (cat_slug, slug, name, short, desc, price, old_price, stock,
             featured, rentable, rental_price, illustration, specs) in PRODUCTS:
            product, created = Product.objects.update_or_create(
                slug=slug,
                defaults={
                    "category": categories[cat_slug],
                    "name": name,
                    "short_description": short,
                    "description": desc,
                    "price": Decimal(price),
                    "old_price": Decimal(old_price) if old_price else None,
                    "stock": stock,
                    "is_available": True,
                    "is_featured": featured,
                    "is_rentable": rentable,
                    "rental_price_per_day": Decimal(rental_price) if rental_price else None,
                    "illustration": illustration,
                },
            )
            created_count += created
            product.specs.all().delete()
            ProductSpecification.objects.bulk_create(
                ProductSpecification(product=product, name=n, value=v, sort_order=i)
                for i, (n, v) in enumerate(specs)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: категорий {len(categories)}, товаров {len(PRODUCTS)} "
                f"(новых {created_count})."
            )
        )
