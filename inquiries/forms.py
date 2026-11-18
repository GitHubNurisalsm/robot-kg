import re

from django import forms

from .models import ContactMessage

PHONE_RE = re.compile(r"^\+?[\d\s()\-]{7,20}$")
MIN_MESSAGE_LEN = 10

SUBJECTS = [
    ("", "Выберите тему"),
    ("Покупка оборудования", "Покупка оборудования"),
    ("Аренда роботов", "Аренда роботов"),
    ("Сервис и гарантия", "Сервис и гарантия"),
    ("Решения для образования", "Решения для образования"),
    ("Сотрудничество", "Сотрудничество"),
    ("Другое", "Другое"),
]


class ContactForm(forms.ModelForm):
    subject = forms.ChoiceField(label="Тема", choices=SUBJECTS)
    # Honeypot: поле скрыто от людей CSS-ом, боты его заполняют.
    website = forms.CharField(required=False, label="Не заполняйте это поле",
                              widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = ContactMessage
        # Белый список: is_processed и user задаёт сервер.
        fields = ("name", "email", "phone", "subject", "message")
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "phone": forms.TextInput(attrs={"placeholder": "+996 555 123 456", "autocomplete": "tel", "inputmode": "tel"}),
            "message": forms.Textarea(attrs={"rows": 6, "placeholder": "Опишите ваш вопрос"}),
        }

    @property
    def is_spam(self) -> bool:
        return bool(self.cleaned_data.get("website"))

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_phone(self):
        phone = self.cleaned_data.get("phone", "").strip()
        if phone and not PHONE_RE.match(phone):
            raise forms.ValidationError("Введите телефон в формате +996 555 123 456.")
        return phone

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if len(message) < MIN_MESSAGE_LEN:
            raise forms.ValidationError(f"Сообщение слишком короткое — минимум {MIN_MESSAGE_LEN} символов.")
        return message
