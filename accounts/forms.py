import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import User

PHONE_RE = re.compile(r"^\+?[\d\s()\-]{7,20}$")


class SignUpForm(UserCreationForm):
    email = forms.EmailField(label="Email", max_length=254)
    first_name = forms.CharField(label="Имя", max_length=150, required=False)
    phone = forms.CharField(
        label="Телефон", max_length=32, required=False,
        widget=forms.TextInput(attrs={"placeholder": "+996 555 123 456", "autocomplete": "tel", "inputmode": "tel"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        # Белый список полей: is_staff/is_superuser и пр. не назначить через POST.
        fields = ("username", "email", "first_name", "phone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Латиница или кириллица, цифры и @/./+/-/_ — до 150 символов."
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True})
        self.fields["email"].widget.attrs.update({"autocomplete": "email"})
        self.fields["first_name"].widget.attrs.update({"autocomplete": "given-name"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Быстрая проверка для понятной ошибки; гарантию даёт ограничение в БД.
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже зарегистрирован.")
        return email

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone and not PHONE_RE.match(phone):
            raise forms.ValidationError("Введите телефон в формате +996 555 123 456.")
        return phone


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"autocomplete": "username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})
