import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from cart.cart import Cart

from .forms import CheckoutForm
from .models import Order
from .services import CartChanged, EmptyCart, InsufficientStock, PriceChanged, place_order

TOKEN_SESSION_KEY = "checkout_token"
ORDERS_PAGE_SIZE = 10


def _new_token(request) -> uuid.UUID:
    token = uuid.uuid4()
    request.session[TOKEN_SESSION_KEY] = str(token)
    return token


def _render_checkout(request, form, cart, lines, status=200):
    return render(request, "orders/checkout.html",
                  {"form": form, "cart": cart, "lines": lines}, status=status)


def _already_placed(request):
    """Повтор формы, по которой заказ уже создан (двойной клик/F5) — к заказу, а не в пустую корзину."""
    try:
        token = uuid.UUID(request.POST.get("checkout_token", ""))
    except ValueError:
        return None
    return Order.objects.filter(checkout_token=token, user=request.user).first()


@login_required
def checkout(request):
    if request.method == "POST":
        existing = _already_placed(request)
        if existing:
            return redirect("orders:detail", number=existing.number)

    cart = Cart(request)
    lines = cart.lines()
    if cart.removed_names or cart.adjusted_names:
        messages.warning(request, "Состав корзины изменился — проверьте её перед оформлением.")
        return redirect("cart:detail")
    if not lines:
        messages.info(request, "Корзина пуста — добавьте товары перед оформлением.")
        return redirect("cart:detail")

    if request.method == "POST":
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                result = place_order(request, form)
            except PriceChanged as exc:
                messages.warning(request, "Цены изменились — проверьте новый итог и подтвердите заказ ещё раз.")
                data = request.POST.copy()
                data["expected_total"] = str(exc.new_total)
                form = CheckoutForm(initial=data.dict())
                return _render_checkout(request, form, cart, lines, status=409)
            except InsufficientStock as exc:
                messages.error(request, f"«{exc.product_name}» уже раскупили в нужном количестве. Корзина обновлена.")
                return redirect("cart:detail")
            except (CartChanged, EmptyCart):
                messages.warning(request, "Состав корзины изменился — проверьте её перед оформлением.")
                return redirect("cart:detail")
            request.session.pop(TOKEN_SESSION_KEY, None)
            if result.created:
                messages.success(request, f"Заказ {result.order.number} оформлен! Менеджер свяжется с вами для подтверждения.")
            return redirect("orders:detail", number=result.order.number)
        messages.error(request, "Проверьте поля формы.")
        return _render_checkout(request, form, cart, lines)

    user = request.user
    form = CheckoutForm(initial={
        "full_name": user.get_full_name() or user.username,
        "email": user.email,
        "phone": getattr(user, "phone", ""),
        "checkout_token": _new_token(request),
        "expected_total": cart.total,
    })
    return _render_checkout(request, form, cart, lines)


@login_required
def order_detail(request, number):
    qs = Order.objects.prefetch_related("items__product")
    # Object-level доступ: только свой заказ (сотрудник — любой). Чужой — 404, не 403.
    if not request.user.is_staff:
        qs = qs.filter(user=request.user)
    order = get_object_or_404(qs, number=number)
    return render(request, "orders/detail.html", {"order": order})


@login_required
def order_list(request):
    orders = (Order.objects.filter(user=request.user)
              .annotate(items_count=Sum("items__quantity"))
              .order_by("-created_at"))
    page_obj = Paginator(orders, ORDERS_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "orders/list.html", {"page_obj": page_obj, "orders": page_obj.object_list})
