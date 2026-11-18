# Robot.KG.Baiel

Учебный интернет-магазин робототехники на Django. «Технологии будущего сегодня.»

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # демо-категории и товары (можно запускать повторно)
python manage.py createsuperuser    # доступ к /admin/
python manage.py runserver
```

Откройте http://127.0.0.1:8000/ и http://127.0.0.1:8000/admin/.

## Структура

| Приложение  | Назначение |
|-------------|------------|
| `config/`   | настройки, корневые URL |
| `accounts/` | собственная модель пользователя |
| `core/`     | главная, общий контекст шаблонов, фильтры |
| `catalog/`  | категории, товары, характеристики, `seed_demo` |
| `rentals/`  | заявки на аренду |
| `inquiries/`| обращения со страницы «Контакты» |
| `templates/`, `static/` | общие шаблоны и статика |

## Проверки

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Переменные окружения для не-dev запуска: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`.
