from django.contrib import admin

from .models import RentalRequest


@admin.register(RentalRequest)
class RentalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "full_name", "phone", "start_date", "end_date",
                    "days_display", "estimated_total", "status", "created_at")
    list_display_links = ("id", "product")
    list_filter = ("status", "start_date", "product")
    # Переходы статусов проверяются в RentalRequest.clean() — работает и здесь.
    list_editable = ("status",)
    list_select_related = ("product", "user")
    search_fields = ("full_name", "phone", "email", "organization")
    readonly_fields = ("created_at", "user", "price_per_day", "estimated_total")
    date_hierarchy = "created_at"

    @admin.display(description="Дней")
    def days_display(self, obj):
        return obj.days
