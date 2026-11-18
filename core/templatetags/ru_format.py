from django import template

register = template.Library()


@register.filter
def ru_plural(value, forms: str) -> str:
    """Русское склонение по числу: {{ n|ru_plural:"товар,товара,товаров" }}."""
    try:
        n = abs(int(value))
    except (TypeError, ValueError):
        n = 0
    one, few, many = (f.strip() for f in forms.split(","))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
