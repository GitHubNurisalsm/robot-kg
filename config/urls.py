from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Robot.KG.Baiel — администрирование"
admin.site.site_title = "Robot.KG.Baiel"
admin.site.index_title = "Управление магазином"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("analytics/", include("analytics.urls")),
    path("catalog/", include("catalog.urls")),
    path("cart/", include("cart.urls")),
    path("accounts/", include("accounts.urls")),
    path("rental/", include("rentals.urls")),
    path("contacts/", include("inquiries.urls")),
    path("", include("orders.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
