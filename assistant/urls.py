from django.urls import path
from . import views

urlpatterns = [
    path("ai/solve/", views.SolveView.as_view()),
    path("ai/quota/", views.QuotaView.as_view()),
    path("ai/requests/<int:pk>/approve/", views.ApproveView.as_view()),
]
