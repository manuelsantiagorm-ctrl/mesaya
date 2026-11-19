# reservas/views_panel.py
"""
Panel operativo:
- panel_hoy: la recepción del día (KPIs, línea de tiempo, acciones rápidas, lista de espera).
- resumen_negocio: el resumen del dueño con gráficas de los últimos 30 días.
"""
from django.utils.translation import gettext as _
from collections import Counter, defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import aprendizaje, areas, booking, piso, tenancy
from .models import ConversacionIA, ListaEspera, Reserva


def _sucursal_actual(request):
    sucs = tenancy.sucursales_for_user(request.user).order_by("nombre")
    sid = request.GET.get("s") or request.POST.get("s") or request.session.get("panel_sucursal")
    suc = sucs.filter(pk=sid).first() if sid else None
    suc = suc or sucs.first()
    if suc:
        request.session["panel_sucursal"] = suc.pk
    return suc, sucs


@staff_member_required
def panel_hoy(request):
    suc, sucs = _sucursal_actual(request)
    if not suc:
        return render(request, "reservas/panel/hoy.html", {"sin_sucursal": True})
    tz = suc.tz()
    ahora = timezone.now().astimezone(tz)
    dia = ahora.date()

    reservas = list(
        Reserva.objects.filter(sucursal=suc, local_service_date=dia)
        .select_related("cliente", "mesa").order_by("local_inicio", "fecha")
    )
    activas = [r for r in reservas if r.estado in (Reserva.PEND, Reserva.CONF)]
    llegaron = [r for r in activas if r.llego]
    por_llegar = [r for r in activas if not r.llego]
    retrasadas = [r for r in por_llegar if r.local_inicio and r.local_inicio.astimezone(tz) < ahora - timedelta(minutes=suc.regla("tolerancia_min"))]
    proxima = next((r for r in por_llegar if r.local_inicio and r.local_inicio.astimezone(tz) >= ahora - timedelta(minutes=15)), None)

    # Línea de tiempo por hora (personas esperadas)
    personas_hora = Counter()
    for r in activas:
        if r.local_inicio:
            personas_hora[r.local_inicio.astimezone(tz).hour] += r.num_personas
    horas = [h.hour for h in booking.horarios_del_dia(suc, dia)]
    rango = sorted(set(horas)) or list(range(12, 23))
    pico = max(personas_hora.values() or [1])
    timeline = [{"h": h, "n": personas_hora.get(h, 0), "pct": int(100 * personas_hora.get(h, 0) / pico) if pico else 0,
                 "now": h == ahora.hour} for h in rango]

    mesas = list(suc.mesas.all())
    ocupadas = {r.mesa_id for r in llegaron}
    espera = ListaEspera.objects.filter(sucursal=suc, estado__in=[ListaEspera.ESPERANDO, ListaEspera.AVISADO])
    for r in reservas:
        r.hora_local = r.local_inicio.astimezone(tz) if r.local_inicio else None
        r.retrasada = r in retrasadas
        r.riesgo = aprendizaje.riesgo_no_show(r) if (r.estado in (Reserva.PEND, Reserva.CONF) and not r.llego) else None
    en_mesa = sorted(piso.sentadas(suc), key=lambda x: x.salida_est)
    alertas_piso = piso.alertas(suc)
    perfil = aprendizaje.perfil_de(suc)

    ctx = {
        "suc": suc, "sucs": sucs, "dia": dia, "ahora": ahora,
        "reservas": reservas,
        "kpi": {
            "reservas": len(activas),
            "personas": sum(r.num_personas for r in activas),
            "llegaron": len(llegaron),
            "por_llegar": len(por_llegar),
            "retrasadas": len(retrasadas),
            "mesas_libres": max(0, len(mesas) - len(ocupadas)),
            "mesas": len(mesas),
            "espera": espera.count(),
            "ia": sum(1 for r in activas if r.origen == "ia"),
        },
        "proxima": proxima,
        "en_mesa": en_mesa,
        "alertas_piso": alertas_piso,
        "perfil": perfil,
        "timeline": timeline,
        "espera": espera,
        "slots_libres": [d.astimezone(tz).strftime("%H:%M") for d in booking.slots_disponibles(suc, dia, 2, limit=8)],
    }
    return render(request, "reservas/panel/hoy.html", ctx)


def _reserva_staff(request, pk):
    r = get_object_or_404(Reserva.objects.select_related("sucursal"), pk=pk)
    if not tenancy.user_can_manage_sucursal(request.user, r.sucursal):
        raise PermissionDenied
    return r


@staff_member_required
@require_POST
def panel_reserva_accion(request, pk, accion):
    r = _reserva_staff(request, pk)
    ahora = timezone.now()
    volver = "reservas:meseros" if request.POST.get("next") == "meseros" else "reservas:panel_hoy"
    if not areas.puede(request.user, areas.RECEPCION):
        # el mesero solo avisa "pidió la cuenta" y "ya se fueron"
        if accion not in ("cuenta", "liberar") or not areas.puede(request.user, areas.MESEROS):
            raise PermissionDenied
        volver = "reservas:meseros"
    if accion == "llego":
        r.llego, r.arrived_at, r.checkin_at = True, ahora, r.checkin_at or ahora
        if r.estado == Reserva.PEND:
            r.estado = Reserva.CONF
        r.save()
        messages.success(request, _("%(v0)s ya está en su mesa %(v1)s. ¡Buen servicio!") % {"v0": r.nombre_contacto or r.cliente, "v1": r.mesa.numero})
    elif accion == "cuenta":
        r.cuenta_pedida_en = ahora
        r.save(update_fields=["cuenta_pedida_en", "modificado"])
        messages.success(request, _("Mesa %(v0)s: pidió la cuenta. La IA la contará libre en ~%(v1)s min.") % {"v0": r.mesa.numero, "v1": piso.MIN_CUENTA})
    elif accion == "liberar":
        r.liberada_en = ahora
        if not r.llego:
            r.llego, r.arrived_at = True, r.arrived_at or ahora
        r.save()
        messages.success(request, _("Mesa %(v0)s liberada y disponible.") % {"v0": r.mesa.numero})
    elif accion == "reacomodar":
        alt = piso.buscar_mesa_alternativa(r)
        if alt:
            piso.reacomodar(r, alt, "Reacomodo desde recepción")
            messages.success(request, _("%(v0)s pasó a la mesa %(v1)s.") % {"v0": r.nombre_contacto or r.cliente, "v1": alt.numero})
        else:
            messages.error(request, _("No hay otra mesa libre para ese horario. Avisa al cliente o usa la lista de espera."))
    elif accion == "confirmar":
        r.estado = Reserva.CONF
        r.save()
        messages.success(request, _("Reserva confirmada."))
    elif accion == "noshow":
        r.estado = Reserva.NOSH
        r.liberada_en = ahora
        r.save()
        messages.info(request, _("Marcada como no-show. La mesa quedó libre."))
    elif accion == "cancelar":
        booking.cancelar_reserva(r, por_cliente=False)
        messages.info(request, _("Reserva cancelada; avisamos al cliente."))
    else:
        messages.error(request, _("Acción no válida."))
    return redirect(volver)


@staff_member_required
@require_POST
def espera_agregar(request):
    suc, _nuevo = _sucursal_actual(request)
    if not suc:
        raise PermissionDenied
    nombre = (request.POST.get("nombre") or "").strip()[:120]
    if not nombre:
        messages.error(request, _("Escribe el nombre del cliente."))
        return redirect("reservas:panel_hoy")
    try:
        personas = max(1, min(int(request.POST.get("personas") or 2), 30))
        espera_min = max(0, min(int(request.POST.get("espera") or 15), 240))
    except ValueError:
        personas, espera_min = 2, 15
    ListaEspera.objects.create(
        sucursal=suc, nombre=nombre, personas=personas, espera_estimada_min=espera_min,
        telefono=(request.POST.get("telefono") or "").strip()[:30],
        notas=(request.POST.get("notas") or "").strip()[:200],
    )
    messages.success(request, _("%(v0)s agregado a la lista de espera.") % {"v0": nombre})
    return redirect("reservas:panel_hoy")


@staff_member_required
@require_POST
def espera_accion(request, pk, accion):
    e = get_object_or_404(ListaEspera.objects.select_related("sucursal__empresa"), pk=pk)
    if not tenancy.user_can_manage_sucursal(request.user, e.sucursal):
        raise PermissionDenied
    if accion == "avisar":
        enviado = False
        if e.telefono:
            from . import notificaciones
            empresa = e.sucursal.empresa
            nombre_neg = getattr(empresa, "nombre", "") or e.sucursal.nombre
            texto = f"¡Hola {e.nombre}! Tu mesa en {nombre_neg} ({e.sucursal.nombre}) está lista. Te esperamos en recepción."
            try:
                enviado = notificaciones.enviar_texto_whatsapp(
                    notificaciones.normalizar_telefono(e.telefono), texto,
                    phone_number_id=getattr(empresa, "whatsapp_phone_number_id", None) or None,
                )
            except Exception:
                enviado = False
        e.estado, e.avisado_en = ListaEspera.AVISADO, timezone.now()
        e.save()
        messages.success(request, _("Avisamos a %(v0)s%(v1)s.") % {"v0": e.nombre, "v1": ' por WhatsApp' if enviado else ''})
    elif accion == "sentar":
        e.estado, e.sentado_en = ListaEspera.SENTADO, timezone.now()
        e.save()
        messages.success(request, _("%(v0)s ya tiene mesa.") % {"v0": e.nombre})
    elif accion == "quitar":
        e.estado = ListaEspera.SE_FUE
        e.save()
        messages.info(request, _("%(v0)s salió de la lista.") % {"v0": e.nombre})
    return redirect("reservas:panel_hoy")


@staff_member_required
def resumen_negocio(request):
    if not tenancy.is_chain_owner(request.user):
        raise PermissionDenied("Solo el dueño o administrador puede ver el resumen.")
    try:
        dias = max(7, min(int(request.GET.get("dias") or 30), 90))
    except ValueError:
        dias = 30
    sucs = tenancy.sucursales_for_user(request.user)
    hoy = timezone.localdate()
    desde = hoy - timedelta(days=dias - 1)
    qs = Reserva.objects.filter(sucursal__in=sucs, local_service_date__gte=desde, local_service_date__lte=hoy)
    previo = Reserva.objects.filter(sucursal__in=sucs, local_service_date__gte=desde - timedelta(days=dias),
                                    local_service_date__lt=desde)

    total = qs.count()
    validas = qs.exclude(estado=Reserva.CANC)
    personas = validas.aggregate(n=Sum("num_personas"))["n"] or 0
    noshow = qs.filter(estado=Reserva.NOSH).count()
    canc = qs.filter(estado=Reserva.CANC).count()
    total_prev = previo.count()
    crecimiento = round(100 * (total - total_prev) / total_prev) if total_prev else None

    serie = defaultdict(int)
    for d, n in validas.values_list("local_service_date").annotate(n=Count("id")):
        serie[d] = n
    labels = [(desde + timedelta(days=i)) for i in range(dias)]

    horas = Counter()
    for li, s_id in validas.values_list("local_inicio", "sucursal_id"):
        if li:
            horas[timezone.localtime(li).hour] += 1
    horas_lbl = sorted(horas)

    origen_map = dict(Reserva.ORIGENES)
    origen = [(origen_map.get(o, o), n) for o, n in qs.values_list("origen").annotate(n=Count("id")).order_by("-n")]
    top_suc = list(validas.values("sucursal__nombre").annotate(n=Count("id"), p=Sum("num_personas")).order_by("-n")[:6])

    recurrentes = validas.values("cliente_id").annotate(n=Count("id")).filter(n__gte=2).count()
    clientes = validas.values("cliente_id").distinct().count()

    emp_ids = tenancy.empresas_admin_ids(request.user)
    conv = ConversacionIA.objects.filter(creado__date__gte=desde) if hasattr(ConversacionIA, "creado") else ConversacionIA.objects.all()
    conv = conv.filter(empresa_id__in=emp_ids)
    reservas_ia = qs.filter(origen="ia").count()

    ctx = {
        "dias": dias, "desde": desde, "hoy": hoy,
        "kpi": {
            "total": total, "personas": personas, "crecimiento": crecimiento,
            "noshow_pct": round(100 * noshow / total, 1) if total else 0,
            "canc_pct": round(100 * canc / total, 1) if total else 0,
            "clientes": clientes, "recurrentes": recurrentes,
            "recurrentes_pct": round(100 * recurrentes / clientes) if clientes else 0,
            "conversaciones": conv.count(), "reservas_ia": reservas_ia,
            "promedio_mesa": round(personas / validas.count(), 1) if validas.exists() else 0,
        },
        "chart": {
            "dias_lbl": [d.strftime("%d/%m") for d in labels],
            "dias_val": [serie.get(d, 0) for d in labels],
            "horas_lbl": [f"{h}:00" for h in horas_lbl],
            "horas_val": [horas[h] for h in horas_lbl],
            "origen_lbl": [o for o, _ in origen],
            "origen_val": [n for _, n in origen],
        },
        "top_suc": top_suc,
    }
    return render(request, "reservas/panel/resumen.html", ctx)


@staff_member_required
@require_POST
def panel_vigilar(request):
    suc, _nuevo = _sucursal_actual(request)
    if not suc:
        raise PermissionDenied
    ns = piso.marcar_no_shows(suc)
    r = piso.vigilar(suc, auto=True)
    messages.success(request, _("IA de piso: %(v0)s reacomodo(s), %(v1)s aviso(s), %(v2)s no-show marcados.") % {"v0": r['reacomodadas'], "v1": r['avisadas'], "v2": ns})
    return redirect("reservas:panel_hoy")
