from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("export/events.csv", views.export_events, name="export_events"),
    path("export/order-items.csv", views.export_order_items, name="export_order_items"),
]
