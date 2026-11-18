from django.contrib import admin, messages

from .models import Order, OrderItem
from .services import cancel_order


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ("product", "product_name", "unit_price", "quantity", "line_total")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "full_name", "phone", "delivery_method", "total", "status", "created_at")
    list_filter = ("status", "delivery_method", "created_at")
    list_editable = ("status",)
    list_select_related = ("user",)
    search_fields = ("number", "full_name", "phone", "email")
    date_hierarchy = "created_at"
    inlines = (OrderItemInline,)
    actions = ("cancel_selected",)
    # Состав и сумма заказа — документ; менеджер меняет только статус.
    readonly_fields = ("number", "user", "full_name", "phone", "email", "delivery_method",
                       "address", "comment", "total", "created_at", "updated_at")
    fields = ("number", "status", "user", "full_name", "phone", "email", "delivery_method",
              "address", "comment", "total", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False  # заказы создаются только через оформление на сайте

    def has_delete_permission(self, request, obj=None):
        return False  # удаление не вернуло бы товар на склад; используйте отмену

    def save_model(self, request, obj, form, change):
        # Переход в «Отменён» — через сервис: он атомарно вернёт остатки (ровно один раз).
        if change and "status" in form.changed_data and obj.status == Order.Status.CANCELLED:
            if not cancel_order(obj.pk):
                messages.error(request, f"Заказ {obj.number} уже нельзя отменить.")
            return
        super().save_model(request, obj, form, change)

    @admin.action(description="Отменить выбранные заказы (вернуть товар на склад)")
    def cancel_selected(self, request, queryset):
        done = sum(cancel_order(pk) for pk in queryset.values_list("pk", flat=True))
        skipped = queryset.count() - done
        self.message_user(request, f"Отменено: {done}. Пропущено (нельзя отменить): {skipped}.")
