"""Inicio de turno por puesto y área de Meseros."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from . import areas, piso, tenancy
from .models import Reserva


@login_required
def staff_inicio(request):
    """Después de entrar: cada quien llega a su área. Si tiene varias, ve botones grandes para elegir."""
    user = request.user
    if user.is_superuser and not tenancy.soporte_empresa_id(user):
        return redirect("reservas:plataforma")
    menu = areas.menu_de(user)
    if not menu:
        return redirect("reservas:home") if not user.is_staff else render(request, "reservas/areas/sin_puesto.html")
    if len(menu) == 1:
        return redirect(menu[0]["url"])
    return render(request, "reservas/areas/inicio.html", {"menu": menu})


def _sucursal(request):
    sucs = tenancy.sucursales_for_user(request.user).order_by("nombre")
    sid = request.GET.get("s") or request.session.get("panel_sucursal")
    suc = (sucs.filter(pk=sid).first() if sid else None) or sucs.first()
    if suc:
        request.session["panel_sucursal"] = suc.pk
    return suc, sucs


@login_required
def meseros(request):
    """Las mesas de la sucursal como tarjetas grandes con colores: libre, por llegar, comiendo, pidió la cuenta."""
    suc, sucs = _sucursal(request)
    if not suc:
        return render(request, "reservas/areas/meseros.html", {"sin_sucursal": True})
    from .models_orders import Order, OrderStatus  # noqa: WPS433

    ahora = timezone.now()
    sentadas = {r.mesa_id: r for r in piso.sentadas(suc, ahora)}
    pronto = {}
    for r in (Reserva.objects.filter(sucursal=suc, llego=False, estado__in=[Reserva.PEND, Reserva.CONF],
                                     local_inicio__gte=ahora - timedelta(minutes=15),
                                     local_inicio__lte=ahora + timedelta(minutes=45))
              .order_by("local_inicio")):
        pronto.setdefault(r.mesa_id, r)
    ordenes = {}
    for o in Order.objects.filter(sucursal=suc).exclude(status=OrderStatus.CLOSED).order_by("-id"):
        ordenes.setdefault(o.mesa_id, o)

    tz = suc.tz()
    mesas = []
    for m in suc.mesas.order_by("numero"):
        r = sentadas.get(m.pk)
        o = ordenes.get(m.pk)
        if r and r.cuenta_pedida_en:
            estado, etiqueta = "cuenta", "Pidió la cuenta"
        elif r:
            estado, etiqueta = "comiendo", "Comiendo"
        elif pronto.get(m.pk):
            estado, etiqueta = "llega", "Por llegar"
        else:
            estado, etiqueta = "libre", "Libre"
        mesas.append({
            "mesa": m, "estado": estado, "etiqueta": etiqueta, "reserva": r,
            "llega": pronto.get(m.pk), "llega_hora": pronto[m.pk].local_inicio.astimezone(tz) if pronto.get(m.pk) else None,
            "orden": o, "orden_estado": o.get_status_display() if o and hasattr(o, "get_status_display") else "",
        })
    cuenta = {k: sum(1 for x in mesas if x["estado"] == k) for k in ("libre", "llega", "comiendo", "cuenta")}
    return render(request, "reservas/areas/meseros.html", {"suc": suc, "sucs": sucs, "mesas": mesas, "cuenta": cuenta})
