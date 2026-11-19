# reservas/aprendizaje.py
"""
IA que aprende la operación de CADA sucursal, día con día.

No re-entrena ningún modelo de lenguaje: calcula, con los datos de esa sucursal,
  1) cuánto dura realmente una mesa por segmento (día × franja × tamaño de grupo),
  2) el riesgo de que una reserva no llegue (modelo bayesiano ingenuo con suavizado),
  3) la demanda por día y hora,
y propone ajustes. Arranque en frío: lo que configuró el dueño es el "prior" y,
conforme llegan datos reales, el estimado se mueve hacia lo observado:

    estimado = (n · observado + K · prior) / (n + K)

Todo es por sucursal: los datos de una sucursal nunca alteran el perfil de otra.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

K_PRIOR = 10            # peso del prior (equivale a "10 mesas" de evidencia)
MIN_MUESTRAS_SUGERIR = 15
MAX_CAMBIO_DIARIO = 0.10  # el perfil aplicado no se mueve más de ±10 % por recálculo
DUR_MIN, DUR_MAX = 20, 240
DIAS_HISTORIA = 120

from django.utils.translation import gettext as _g, gettext_lazy as _l

DIAS = [("lj", _l("Lun–Jue")), ("vi", _l("Viernes")), ("sa", _l("Sábado")), ("do", _l("Domingo"))]
FRANJAS = [("desayuno", _l("Desayuno")), ("comida", _l("Comida")), ("cena", _l("Cena"))]
GRUPOS = [("1-2", "1–2"), ("3-4", "3–4"), ("5-6", "5–6"), ("7+", "7+")]


# ---------------------------------------------------------------- segmentos
def dia_tipo(dt):
    w = dt.weekday()
    return "lj" if w <= 3 else {4: "vi", 5: "sa", 6: "do"}[w]


def franja(dt):
    h = dt.hour
    return "desayuno" if h < 12 else ("comida" if h < 17 else "cena")


def grupo(n):
    n = int(n or 2)
    return "1-2" if n <= 2 else "3-4" if n <= 4 else "5-6" if n <= 6 else "7+"


def seg_key(dt_local, party):
    return f"{dia_tipo(dt_local)}|{franja(dt_local)}|{grupo(party)}"


def _anticipacion(r):
    if not (r.creado and r.local_inicio):
        return "1-3d"
    d = (r.local_inicio - r.creado).total_seconds() / 86400
    return "mismo día" if d < 1 else "1-3d" if d < 4 else "4-10d" if d < 11 else "+10d"


def _shrink(n, observado, prior, k=K_PRIOR):
    return (n * observado + k * prior) / (n + k)


def _p75(xs):
    xs = sorted(xs)
    if not xs:
        return None
    i = 0.75 * (len(xs) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


# ---------------------------------------------------------------- cálculo
def aprender(sucursal, ahora=None):
    """Recalcula y guarda el PerfilSucursal. Devuelve el perfil."""
    from .models import PerfilSucursal, Reserva
    from .utils import booking_total_minutes

    ahora = ahora or timezone.now()
    tz = sucursal.tz()
    desde = (ahora - timedelta(days=DIAS_HISTORIA)).astimezone(tz).date()
    hoy = ahora.astimezone(tz).date()

    qs = (Reserva.objects.filter(sucursal=sucursal, local_service_date__gte=desde, local_service_date__lte=hoy)
          .only("local_inicio", "num_personas", "estado", "llego", "arrived_at", "liberada_en",
                "creado", "origen", "local_service_date"))

    perfil, _nuevo = PerfilSucursal.objects.get_or_create(sucursal=sucursal)

    # ---------- 1) Duraciones reales por segmento
    obs = defaultdict(list)          # seg -> [minutos]
    obs_grupo = defaultdict(list)    # nivel superior: tamaño de grupo
    pares = []                       # (real, prior) para medir error del tiempo fijo
    for r in qs:
        if not (r.llego and r.arrived_at and r.liberada_en and r.local_inicio):
            continue
        mins = (r.liberada_en - r.arrived_at).total_seconds() / 60
        if not (15 <= mins <= 300):   # sesiones mal cerradas: se ignoran
            continue
        loc = r.local_inicio.astimezone(tz)
        k = seg_key(loc, r.num_personas)
        obs[k].append(mins)
        obs_grupo[grupo(r.num_personas)].append(mins)
        pares.append((k, mins))

    anterior = perfil.duraciones or {}
    colchon = int(sucursal.regla("colchon_min") or 0)
    duraciones = {}
    ejemplo_dt = {"lj": 0, "vi": 4, "sa": 5, "do": 6}
    hora_franja = {"desayuno": 9, "comida": 14, "cena": 20}
    party_grupo = {"1-2": 2, "3-4": 4, "5-6": 6, "7+": 8}
    base = timezone.now().astimezone(tz).replace(hour=12, minute=0, second=0, microsecond=0)
    lunes = base - timedelta(days=base.weekday())
    for d, _ in DIAS:
        for f, _ in FRANJAS:
            for g, _ in GRUPOS:
                k = f"{d}|{f}|{g}"
                dt = (lunes + timedelta(days=ejemplo_dt[d])).replace(hour=hora_franja[f])
                prior = prior_del_dueno(perfil.prior_dueno, d, f, g) or \
                    float(booking_total_minutes(dt, party_grupo[g], sucursal=_SinPerfil(sucursal))) - colchon
                # jerarquía: segmento -> grupo de la sucursal -> lo que configuró el dueño
                xs_g = obs_grupo.get(g, [])
                prior_g = _shrink(len(xs_g), statistics.median(xs_g), prior) if xs_g else prior
                xs = obs.get(k, [])
                n = len(xs)
                if n:
                    p50 = statistics.median(xs)
                    p75 = _p75(xs)
                    est_mostrar = _shrink(n, p50, prior_g)
                    est_reservar = _shrink(n, p75, prior_g)
                else:
                    p50 = p75 = None
                    est_mostrar = est_reservar = prior_g
                # guarda de cambio máximo por recálculo
                prev = (anterior.get(k) or {}).get("reservar")
                if prev:
                    lim = prev * MAX_CAMBIO_DIARIO
                    est_reservar = min(max(est_reservar, prev - lim), prev + lim)
                est_reservar = min(max(est_reservar, DUR_MIN), DUR_MAX)
                duraciones[k] = {
                    "n": n, "p50": round(p50, 1) if p50 else None, "p75": round(p75, 1) if p75 else None,
                    "prior": round(prior), "mostrar": round(est_mostrar), "reservar": round(est_reservar),
                }

    # Error promedio: tiempo fijo vs aprendido (lo que demuestra que la IA sirve)
    if pares:
        err_fijo = statistics.mean(abs(m - duraciones[k]["prior"]) for k, m in pares)
        err_ia = statistics.mean(abs(m - duraciones[k]["mostrar"]) for k, m in pares)
    else:
        err_fijo = err_ia = None

    # ---------- 2) Riesgo de no-show (Bayes ingenuo con suavizado de Laplace)
    pasadas = [r for r in qs if r.local_inicio and r.local_inicio < ahora and r.estado != Reserva.CANC]
    total = len(pasadas)
    faltas = sum(1 for r in pasadas if r.estado == Reserva.NOSH)
    base_rate = (faltas + 1) / (total + 20)  # prior suave ~5 %
    factores = {"anticipacion": _f(), "origen": _f(), "grupo": _f(), "dia": _f()}
    for r in pasadas:
        ns = r.estado == Reserva.NOSH
        loc = r.local_inicio.astimezone(tz)
        for fac, val in (("anticipacion", _anticipacion(r)), ("origen", r.origen or "web"),
                         ("grupo", grupo(r.num_personas)), ("dia", dia_tipo(loc))):
            factores[fac][val][0] += 1
            factores[fac][val][1] += int(ns)
    riesgo = {"base": round(base_rate, 4), "total": total, "faltas": faltas, "factores": {}}
    for fac, vals in factores.items():
        riesgo["factores"][fac] = {
            v: {"n": n, "tasa": round((f + base_rate * 10) / (n + 10), 4)} for v, (n, f) in vals.items()
        }

    # ---------- 3) Demanda: personas promedio por día de la semana × hora
    semanas = max(1, (hoy - desde).days / 7)
    dem = defaultdict(float)
    for r in qs:
        if r.local_inicio and r.estado != Reserva.CANC:
            loc = r.local_inicio.astimezone(tz)
            dem[f"{loc.weekday()}|{loc.hour}"] += r.num_personas / semanas
    demanda = {k: round(v, 1) for k, v in dem.items()}

    # ---------- 4) Sugerencias
    sugerencias = []
    por_semana = defaultdict(float)
    for k, m in pares:
        por_semana[k] += 1 / semanas
    for k, d in duraciones.items():
        if d["n"] < MIN_MUESTRAS_SUGERIR:
            continue
        dif = d["prior"] - d["reservar"]
        if abs(dif) >= 10:
            dd, ff, gg = k.split("|")
            nombre = f"{dict(DIAS)[dd]} · {dict(FRANJAS)[ff].lower()} · grupos de {dict(GRUPOS)[gg]}"
            if dif > 0:
                extra = por_semana[k] * dif / max(d["reservar"], 1)
                sugerencias.append({
                    "tipo": "duracion", "clave": k, "nivel": "oportunidad",
                    "datos": {"dif": round(dif), "n": d["n"], "p75": round(d["p75"]), "extra": max(1, round(extra))},
                    "titulo": f"{nombre}: las mesas se liberan {round(dif)} min antes de lo configurado",
                    "detalle": f"En {d['n']} mesas reales el 75 % se fue antes de {round(d['p75'])} min. "
                               f"Ajustar libera espacio para ~{max(1, round(extra))} reserva(s) más por semana.",
                })
            else:
                sugerencias.append({
                    "tipo": "duracion", "clave": k, "nivel": "riesgo",
                    "datos": {"dif": round(-dif), "n": d["n"], "p75": round(d["p75"])},
                    "titulo": f"{nombre}: las mesas tardan {round(-dif)} min más de lo configurado",
                    "detalle": f"En {d['n']} mesas reales, 1 de cada 4 pasó de {round(d['p75'])} min. "
                               "Con el tiempo actual, el siguiente cliente puede llegar a una mesa ocupada.",
                })
    ant = riesgo["factores"].get("anticipacion", {})
    lejos = ant.get("+10d")
    if lejos and lejos["n"] >= 20 and lejos["tasa"] >= 2 * base_rate:
        sugerencias.append({
            "tipo": "confirmacion", "nivel": "riesgo",
            "datos": {"tasa": round(lejos["tasa"] * 100), "base": round(base_rate * 100)},
            "titulo": "Las reservas hechas con más de 10 días faltan mucho más",
            "detalle": f"Faltan {round(lejos['tasa'] * 100)} % contra {round(base_rate * 100)} % en general. "
                       "Conviene pedir confirmación por WhatsApp 24 h antes.",
        })
    sugerencias.sort(key=lambda s: 0 if s["nivel"] == "riesgo" else 1)

    perfil.duraciones = duraciones
    perfil.riesgo = riesgo
    perfil.demanda = demanda
    perfil.sugerencias = sugerencias
    perfil.muestras = len(pares)
    perfil.metricas = {
        "error_fijo_min": round(err_fijo, 1) if err_fijo is not None else None,
        "error_ia_min": round(err_ia, 1) if err_ia is not None else None,
        "reservas_analizadas": qs.count(),
        "no_show_pct": round(100 * faltas / total, 1) if total else 0,
    }
    perfil.version += 1
    perfil.calculado_en = ahora
    perfil.save()
    return perfil


# ---------------------------------------------------------------- asistente de alta
TIPOS = {
    # tipo: (nombre, pareja entre semana, pareja fin de semana, grupo de 4, grupo de 6+, colchón, tolerancia)
    "rapida": (_l("Comida rápida / taquería"), 35, 45, 45, 60, 5, 5),
    "casual": (_l("Casual / familiar"), 60, 80, 80, 100, 10, 10),
    "cafe": (_l("Cafetería / brunch"), 50, 70, 65, 80, 10, 10),
    "manteles": (_l("Manteles largos / alta cocina"), 100, 120, 120, 150, 15, 15),
    "bar": (_l("Bar / restaurante con música"), 90, 130, 110, 130, 10, 15),
}
FRANJA_FACTOR = {"desayuno": 0.85, "comida": 1.0, "cena": 1.1}


def prior_del_dueno(resp, d, f, g):
    """Minutos esperados para un segmento según lo que contestó el dueño (None si no contestó)."""
    if not resp or not resp.get("pareja_semana"):
        return None
    semana = float(resp["pareja_semana"])
    finde = float(resp.get("pareja_finde") or semana)
    factor_finde = (finde / semana) if (d != "lj" and semana) else 1.0
    if g == "1-2":
        base = semana
    elif g == "3-4":
        base = float(resp.get("grupo4") or semana * 1.25)
    else:
        base = float(resp.get("grupo6") or semana * 1.5) + (15 if g == "7+" else 0)
    factor_f = FRANJA_FACTOR.get(f, 1.0) * (1.05 if resp.get("tipo") == "bar" and f == "cena" else 1.0)
    return round(min(max(base * factor_finde * factor_f, DUR_MIN), DUR_MAX), 1)


def _f():
    return defaultdict(lambda: [0, 0])


class _SinPerfil:
    """Envoltura para obtener el tiempo configurado por el dueño sin usar el perfil aprendido."""
    def __init__(self, s):
        self._s = s
        self._sin_ia = True

    def __getattr__(self, name):
        return getattr(self._s, name)


# ---------------------------------------------------------------- uso en vivo
def perfil_de(sucursal):
    if getattr(sucursal, "_sin_ia", False):
        return None
    if not hasattr(sucursal, "_perfil_cache"):
        from .models import PerfilSucursal
        try:
            sucursal._perfil_cache = PerfilSucursal.objects.filter(sucursal_id=sucursal.pk).first()
        except Exception:
            sucursal._perfil_cache = None
    return sucursal._perfil_cache


def duracion_aprendida(sucursal, dt, party):
    """Minutos aprendidos para reservar, o None si la sucursal no usa aprendizaje."""
    p = perfil_de(sucursal)
    if not p or not p.usar_aprendizaje or not p.duraciones:
        return None
    loc = dt.astimezone(sucursal.tz()) if timezone.is_aware(dt) else dt
    d = p.duraciones.get(seg_key(loc, party))
    return int(d["reservar"]) if d else None


def duracion_estimada(sucursal, dt, party):
    """Minutos esperados (mediana suavizada) para mostrar hora estimada de salida."""
    p = perfil_de(sucursal)
    loc = dt.astimezone(sucursal.tz()) if timezone.is_aware(dt) else dt
    if p and p.duraciones:
        d = p.duraciones.get(seg_key(loc, party))
        if d:
            return int(d["mostrar"])
    from .utils import booking_total_minutes
    return int(booking_total_minutes(dt, party, sucursal=_SinPerfil(sucursal)))


def riesgo_no_show(reserva):
    """Probabilidad estimada (0–1) de que la reserva no llegue, con el modelo de su sucursal."""
    p = perfil_de(reserva.sucursal)
    if not p or not p.riesgo:
        return None
    base = p.riesgo.get("base") or 0.05
    fac = p.riesgo.get("factores", {})
    loc = reserva.local_inicio.astimezone(reserva.sucursal.tz()) if reserva.local_inicio else None
    vals = {"anticipacion": _anticipacion(reserva), "origen": reserva.origen or "web",
            "grupo": grupo(reserva.num_personas), "dia": dia_tipo(loc) if loc else "lj"}
    odds = base / (1 - base)
    for f, v in vals.items():
        t = (fac.get(f, {}).get(v) or {}).get("tasa")
        if t:
            t = min(max(t, 0.001), 0.95)
            odds *= (t / (1 - t)) / (base / (1 - base))
    prob = odds / (1 + odds)
    return round(min(max(prob, 0.0), 0.95), 3)


def texto_sugerencia(s):
    """Título y detalle de una sugerencia en el idioma activo (las guardadas antes de esta versión se muestran tal cual)."""
    d = s.get("datos")
    if not d:
        return s.get("titulo", ""), s.get("detalle", "")
    if s["tipo"] == "duracion":
        dd, ff, gg = s["clave"].split("|")
        nombre = _g("%(dia)s · %(franja)s · grupos de %(grupo)s") % {
            "dia": dict(DIAS)[dd], "franja": str(dict(FRANJAS)[ff]).lower(), "grupo": dict(GRUPOS)[gg]}
        if s["nivel"] == "oportunidad":
            return (_g("%(nombre)s: las mesas se liberan %(dif)s min antes de lo configurado") % {"nombre": nombre, "dif": d["dif"]},
                    _g("En %(n)s mesas reales el 75 %% se fue antes de %(p75)s min. Ajustar libera espacio para ~%(extra)s reserva(s) más por semana.") % d)
        return (_g("%(nombre)s: las mesas tardan %(dif)s min más de lo configurado") % {"nombre": nombre, "dif": d["dif"]},
                _g("En %(n)s mesas reales, 1 de cada 4 pasó de %(p75)s min. Con el tiempo actual, el siguiente cliente puede llegar a una mesa ocupada.") % d)
    return (_g("Las reservas hechas con más de 10 días faltan mucho más"),
            _g("Faltan %(tasa)s %% contra %(base)s %% en general. Conviene pedir confirmación por WhatsApp 24 h antes.") % d)
