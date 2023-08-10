from django.views import generic
from django.shortcuts import redirect
from .forms import RegisterForm, LoginForm
from django.contrib.auth import login
from django.urls import reverse_lazy
# Create your views here.

class UserRegistrationView(generic.CreateView):
    form_class = RegisterForm
    template_name = 'registration/register.html'
    success_url = reverse_lazy("login")

    def get(self, request, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/")
        return super().get(request, *args, **kwargs)


class UserLoginView(generic.FormView):
    form_class = LoginForm
    template_name = 'authentication/login.html'
    success_url = reverse_lazy('home')

    def get(self, request, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/")
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        login(self.request, form.get_user())
        return super().form_valid(form)