"""Limpia el admin de Django: el operador no ve datos de los restaurantes ni de sus comensales.
Se importa al inicio de urls.py, ANTES de construir admin.site.urls."""
from django.contrib import admin


# Tokens de inicio de sesión de los usuarios: nunca visibles en el admin (se registran después de nuestras apps)
try:
    from allauth.socialaccount.models import SocialAccount, SocialToken
    for _m in (SocialAccount, SocialToken):
        if admin.site.is_registered(_m):
            admin.site.unregister(_m)
except Exception:
    pass


# Comensales: sus cuentas pertenecen a los restaurantes, no al operador. En el admin solo se ven usuarios del personal.
try:
    from allauth.account.models import EmailAddress
    if admin.site.is_registered(EmailAddress):
        admin.site.unregister(EmailAddress)
except Exception:
    pass

from django.contrib.auth import get_user_model as _gum  # noqa: E402
from django.contrib.auth.admin import UserAdmin as _UserAdmin  # noqa: E402

_U = _gum()
if admin.site.is_registered(_U):
    _base = type(admin.site._registry[_U])
    admin.site.unregister(_U)

    class UsuarioPersonalAdmin(_base if issubclass(_base, _UserAdmin) else _UserAdmin):
        def get_queryset(self, request):
            return super().get_queryset(request).filter(is_staff=True)

    admin.site.register(_U, UsuarioPersonalAdmin)


# El admin de Django es solo del operador de la plataforma (los restaurantes usan su panel).
admin.site.has_permission = lambda request: bool(request.user.is_active and request.user.is_superuser)
