from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("admin/materials", views.AdminMaterialViewSet, basename="admin-material")
urlpatterns = [
    path("materials/", views.MaterialListView.as_view()),
    path("materials/files/<int:pk>/link/", views.FileLinkView.as_view()),
    path("materials/files/<int:pk>/view/", views.FileView.as_view()),
    path("", include(router.urls)),
]
