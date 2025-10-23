from django.urls import path
from . import views

urlpatterns = [
    path("", views.root, name="root"),
    path("login", views.login_view, name="login"),
    path("register", views.register_view, name="register"),
    path("home", views.home, name="home"),
]
