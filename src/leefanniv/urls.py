"""URL routes."""

from django.contrib import admin
from django.urls import path

from leefanniv import views

urlpatterns = [
    path("", views.home, name="home"),
    path("tournaments/", views.tournaments, name="tournaments"),
    path("t/<int:pk>/", views.tournament, name="tournament"),
    path("games/", views.games, name="games"),
    path("admin/", admin.site.urls),
]
