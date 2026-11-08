from django.urls import path
from . import views

urlpatterns = [
    path("stats/me/", views.MyStats.as_view()),
    path("stats/teacher/", views.TeacherStats.as_view()),
    path("stats/activity/", views.MyActivity.as_view()),
    path("admin/activity/", views.AdminActivity.as_view()),
    path("admin/stats/", views.AdminStats.as_view()),
]
