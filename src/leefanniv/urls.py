"""URL routes."""

from django.contrib import admin
from django.urls import path

from leefanniv import views

urlpatterns = [
    path("", views.home, name="home"),
    path("tournaments/", views.tournaments, name="tournaments"),
    path("t/<int:pk>/", views.tournament, name="tournament"),
    path("t/<int:pk>/equipes/", views.tournament, {"tab": "teams"}, name="teams"),
    path("t/<int:pk>/charte/", views.tournament, {"tab": "charter"}, name="charter"),
    path("admin/", admin.site.urls),
]
