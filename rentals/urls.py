from django.urls import path

from . import views

app_name = "rentals"

urlpatterns = [
    path("", views.rental, name="rental"),
]
