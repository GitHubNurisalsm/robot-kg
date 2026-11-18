from django.contrib import admin

from .models import ContactMessage


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "phone", "is_processed", "created_at")
    list_filter = ("is_processed", "subject")
    list_editable = ("is_processed",)
    search_fields = ("name", "email", "subject", "message")
    # Текст обращения — исходный документ клиента, редактировать его нельзя.
    readonly_fields = ("user", "name", "email", "phone", "subject", "message", "created_at")
    date_hierarchy = "created_at"
    actions = ("mark_processed",)

    def has_add_permission(self, request):
        return False  # обращения приходят только с сайта

    @admin.action(description="Отметить обработанными")
    def mark_processed(self, request, queryset):
        updated = queryset.filter(is_processed=False).update(is_processed=True)
        self.message_user(request, f"Отмечено обработанными: {updated}.")
