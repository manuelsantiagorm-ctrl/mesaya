# reservas/views_chainadmin.py
from collections import defaultdict, OrderedDict

from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import Sucursal
from .forms_sucursales import SucursalForm
from .mixins import ChainOwnerRequiredMixin, CountryScopedQuerysetMixin, CountryScopedObjectMixin
from .utils_auth import user_allowed_countries
from . import tenancy


# ---------------------------------------------------------------
# Helpers locales
# ---------------------------------------------------------------

def _allowed_country_ids(user):
    """
    Normaliza user_allowed_countries(user) a un set de IDs de país.
    Puede venir como QuerySet de Pais, lista de Pais, o lista de IDs.
    """
    paises = user_allowed_countries(user)
    try:
        return set(paises.values_list("id", flat=True))
    except Exception:
        # lista de objetos o ids
        ids = []
        for p in paises or []:
            ids.append(getattr(p, "id", p))
        return set(ids)


# ===============================================================
# LISTAR SUCURSALES
# ===============================================================



# ===============================================================
# CREAR SUCURSAL
# ===============================================================

class ChainAdminSucursalCreateView(ChainOwnerRequiredMixin, CreateView):
    template_name = "reservas/chainadmin/sucursal_form.html"
    model = Sucursal
    form_class = SucursalForm
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # el form puede usar request para limitar choices de País
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        empresa = getattr(self.request, "empresa", None) or tenancy.empresa_de_usuario(user)
        if empresa is None or not tenancy.is_empresa_admin(user, empresa):
            form.add_error(None, _("Tu usuario no pertenece a una empresa con permiso para crear sucursales."))
            return self.form_invalid(form)
        form.instance.empresa = empresa
        if empresa.sucursales.filter(nombre__iexact=form.cleaned_data.get("nombre", "")).exists():
            form.add_error("nombre", _("Ya tienes una sucursal con ese nombre."))
            return self.form_invalid(form)
        messages.success(self.request, _("Sucursal creada correctamente."))
        return super().form_valid(form)


# ===============================================================
# EDITAR SUCURSAL
# ===============================================================

class ChainAdminSucursalUpdateView(ChainOwnerRequiredMixin, CountryScopedObjectMixin, UpdateView):
    template_name = "reservas/chainadmin/sucursal_form.html"
    model = Sucursal
    form_class = SucursalForm
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("Sucursal actualizada correctamente."))
        return super().form_valid(form)


# ===============================================================
# ELIMINAR SUCURSAL
# ===============================================================

class ChainAdminSucursalDeleteView(ChainOwnerRequiredMixin, CountryScopedObjectMixin, DeleteView):
    template_name = "reservas/chainadmin/sucursal_confirm_delete.html"
    model = Sucursal
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def form_valid(self, form):
        from django.db.models.deletion import ProtectedError
        try:
            resp = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, _("No se puede eliminar: tiene reservas u órdenes. Desactívala en su lugar."))
            from django.shortcuts import redirect
            return redirect(self.success_url)
        messages.success(self.request, _("Sucursal eliminada."))
        return resp
