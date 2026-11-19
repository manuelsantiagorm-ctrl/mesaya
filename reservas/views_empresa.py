# reservas/views_empresa.py
"""Panel del dueño: marca, aviso de privacidad, WhatsApp, equipo y reglas por sucursal."""
from django.utils.translation import gettext as _
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from .models import AccesoSoporte
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import areas, tenancy
from .forms_empresa import EditarPuestoForm, EmpresaConfigForm, NuevoMiembroForm, SucursalReglasForm, asignar_sucursales
from .models import MiembroEmpresa


def _empresa_admin(request):
    empresa = getattr(request, "empresa", None) or tenancy.empresa_de_usuario(request.user)
    if empresa is None or not tenancy.is_empresa_admin(request.user, empresa):
        raise PermissionDenied("Solo el dueño o administrador de la empresa puede entrar aquí.")
    return empresa


@staff_member_required
@require_http_methods(["GET", "POST"])
def empresa_config(request):
    empresa = _empresa_admin(request)
    form = EmpresaConfigForm(request.POST or None, request.FILES or None, instance=empresa)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Configuración guardada."))
        return redirect("reservas:empresa_config")
    return render(request, "reservas/empresa/config.html", {
        "form": form, "empresa": empresa,
        "sucursales": tenancy.sucursales_for_user(request.user).filter(empresa=empresa).order_by("nombre"),
        "accesos_soporte": AccesoSoporte.objects.filter(empresa=empresa).order_by("-inicio")[:20],
    })


@staff_member_required
@require_http_methods(["GET", "POST"])
def empresa_equipo(request):
    empresa = _empresa_admin(request)
    es_owner = bool(tenancy.soporte_empresa_id(request.user) == empresa.pk) or MiembroEmpresa.objects.filter(
        empresa=empresa, user=request.user, rol=MiembroEmpresa.OWNER, activo=True
    ).exists()
    form = NuevoMiembroForm(request.POST if (request.method == "POST" and not request.POST.get("quitar") and not request.POST.get("editar")) else None, empresa=empresa, puede_owner=es_owner)
    if request.method == "POST":
        if request.POST.get("quitar"):
            m = get_object_or_404(MiembroEmpresa, pk=request.POST["quitar"], empresa=empresa)
            if m.user_id == request.user.id:
                messages.error(request, _("No puedes quitarte a ti mismo."))
            elif m.rol in (MiembroEmpresa.OWNER, MiembroEmpresa.ADMIN) and not es_owner:
                messages.error(request, _("Solo el dueño puede quitar a un dueño o gerente general."))
            else:
                for s in empresa.sucursales.all():
                    s.administradores.remove(m.user)
                m.delete()
                messages.success(request, _("Miembro quitado."))
            return redirect("reservas:empresa_equipo")
        if request.POST.get("editar"):
            m = get_object_or_404(MiembroEmpresa, pk=request.POST["editar"], empresa=empresa)
            ef = EditarPuestoForm(request.POST, prefix=f"m{m.pk}", empresa=empresa, puede_owner=es_owner)
            if m.user_id == request.user.id:
                messages.error(request, _("No puedes cambiar tu propio puesto."))
            elif m.rol in (MiembroEmpresa.OWNER, MiembroEmpresa.ADMIN) and not es_owner:
                messages.error(request, _("Solo el dueño puede cambiar a un dueño o gerente general."))
            elif ef.is_valid():
                m.rol = ef.cleaned_data["rol"]
                m.save(update_fields=["rol"])
                asignar_sucursales(empresa, m.user, m.rol, ef.cleaned_data["sucursales"])
                messages.success(request, _("Listo: %(n)s ahora es %(p)s.") % {
                    "n": m.user.get_full_name() or m.user.email, "p": m.get_rol_display()})
            else:
                messages.error(request, " ".join(str(e) for errs in ef.errors.values() for e in errs))
            return redirect("reservas:empresa_equipo")
        if form.is_valid():
            m = form.save()
            messages.success(request, _("%(v0)s agregado como %(v1)s.") % {"v0": m.user.email, "v1": m.get_rol_display()})
            return redirect("reservas:empresa_equipo")

    miembros = list(empresa.miembros.select_related("user").order_by("rol", "user__first_name", "user__email"))
    orden_rol = [r for r, _x in MiembroEmpresa.ROLES]
    miembros.sort(key=lambda m: (orden_rol.index(m.rol) if m.rol in orden_rol else 99, (m.user.get_full_name() or m.user.email).lower()))
    for m in miembros:
        m.puesto = areas.PUESTOS.get(m.rol, {})
        m.suc_ids = set(m.user.sucursales_que_administra.filter(empresa=empresa).values_list("pk", flat=True))
        m.suc_nombres = [s.nombre for s in empresa.sucursales.all() if s.pk in m.suc_ids]
        m.editable = m.user_id != request.user.id and (es_owner or m.rol not in (MiembroEmpresa.OWNER, MiembroEmpresa.ADMIN))
    roles = [{"valor": v, "nombre": n, **areas.PUESTOS.get(v, {})} for v, n in form.fields["rol"].choices]
    return render(request, "reservas/empresa/equipo.html", {
        "empresa": empresa, "form": form, "miembros": miembros, "roles": roles,
        "sucursales": empresa.sucursales.order_by("nombre"),
        "rol_elegido": form.data.get("rol") if form.is_bound else form.fields["rol"].initial,
        "suc_elegidas": [int(x) for x in form.data.getlist("sucursales")] if form.is_bound else list(form.initial.get("sucursales", [])),
        "por_sucursal": MiembroEmpresa.ROLES_POR_SUCURSAL,
    })


@staff_member_required
@require_http_methods(["GET", "POST"])
def sucursal_reglas(request, sucursal_id):
    suc = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)
    form = SucursalReglasForm(request.POST or None, instance=suc)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Reglas de la sucursal guardadas."))
        return redirect("reservas:sucursal_reglas", sucursal_id=suc.pk)
    return render(request, "reservas/empresa/sucursal_reglas.html", {"form": form, "sucursal": suc})


@staff_member_required
def sucursal_widget(request, sucursal_id):
    suc = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)
    url = request.build_absolute_uri(reverse("reservas:reservar_publico", args=[suc.slug]))
    return render(request, "reservas/empresa/widget.html", {
        "sucursal": suc,
        "url": url,
        "url_embed": url + "?embed=1",
    })
