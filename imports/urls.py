from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("imports", views.ImportViewSet, basename="import")
urlpatterns = [path("", include(router.urls))]
