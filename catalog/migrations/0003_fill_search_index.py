"""Заполняет search_index для уже существующих товаров.

Логика продублирована намеренно: в миграциях нельзя импортировать
методы модели — они могут измениться позже, а миграция должна остаться прежней.
"""

from django.db import migrations

BATCH = 500


def fill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    batch = []
    for p in Product.objects.only("id", "name", "short_description", "description").iterator(chunk_size=BATCH):
        p.search_index = " ".join([p.name, p.short_description, p.description]).lower()
        batch.append(p)
        if len(batch) >= BATCH:
            Product.objects.bulk_update(batch, ["search_index"])
            batch = []
    if batch:
        Product.objects.bulk_update(batch, ["search_index"])


class Migration(migrations.Migration):
    dependencies = [("catalog", "0002_product_search_index")]
    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
