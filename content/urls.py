from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register("subjects", views.SubjectViewSet, basename="subject")
router.register("problems", views.ProblemViewSet, basename="problem")
router.register("admin/subjects", views.AdminSubjectViewSet, basename="admin-subject")
router.register("admin/topics", views.AdminTopicViewSet, basename="admin-topic")

urlpatterns = [
    path("", include(router.urls)),
    path("topics/<int:pk>/solutions/", views.TopicSolutionsView.as_view()),
]
