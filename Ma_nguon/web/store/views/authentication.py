from urllib.parse import unquote, urlsplit

from django.contrib.auth.views import LoginView
from django.urls import reverse

from store.forms.authentication import EmployeeLoginForm
from store.models import Role


class EmployeeLoginView(LoginView):
    template_name = "store/auth/login.html"
    authentication_form = EmployeeLoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        if self.request.user.is_authenticated and self.request.user.role == Role.CUSTOMER:
            return reverse("shop_account")
        destination = super().get_success_url()
        if unquote(urlsplit(destination).path).rstrip("/") == self.request.path.rstrip("/"):
            return reverse("dashboard")
        return destination
