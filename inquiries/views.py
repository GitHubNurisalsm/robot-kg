from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import ContactForm
from .services import RateLimited, submit_contact


def _initial(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    return {"name": user.get_full_name() or user.username, "email": user.email,
            "phone": getattr(user, "phone", "")}


def contact(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            try:
                submit_contact(request, form)
            except RateLimited:
                messages.error(request, "Слишком много обращений. Попробуйте через час или позвоните нам.")
                return render(request, "inquiries/contact.html", {"form": form}, status=429)
            messages.success(request, "Спасибо! Сообщение отправлено — мы ответим в течение рабочего дня.")
            return redirect(reverse("inquiries:contact") + "#contact-form")  # PRG
        messages.error(request, "Проверьте поля формы.")
    else:
        form = ContactForm(initial=_initial(request))
    return render(request, "inquiries/contact.html", {"form": form})
