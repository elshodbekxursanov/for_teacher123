from django.urls import path
from . import views, payme, click

urlpatterns = [
    path("plans/", views.PlansView.as_view()),
    path("payments/", views.CreatePaymentView.as_view()),
    path("payments/me/", views.MyPaymentsView.as_view()),
    path("payments/payme/", payme.PaymeView.as_view()),
    path("payments/click/prepare/", click.ClickPrepareView.as_view()),
    path("payments/click/complete/", click.ClickCompleteView.as_view()),
    path("admin/payments/", views.AdminPaymentsView.as_view()),
]
