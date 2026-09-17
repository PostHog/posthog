from django.urls import path

from shop import views

urlpatterns = [
    path("orders/<int:pk>/summary/", views.order_summary, name="order-summary"),
]
