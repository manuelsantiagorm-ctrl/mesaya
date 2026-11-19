# reservas/views_ia.py
"""Pantalla 'IA de tu sucursal': lo que aprendió, qué tan precisa es y qué sugiere."""
from django.utils.translation import gettext as _
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import aprendizaje, tenancy
from .models import PerfilSucursal

DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _sucursal(request):
    sucs = tenancy.sucursales_for_user(request.user).order_by("nombre")
    sid = request.GET.get("s") or request.POST.get("s") or request.session.get("panel_sucursal")
    suc = (sucs.filter(pk=sid).first() if sid else None) or sucs.first()
    if suc:
        request.session["panel_sucursal"] = suc.pk
    return suc, sucs


@staff_member_required
@require_http_methods(["GET", "POST"])
def ia_sucursal(request):
    suc, sucs = _sucursal(request)
    if not suc:
        return render(request, "reservas/panel/ia.html", {"sin_sucursal": True})
    puede_editar = tenancy.is_empresa_admin(request.user, suc.empresa)

    if request.method == "POST":
        if not puede_editar:
            raise PermissionDenied
        accion = request.POST.get("accion")
        if accion == "recalcular":
            p = aprendizaje.aprender(suc)
            messages.success(request, _("Listo: la IA analizó %(v0)s mesas de %(v1)s.") % {"v0": p.muestras, "v1": suc.nombre})
        elif accion in ("activar", "desactivar"):
            p, _nuevo = PerfilSucursal.objects.get_or_create(sucursal=suc)
            p.usar_aprendizaje = accion == "activar"
            p.save(update_fields=["usar_aprendizaje"])
            messages.success(request, "Las reservas ya usan los tiempos aprendidos." if p.usar_aprendizaje
                             else "Las reservas vuelven a usar los tiempos fijos.")
        return redirect(f"{request.path}?s={suc.pk}")

    perfil = PerfilSucursal.objects.filter(sucursal=suc).first()
    if perfil is None or not perfil.calculado_en:
        perfil = aprendizaje.aprender(suc)

    # Tabla de duraciones: por día, filas = franja, columnas = tamaño de grupo
    tablas = []
    for d, dn in aprendizaje.DIAS:
        filas = []
        for f, fn in aprendizaje.FRANJAS:
            celdas = []
            for g, gn in aprendizaje.GRUPOS:
                x = perfil.duraciones.get(f"{d}|{f}|{g}") or {}
                delta = (x.get("mostrar") or 0) - (x.get("prior") or 0)
                celdas.append({**x, "delta": delta})
            filas.append({"franja": fn, "celdas": celdas})
        tablas.append({"clave": d, "nombre": dn, "filas": filas})

    # Mapa de calor de demanda
    apertura, cierre = suc.regla("hora_apertura"), min(24, suc.regla("hora_cierre"))
    horas = list(range(apertura, cierre))
    maxv = max(perfil.demanda.values() or [1])
    calor = []
    for wd, nombre in enumerate(DIAS_SEMANA):
        fila = []
        for h in horas:
            v = perfil.demanda.get(f"{wd}|{h}", 0)
            fila.append({"v": v, "pct": int(100 * v / maxv) if maxv else 0})
        calor.append({"dia": nombre, "celdas": fila})

    met = perfil.metricas or {}
    mejora = None
    if met.get("error_fijo_min") and met.get("error_ia_min") is not None and met["error_fijo_min"] > 0:
        mejora = round(100 * (met["error_fijo_min"] - met["error_ia_min"]) / met["error_fijo_min"])

    ant = (perfil.riesgo.get("factores") or {}).get("anticipacion", {})
    orden_ant = ["mismo día", "1-3d", "4-10d", "+10d"]
    riesgo_ant = [{"k": k, **ant[k], "pct": round(ant[k]["tasa"] * 100, 1)} for k in orden_ant if k in ant]
    org = (perfil.riesgo.get("factores") or {}).get("origen", {})
    riesgo_org = sorted([{"k": k, **v, "pct": round(v["tasa"] * 100, 1)} for k, v in org.items()],
                        key=lambda x: -x["pct"])

    sugerencias = []
    for s in (perfil.sugerencias or [])[:8]:
        titulo, detalle = aprendizaje.texto_sugerencia(s)
        sugerencias.append({"nivel": s.get("nivel"), "titulo": titulo, "detalle": detalle})
    return render(request, "reservas/panel/ia.html", {
        "sugerencias": sugerencias,
        "suc": suc, "sucs": sucs, "perfil": perfil, "met": met, "mejora": mejora,
        "tablas": tablas, "grupos": aprendizaje.GRUPOS, "horas": horas, "calor": calor,
        "riesgo_ant": riesgo_ant, "riesgo_org": riesgo_org, "puede_editar": puede_editar,
    })


@staff_member_required
@require_http_methods(["GET", "POST"])
def asistente_alta(request):
    """Asistente de alta: 5 preguntas que la IA usa como punto de partida para esa sucursal."""
    suc, sucs = _sucursal(request)
    if not suc:
        raise PermissionDenied
    if not (tenancy.is_empresa_admin(request.user, suc.empresa)):
        raise PermissionDenied("Solo el dueño o administrador puede configurar la sucursal.")
    perfil, _nuevo = PerfilSucursal.objects.get_or_create(sucursal=suc)
    errores = {}
    if request.method == "POST":
        tipo = request.POST.get("tipo")
        if tipo not in aprendizaje.TIPOS:
            errores["tipo"] = "Elige el tipo de restaurante."
        resp = {"tipo": tipo}
        for campo in ("pareja_semana", "pareja_finde", "grupo4", "grupo6"):
            try:
                v = int(request.POST.get(campo) or 0)
            except ValueError:
                v = 0
            if not (15 <= v <= 240):
                errores[campo] = "Entre 15 y 240 minutos."
            resp[campo] = v
        if not errores:
            preset = aprendizaje.TIPOS[tipo]
            perfil.prior_dueno = resp
            perfil.usar_aprendizaje = True
            perfil.save(update_fields=["prior_dueno", "usar_aprendizaje"])
            # Valores base de la sucursal (por si se desactiva el aprendizaje)
            suc.duracion_min = resp["grupo4"]
            suc.duracion_pico_min = max(resp["grupo4"], round(resp["grupo4"] * resp["pareja_finde"] / max(resp["pareja_semana"], 1)))
            if suc.colchon_min is None:
                suc.colchon_min = preset[5]
            if suc.tolerancia_min is None:
                suc.tolerancia_min = preset[6]
            suc.save(update_fields=["duracion_min", "duracion_pico_min", "colchon_min", "tolerancia_min"])
            aprendizaje.aprender(suc)
            messages.success(request, _("¡Listo! %(v0)s ya ofrece horarios con estos tiempos y la IA aprenderá cada noche a partir de aquí.") % {"v0": suc.nombre})
            return redirect(f"/staff/ia/?s={suc.pk}")
    else:
        resp = perfil.prior_dueno or {}
    return render(request, "reservas/panel/asistente_alta.html", {
        "suc": suc, "sucs": sucs, "resp": resp, "errores": errores,
        "tipos": [(k, v[0], v[1], v[2], v[3], v[4]) for k, v in aprendizaje.TIPOS.items()],
    })
