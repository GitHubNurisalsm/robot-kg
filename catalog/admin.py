from django.contrib import admin

from .models import Category, Product, ProductSpecification


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


class ProductSpecificationInline(admin.TabularInline):
    model = ProductSpecification
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "price",
        "stock",
        "is_available",
        "is_featured",
        "is_rentable",
    )
    list_filter = ("category", "is_available", "is_featured", "is_rentable")
    list_editable = ("price", "stock", "is_available", "is_featured")
    list_select_related = ("category",)
    search_fields = ("name", "short_description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = (ProductSpecificationInline,)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("category", "name", "slug", "short_description", "description")}),
        ("Цена и наличие", {"fields": ("price", "old_price", "stock", "is_available", "is_featured")}),
        ("Аренда", {"fields": ("is_rentable", "rental_price_per_day")}),
        ("Изображение", {"fields": ("image", "illustration")}),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )
