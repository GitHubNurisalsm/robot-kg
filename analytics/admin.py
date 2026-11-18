from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """Только чтение: сырые события — неизменяемый журнал."""

    list_display = ("created_at", "event_type", "product", "query", "results_count", "value")
    list_filter = ("event_type",)
    list_select_related = ("product",)
    search_fields = ("query", "product__name")
    date_hierarchy = "created_at"
    list_per_page = 100

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
