from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from catalog.models import Product

from .forms import RentalRequestForm
from .services import create_rental_request


def _initial(request):
    initial = {}
    slug = request.GET.get("product")
    if slug and Product.objects.rentable().filter(slug=slug).exists():
        initial["product"] = slug
    user = request.user
    if user.is_authenticated:
        initial.update({
            "full_name": user.get_full_name() or user.username,
            "email": user.email,
            "phone": getattr(user, "phone", ""),
        })
    return initial


def rental(request):
    if request.method == "POST":
        form = RentalRequestForm(request.POST)
        if form.is_valid():
            result = create_rental_request(request, form)
            r = result.rental
            total = f"{r.estimated_total:,.0f}".replace(",", " ")
            messages.success(
                request,
                f"Заявка №{r.pk} принята: «{r.product.name}», {r.days} дн., "
                f"предварительно {total} сом. Менеджер свяжется с вами.",
            )
            # PRG: после POST — redirect, чтобы F5 не отправлял форму повторно.
            return redirect(reverse("rentals:rental") + "#rental-form")
        messages.error(request, "Проверьте поля формы.")
    else:
        form = RentalRequestForm(initial=_initial(request))

    products = list(
        Product.objects.rentable().select_related("category").order_by("rental_price_per_day")
    )
    prices = {p.slug: float(p.rental_price_per_day) for p in products}
    return render(request, "rentals/rental.html",
                  {"form": form, "products": products, "rental_prices": prices})
