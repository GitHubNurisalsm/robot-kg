import re

from django import forms

from .models import Order

PHONE_RE = re.compile(r"^\+?[\d\s()\-]{7,20}$")


class CheckoutForm(forms.ModelForm):
    # Служебные поля: токен идемпотентности и сумма, которую видел покупатель.
    checkout_token = forms.UUIDField(widget=forms.HiddenInput)
    expected_total = forms.DecimalField(widget=forms.HiddenInput, max_digits=14, decimal_places=2)

    class Meta:
        model = Order
        # Белый список: status, total, user, number задаёт только сервер.
        fields = ("full_name", "phone", "email", "delivery_method", "address", "comment")
        widgets = {
            "delivery_method": forms.RadioSelect,
            "full_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "phone": forms.TextInput(attrs={"placeholder": "+996 555 123 456", "autocomplete": "tel", "inputmode": "tel"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "address": forms.TextInput(attrs={"placeholder": "Город, улица, дом, квартира", "autocomplete": "street-address"}),
            "comment": forms.Textarea(attrs={"rows": 3, "placeholder": "Удобное время, этаж, реквизиты для счёта"}),
        }

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not PHONE_RE.match(phone):
            raise forms.ValidationError("Введите телефон в формате +996 555 123 456.")
        return phone

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("delivery_method") == Order.Delivery.DELIVERY and not (cleaned.get("address") or "").strip():
            self.add_error("address", "Укажите адрес доставки.")
        return cleaned
