# reservas/views_legado.py
"""
Rutas de la versión anterior que se reemplazaron por pantallas nuevas.
Se conservan sus URLs (y nombres) para que ningún enlace viejo se rompa: solo redirigen.
"""
from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from .models import Mesa, Sucursal


def _con_params(url, request, mapa):
    params = {nuevo: request.GET.get(viejo) for viejo, nuevo in mapa.items() if request.GET.get(viejo)}
    return f"{url}?{urlencode(params)}" if params else url


def a_reservar_publico_slug(request, slug):
    return redirect(_con_params(reverse("reservas:reservar_publico", args=[slug]), request,
                                {"date": "fecha", "time": "hora", "party": "party"}))


def a_reservar_publico_sucursal(request, sucursal_id):
    s = get_object_or_404(Sucursal, pk=sucursal_id)
    return redirect(_con_params(reverse("reservas:reservar_publico", args=[s.slug]), request,
                                {"date": "fecha", "fecha": "fecha", "time": "hora", "hora": "hora", "party": "party"}))


def a_reservar_publico_mesa(request, mesa_id):
    m = get_object_or_404(Mesa.objects.select_related("sucursal"), pk=mesa_id)
    return redirect("reservas:reservar_publico", slug=m.sucursal.slug)


def a_buscar(request, *a, **kw):
    return redirect(_con_params(reverse("reservas:seleccionar_sucursal"), request,
                                {"q": "q", "date": "date", "time": "time", "party": "party"}))


def a_mis_reservas(request, *a, **kw):
    return redirect("reservas:mis_reservas")


def a_registro(request, *a, **kw):
    return redirect("accounts:signup_start")


def a_hoy(request, *a, **kw):
    return redirect("reservas:panel_hoy")


def a_sucursales_staff(request, *a, **kw):
    return redirect("reservas:admin_sucursales")


def a_mapa(request, sucursal_id, *a, **kw):
    return redirect("reservas:admin_mapa_sucursal", sucursal_id=sucursal_id)


def a_resumen(request, *a, **kw):
    return redirect("reservas:resumen_negocio")


def a_equipo(request, *a, **kw):
    return redirect("reservas:empresa_equipo")


def a_plataforma(request, *a, **kw):
    return redirect("reservas:plataforma")


def a_sucursal_nueva(request, *a, **kw):
    return redirect("reservas:chainadmin_sucursal_nueva")


def a_sucursal_editar(request, pk, *a, **kw):
    return redirect("reservas:chainadmin_sucursal_editar", pk=pk)
