# reservas/mixins.py
"""
Mixins de autorización/visibilidad (multi-empresa).
Toda la lógica vive en reservas.tenancy; estos mixins solo la aplican a las vistas.
Se conservan los nombres anteriores para no romper imports.
"""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.db.models import QuerySet

from .models import Sucursal
from . import tenancy


def _is_chain_owner(user) -> bool:
    """Compat: True = dueño/administrador (de la plataforma o de su empresa)."""
    return tenancy.is_chain_owner(user)


def _user_allowed_countries(user):
    ids = tenancy.allowed_country_ids(user)
    if ids is None:
        from .models import Pais
        return list(Pais.objects.values_list("id", flat=True))
    return ids


class ChainOwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Superusuario o dueño/administrador de una empresa."""
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.is_staff and tenancy.is_chain_owner(u)


class CountryScopeMixin:
    """chain_scope(qs) filtra cualquier queryset al alcance del usuario."""
    def chain_scope(self, qs: QuerySet, country_field: str = "pais_id"):
        return tenancy.scope_queryset(qs, getattr(self.request, "user", None))


class VisibleSucursalQuerysetMixin:
    model = Sucursal

    def get_queryset(self):
        return tenancy.sucursales_for_user(self.request.user, super().get_queryset())


class VisibleBySucursalFKMixin:
    sucursal_field = "sucursal"

    def get_queryset(self):
        return tenancy.scope_by_sucursal(super().get_queryset(), self.request.user, self.sucursal_field)


class VisibleBySucursalViaMesaMixin:
    mesa_field = "mesa"

    def get_queryset(self):
        return tenancy.scope_by_sucursal(super().get_queryset(), self.request.user, f"{self.mesa_field}__sucursal")


class CountryScopedQuerysetMixin:
    """Filtra get_queryset() al alcance del usuario (empresa, país y sucursal)."""
    country_field = "pais"

    def get_allowed_countries(self):
        return _user_allowed_countries(self.request.user)

    def get_queryset(self):
        return tenancy.scope_queryset(super().get_queryset(), self.request.user)


class CountryScopedObjectMixin:
    """Valida en get_object() que el objeto esté dentro del alcance del usuario."""
    country_attr = "pais"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        model = type(obj)
        if not tenancy.scope_queryset(model.objects.filter(pk=obj.pk), self.request.user).exists():
            raise PermissionDenied("No tienes acceso a este recurso.")
        return obj


class AssertUserCanManageSucursalMixin(LoginRequiredMixin):
    url_kwarg_sucursal = "sucursal_id"

    def get_sucursal(self) -> Sucursal:
        qs = tenancy.sucursales_for_user(self.request.user)
        return get_object_or_404(qs, pk=self.kwargs[self.url_kwarg_sucursal])

    def assert_user_can_manage_sucursal(self, sucursal: Sucursal):
        if not tenancy.user_can_manage_sucursal(self.request.user, sucursal):
            raise Http404("Sucursal no encontrada o sin permisos.")


class StaffSucursalesListMixin(VisibleSucursalQuerysetMixin, LoginRequiredMixin):
    pass


# --- Alias retro-compatibles ---
class ChainScopeMixin(CountryScopeMixin):
    pass


class CountryRestrictedQuerysetMixin(VisibleSucursalQuerysetMixin):
    pass


class CountryObjectPermissionMixin(CountryScopedObjectMixin):
    pass
