import datetime
import re

from django import forms
from django.utils import timezone

from catalog.models import Product

from .models import RentalRequest

PHONE_RE = re.compile(r"^\+?[\d\s()\-]{7,20}$")
MIN_LEAD_DAYS = 1        # начало аренды — не раньше завтрашнего дня
MAX_RENTAL_DAYS = 90
MAX_ADVANCE_DAYS = 365


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class RentableProductChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.name} — {obj.rental_price_per_day:,.0f} сом/сутки".replace(",", " ")


class RentalRequestForm(forms.ModelForm):
    product = RentableProductChoice(
        label="Робот", queryset=Product.objects.none(), to_field_name="slug",
        empty_label="Выберите робота",
        error_messages={"invalid_choice": "Этот робот недоступен для аренды."},
    )

    class Meta:
        model = RentalRequest
        # Белый список: status, user, цены задаёт сервер, а не клиент.
        fields = ("product", "start_date", "end_date", "full_name", "phone",
                  "email", "organization", "comment")
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "comment": forms.Textarea(attrs={"rows": 4, "placeholder": "Мероприятие, адрес, пожелания"}),
            "phone": forms.TextInput(attrs={"placeholder": "+996 555 123 456", "autocomplete": "tel", "inputmode": "tel"}),
            "full_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "organization": forms.TextInput(attrs={"autocomplete": "organization"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.rentable().order_by("name")
        today = timezone.localdate()
        self.min_start = today + datetime.timedelta(days=MIN_LEAD_DAYS)
        self.max_start = today + datetime.timedelta(days=MAX_ADVANCE_DAYS)
        for name in ("start_date", "end_date"):
            self.fields[name].widget.attrs.update(
                {"min": self.min_start.isoformat(), "max": (self.max_start + datetime.timedelta(days=MAX_RENTAL_DAYS)).isoformat()}
            )

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError("Введите телефон в формате +996 555 123 456.")
        return phone

    def clean_start_date(self):
        start = self.cleaned_data["start_date"]
        if start < self.min_start:
            raise forms.ValidationError(
                f"Аренда возможна не раньше {self.min_start:%d.%m.%Y}."
            )
        if start > self.max_start:
            raise forms.ValidationError("Бронировать можно не более чем на год вперёд.")
        return start

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end:
            if end < start:
                self.add_error("end_date", "Дата окончания не может быть раньше даты начала.")
            elif (end - start).days + 1 > MAX_RENTAL_DAYS:
                self.add_error("end_date", f"Максимальный срок аренды — {MAX_RENTAL_DAYS} дней.")
        return cleaned
