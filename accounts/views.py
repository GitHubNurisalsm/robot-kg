from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, resolve_url
from django.conf import settings
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView

from .forms import LoginForm, SignUpForm


def safe_next(request) -> str | None:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return None


class SignUpView(FormView):
    form_class = SignUpForm
    template_name = "accounts/signup.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            # Savepoint: гонка двух регистраций с одним email/логином
            # ловится уникальными ограничениями БД, а не падает с 500.
            with transaction.atomic():
                user = form.save()
        except IntegrityError:
            form.add_error(None, "Пользователь с таким логином или email уже существует.")
            return self.form_invalid(form)
        # login() меняет ключ сессии (защита от session fixation), корзина сохраняется.
        login(self.request, user)
        messages.success(self.request, f"Добро пожаловать в {settings.SITE_BRAND['name']}!")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return safe_next(self.request) or resolve_url(settings.LOGIN_REDIRECT_URL)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["next"] = safe_next(self.request) or ""
        return ctx


class SiteLoginView(LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True  # проверка next на «свой хост» встроена в LoginView

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Вы вошли в аккаунт.")
        return response


class SiteLogoutView(LogoutView):
    """Выход только по POST (GET-выход позволял бы разлогинить по ссылке)."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "Вы вышли из аккаунта.")
        return response
