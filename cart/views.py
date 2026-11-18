from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from analytics.models import Event
from analytics.services import track
from catalog.models import Product

from .cart import MAX_LINES, Cart, CartLimitError, OutOfStockError
from .forms import CartQuantityForm, CartUpdateForm


def _redirect_back(request):
    """Возврат на страницу, откуда пришли — только в пределах нашего сайта."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(target)
    return redirect("cart:detail")


def _first_error(form) -> str:
    for errors in form.errors.values():
        return errors[0]
    return "Некорректные данные."


def cart_detail(request):
    cart = Cart(request)
    lines = cart.lines()
    if cart.removed_names:
        messages.warning(
            request, "Больше не продаются и удалены из корзины: " + ", ".join(cart.removed_names) + "."
        )
    if cart.adjusted_names:
        messages.info(
            request, "Количество уменьшено до остатка на складе: " + ", ".join(cart.adjusted_names) + "."
        )
    return render(request, "cart/detail.html", {"cart": cart, "lines": lines})


@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(Product.objects.available(), pk=product_id)
    data = request.POST.copy()
    data.setdefault("quantity", "1")  # быстрая кнопка в карточке может не передать количество
    form = CartQuantityForm(data)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return _redirect_back(request)

    requested = form.cleaned_data["quantity"]
    cart = Cart(request)
    try:
        added = cart.add(product, requested)
    except OutOfStockError:
        messages.error(request, f"«{product.name}» нет на складе.")
        return _redirect_back(request)
    except CartLimitError:
        messages.error(request, f"В корзине может быть не больше {MAX_LINES} разных товаров.")
        return _redirect_back(request)

    if added > 0:
        track(request, Event.Type.ADD_TO_CART, product=product, category=product.category,
              quantity=added, value=product.price * added)
    if added == requested:
        messages.success(request, f"«{product.name}» добавлен в корзину.")
    elif added > 0:
        messages.warning(
            request, f"Добавлено {added} шт. «{product.name}» — больше нет на складе."
        )
    else:
        messages.warning(
            request, f"В корзине уже максимально доступное количество «{product.name}»."
        )
    return _redirect_back(request)


@require_POST
def cart_update(request, product_id):
    cart = Cart(request)
    form = CartUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect("cart:detail")

    product = Product.objects.available().filter(pk=product_id).first()
    if product is None:
        cart.remove(product_id)
        messages.warning(request, "Товар больше не продаётся и удалён из корзины.")
        return redirect("cart:detail")

    before = cart.quantity_of(product.pk)
    if before == 0:
        # Обновлять можно только то, что уже лежит в корзине.
        messages.error(request, "Этого товара нет в корзине.")
        return redirect("cart:detail")

    requested = form.cleaned_data["quantity"]
    after = cart.set(product, requested)
    delta = after - before
    if delta > 0:
        track(request, Event.Type.ADD_TO_CART, product=product, category=product.category,
              quantity=delta, value=product.price * delta)
    elif delta < 0:
        track(request, Event.Type.REMOVE_FROM_CART, product=product, category=product.category,
              quantity=-delta, value=product.price * -delta)

    if after == 0:
        messages.success(request, f"«{product.name}» удалён из корзины.")
    elif after < requested:
        messages.warning(request, f"Доступно только {after} шт. «{product.name}».")
    return redirect("cart:detail")


@require_POST
def cart_remove(request, product_id):
    cart = Cart(request)
    removed = cart.remove(product_id)
    if removed:
        product = Product.objects.filter(pk=product_id).select_related("category").first()
        track(request, Event.Type.REMOVE_FROM_CART, product=product,
              category=product.category if product else None, quantity=removed,
              value=product.price * removed if product else None)
        messages.success(request, "Товар удалён из корзины.")
    return redirect(reverse("cart:detail"))


@require_POST
def cart_clear(request):
    Cart(request).clear()
    messages.success(request, "Корзина очищена.")
    return redirect("cart:detail")
