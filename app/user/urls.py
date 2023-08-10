from .views import UserRegistrationView, UserLoginView
from django.urls import path

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="register"),
    path("login/", UserLoginView.as_view(), name="login"),
]
