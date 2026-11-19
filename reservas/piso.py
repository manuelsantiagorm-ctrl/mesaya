# reservas/piso.py
"""
Motor de piso en vivo (por sucursal):
  - hora estimada de salida de cada mesa ocupada (usa lo aprendido por la IA de la sucursal),
  - alertas cuando una mesa ocupada no se va a liberar a tiempo para la siguiente reserva,
  - reacomodo automático a otra mesa libre,
  - no-show automático pasada la tolerancia.
Las decisiones son reglas exactas (no un modelo de lenguaje): nunca generan traslapes.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import aprendizaje

log = logging.getLogger(__name__)

MIN_CUENTA = 12          # minutos típicos desde "pidió la cuenta" hasta que se va
VENTANA_ALERTA = 90      # minutos hacia adelante que se vigilan


def salida_estimada(r, ahora=None):
    """Hora estimada en que se desocupa la mesa de una reserva sentada."""
    ahora = ahora or timezone.now()
    if r.liberada_en:
        return r.liberada_en
    if r.cuenta_pedida_en:
        return max(r.cuenta_pedida_en + timedelta(minutes=MIN_CUENTA), ahora + timedelta(minutes=3))
    llegada = r.arrived_at or r.local_inicio
    dur = aprendizaje.duracion_estimada(r.sucursal, r.local_inicio or llegada, r.num_personas)
    est = llegada + timedelta(minutes=dur)
    return est if est > ahora else ahora + timedelta(minutes=10)


def sentadas(suc, ahora=None):
    from .models import Reserva
    ahora = ahora or timezone.now()
    dia = ahora.astimezone(suc.tz()).date()
    qs = (Reserva.objects.filter(sucursal=suc, llego=True, liberada_en__isnull=True,
                                 local_service_date__gte=dia - timedelta(days=1),
                                 local_inicio__gte=ahora - timedelta(hours=6), local_inicio__lte=ahora)
          .exclude(estado__in=[Reserva.CANC, Reserva.NOSH]).select_related("mesa", "sucursal", "cliente"))
    out = []
    for r in qs:
        r.salida_est = salida_estimada(r, ahora)
        llegada = r.arrived_at or r.local_inicio
        r.min_sentados = int((ahora - llegada).total_seconds() // 60) if llegada else 0
        dur = aprendizaje.duracion_estimada(suc, r.local_inicio or llegada, r.num_personas)
        r.excedida_min = max(0, r.min_sentados - dur)
        out.append(r)
    return out


def buscar_mesa_alternativa(r):
    """Otra mesa libre para la reserva r en su horario (misma zona primero, la más chica que alcance)."""
    from .models import Mesa
    from .utils import booking_total_minutes, checa_choque_reserva_o_bloqueo, mesa_elegible_para_party
    ini = r.local_inicio
    fin = r.local_fin or (ini + timedelta(minutes=booking_total_minutes(ini, r.num_personas, r.sucursal)))
    cands = (Mesa.objects.filter(sucursal_id=r.sucursal_id, bloqueada=False, capacidad__gte=r.num_personas)
             .exclude(pk=r.mesa_id).order_by("capacidad", "numero"))
    zona = getattr(r.mesa, "zona", None)
    cands = sorted(cands, key=lambda m: (m.zona != zona, m.capacidad, m.numero))
    for m in cands:
        if not mesa_elegible_para_party(m, r.num_personas, ini):
            continue
        if not checa_choque_reserva_o_bloqueo(m, ini, fin, r.num_personas, exclude_reserva_id=r.pk):
            return m
    return None


def alertas(suc, ahora=None):
    """Reservas próximas cuya mesa sigue ocupada y no se liberará a tiempo."""
    from .models import Reserva
    ahora = ahora or timezone.now()
    colchon = int(suc.regla("colchon_min") or 0)
    ocupadas = {r.mesa_id: r for r in sentadas(suc, ahora)}
    proximas = (Reserva.objects.filter(sucursal=suc, estado__in=[Reserva.PEND, Reserva.CONF], llego=False,
                                       local_inicio__gte=ahora - timedelta(minutes=10),
                                       local_inicio__lte=ahora + timedelta(minutes=VENTANA_ALERTA))
                .select_related("mesa", "sucursal", "cliente").order_by("local_inicio"))
    out = []
    for r in proximas:
        actual = ocupadas.get(r.mesa_id)
        if not actual or actual.pk == r.pk:
            continue
        if actual.salida_est + timedelta(minutes=colchon) <= r.local_inicio:
            continue
        retraso = int((actual.salida_est + timedelta(minutes=colchon) - r.local_inicio).total_seconds() // 60)
        out.append({"reserva": r, "ocupada_por": actual, "retraso_min": max(1, retraso),
                    "alternativa": buscar_mesa_alternativa(r)})
    return out


@transaction.atomic
def reacomodar(r, mesa, motivo="Reacomodo automático"):
    from .models import Reserva
    r = Reserva.objects.select_for_update().get(pk=r.pk)
    anterior = r.mesa.numero
    r.mesa = mesa
    nota = f"[{motivo}: mesa {anterior} → {mesa.numero}]"
    r.notas = (f"{r.notas} {nota}".strip())[:300]
    r.save(update_fields=["mesa", "notas", "modificado"])
    log.info("Reacomodo %s: %s", r.folio, nota)
    return r


def avisar_retraso(r, minutos):
    """Avisa al cliente que su mesa tardará (solo una vez por reserva). Sin cortesías: solo informa."""
    key = f"aviso_retraso:{r.pk}"
    if cache.get(key):
        return False
    cache.set(key, 1, 6 * 3600)
    tel = r.telefono_contacto or getattr(r.cliente, "telefono", "")
    if not tel:
        return False
    from . import notificaciones
    emp = r.sucursal.empresa
    nombre = getattr(emp, "nombre", "") or r.sucursal.nombre
    hora = r.local_inicio.astimezone(r.sucursal.tz()).strftime("%H:%M")
    texto = (f"Hola {r.nombre_contacto or ''}, te escribimos de {nombre}. Tu mesa de las {hora} podría "
             f"estar lista unos {minutos} min después. Si prefieres otra hora, responde este mensaje. ¡Te esperamos!")
    try:
        return notificaciones.enviar_texto_whatsapp(
            notificaciones.normalizar_telefono(tel), texto,
            phone_number_id=getattr(emp, "whatsapp_phone_number_id", None) or None)
    except Exception:
        log.exception("No se pudo avisar el retraso de %s", r.folio)
        return False


def vigilar(suc, ahora=None, auto=True):
    """Revisa la sucursal: reacomoda lo que se pueda y avisa lo que no. Devuelve un resumen."""
    res = {"reacomodadas": 0, "avisadas": 0, "alertas": 0}
    for a in alertas(suc, ahora):
        res["alertas"] += 1
        if not auto:
            continue
        if a["alternativa"]:
            reacomodar(a["reserva"], a["alternativa"], "IA: mesa anterior seguía ocupada")
            res["reacomodadas"] += 1
        elif avisar_retraso(a["reserva"], a["retraso_min"]):
            res["avisadas"] += 1
    return res


def marcar_no_shows(suc, ahora=None):
    """Pasada la tolerancia sin llegada → no-show y la mesa se libera."""
    from .models import Reserva
    ahora = ahora or timezone.now()
    tol = int(suc.regla("tolerancia_min") or 5)
    limite = ahora - timedelta(minutes=tol)
    qs = Reserva.objects.filter(sucursal=suc, estado__in=[Reserva.PEND, Reserva.CONF], llego=False,
                                local_inicio__lt=limite, local_inicio__gte=ahora - timedelta(hours=12))
    return qs.update(estado=Reserva.NOSH, liberada_en=ahora)
