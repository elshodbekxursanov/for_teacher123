from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("tests", views.TestViewSet, basename="test")
router.register("attempts", views.AttemptViewSet, basename="attempt")
urlpatterns = [path("", include(router.urls))]
