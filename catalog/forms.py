from decimal import Decimal

from django import forms

from .models import Category

SORT_CHOICES = [
    ("new", "Сначала новые"),
    ("price_asc", "Сначала дешёвые"),
    ("price_desc", "Сначала дорогие"),
    ("name", "По названию"),
]
# Белый список: пользовательский ввод никогда не попадает в order_by напрямую.
SORT_ORDERING = {
    "new": ("-created_at", "-id"),
    "price_asc": ("price", "id"),
    "price_desc": ("-price", "id"),
    "name": ("name", "id"),
}

MAX_PRICE = Decimal("1000000000")


class ProductFilterForm(forms.Form):
    q = forms.CharField(
        label="Поиск", required=False, max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "Название или описание", "type": "search"}),
    )
    category = forms.ModelChoiceField(
        label="Категория", required=False, queryset=Category.objects.none(),
        to_field_name="slug", empty_label="Все категории",
    )
    min_price = forms.DecimalField(
        label="Цена от", required=False, min_value=0, max_value=MAX_PRICE, decimal_places=2,
        widget=forms.NumberInput(attrs={"placeholder": "0", "step": "1"}),
    )
    max_price = forms.DecimalField(
        label="Цена до", required=False, min_value=0, max_value=MAX_PRICE, decimal_places=2,
        widget=forms.NumberInput(attrs={"placeholder": "∞", "step": "1"}),
    )
    in_stock = forms.BooleanField(label="Только в наличии", required=False)
    rentable = forms.BooleanField(label="Доступно для аренды", required=False)
    sort = forms.ChoiceField(label="Сортировка", required=False, choices=SORT_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.active()

    def clean(self):
        cleaned = super().clean()
        lo, hi = cleaned.get("min_price"), cleaned.get("max_price")
        if lo is not None and hi is not None and lo > hi:
            self.add_error("max_price", "«Цена до» не может быть меньше «Цены от».")
        return cleaned
