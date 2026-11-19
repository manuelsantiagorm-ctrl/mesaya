# reservas/booking.py
"""
Servicio único para crear reservas (cliente web, widget, invitado y API).

- Valida reglas de la sucursal (horario, anticipación, días máximos, personas).
- Limita reservas activas por cliente el mismo día.
- Bloquea la sucursal durante la asignación (pg_advisory_xact_lock) para que dos
  personas nunca se queden con la misma mesa al mismo tiempo.
- Si no hay mesa, lanza NoDisponible con horarios alternativos.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import connection, transaction
from django.utils import timezone

from .utils import (
    asignar_mesa_automatica,
    booking_total_minutes,
    mesa_elegible_para_party,
)


class ReservaError(Exception):
    """Error de negocio con mensaje listo para mostrar al cliente."""

    def __init__(self, mensaje, alternativas=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.alternativas = alternativas or []


class NoDisponible(ReservaError):
    pass


ACTIVAS = ("PEND", "CONF")


def _lock_sucursal(sucursal_id: int):
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", [7301, int(sucursal_id)])


# ---------------------------------------------------------------
# Disponibilidad (en memoria: 3 consultas por día, no N por slot)
# ---------------------------------------------------------------
def _ocupacion_del_dia(sucursal, dia):
    from .models import BloqueoMesa, Mesa, Reserva

    tz = sucursal.tz()
    ini = timezone.make_aware(datetime.combine(dia, time(0, 0)), tz) - timedelta(hours=6)
    fin = ini + timedelta(hours=36)
    mesas = list(
        Mesa.objects.filter(sucursal=sucursal, bloqueada=False).order_by("capacidad", "numero", "id")
    )
    ocupado = {m.id: [] for m in mesas}
    for r in Reserva.objects.filter(
        mesa__sucursal=sucursal, estado__in=ACTIVAS, fecha__gte=ini - timedelta(hours=4), fecha__lt=fin
    ).only("id", "mesa_id", "fecha", "num_personas", "liberada_en", "local_inicio", "local_fin", "llego", "cuenta_pedida_en", "sucursal_id"):
        if r.mesa_id in ocupado:
            ocupado[r.mesa_id].append((r.fecha, r.fin_efectivo(r.num_personas or 2)))
    bloqueos = list(
        BloqueoMesa.objects.filter(sucursal=sucursal, inicio__lt=fin, fin__gt=ini).values_list("mesa_id", "inicio", "fin")
    )
    return mesas, ocupado, bloqueos


def _mesa_libre(mesa, ini, fin, ocupado, bloqueos):
    for a, b in ocupado.get(mesa.id, []):
        if a < fin and b > ini:
            return False
    for mesa_id, a, b in bloqueos:
        if (mesa_id is None or mesa_id == mesa.id) and a < fin and b > ini:
            return False
    return True


def horarios_del_dia(sucursal, dia):
    """Todos los horarios de inicio posibles del día según las reglas de la sucursal."""
    tz = sucursal.tz()
    paso = max(5, sucursal.regla("intervalo_min"))
    apertura = sucursal.regla("hora_apertura")
    cierre = sucursal.regla("hora_cierre")
    cursor = timezone.make_aware(datetime.combine(dia, time(apertura % 24, 0)), tz)
    limite = timezone.make_aware(datetime.combine(dia, time(0, 0)), tz) + timedelta(hours=cierre)
    out = []
    while cursor < limite:
        out.append(cursor)
        cursor += timedelta(minutes=paso)
    return out


def _validar_hora(sucursal, inicio_local, party, ahora=None):
    """Devuelve mensaje de error o None."""
    from .utils import anticipacion_minima_para

    ahora = ahora or timezone.now()
    if party < 1:
        return "Indica cuántas personas asistirán."
    max_p = sucursal.regla("max_personas")
    if party > max_p:
        return f"Para grupos de más de {max_p} personas comunícate con la sucursal."
    if inicio_local < ahora + timedelta(minutes=anticipacion_minima_para(inicio_local.astimezone(sucursal.tz()))):
        return "Ese horario ya no está disponible para reservar en línea."
    if inicio_local.date() > (ahora.astimezone(sucursal.tz()) + timedelta(days=sucursal.regla("dias_adelante"))).date():
        return f"Solo se puede reservar con hasta {sucursal.regla('dias_adelante')} días de anticipación."
    loc = inicio_local.astimezone(sucursal.tz())
    apertura, cierre = sucursal.regla("hora_apertura"), sucursal.regla("hora_cierre")
    minutos = loc.hour * 60 + loc.minute
    if minutos < apertura * 60 or minutos >= cierre * 60:
        return f"La sucursal recibe reservas de {apertura}:00 a {cierre}:00."
    return None


def slots_disponibles(sucursal, dia, party, ahora=None, limit=None):
    """Horarios (datetimes aware) en los que hoy existe al menos una mesa para 'party'."""
    party = max(1, int(party or 2))
    mesas, ocupado, bloqueos = _ocupacion_del_dia(sucursal, dia)
    out = []
    for ini in horarios_del_dia(sucursal, dia):
        if _validar_hora(sucursal, ini, party, ahora):
            continue
        fin = ini + timedelta(minutes=booking_total_minutes(ini, party, sucursal))
        for m in mesas:
            if m.capacidad >= party and mesa_elegible_para_party(m, party, ini) and _mesa_libre(m, ini, fin, ocupado, bloqueos):
                out.append(ini)
                break
        if limit and len(out) >= limit:
            break
    return out


def opciones_disponibles(sucursal, dia, party, hora_preferida=None, zona=None, n=6, ahora=None):
    """
    Evalúa mesas y horarios del día y devuelve las mejores opciones:
    [{"hora": "14:00", "inicio": dt, "mesa": 3, "capacidad": 4, "zona": "terraza"}, ...]
    Orden: cercanía a la hora pedida, luego zona pedida, luego la mesa con menos lugares vacíos.
    Usa exactamente las mismas reglas que crear_reserva (no promete lo que no se puede reservar).
    """
    party = max(1, int(party or 2))
    tz = sucursal.tz()
    mesas, ocupado, bloqueos = _ocupacion_del_dia(sucursal, dia)
    candidatas = []
    for ini in horarios_del_dia(sucursal, dia):
        if _validar_hora(sucursal, ini, party, ahora):
            continue
        fin = ini + timedelta(minutes=booking_total_minutes(ini, party, sucursal))
        libres = [
            m for m in mesas
            if m.capacidad >= party and mesa_elegible_para_party(m, party, ini) and _mesa_libre(m, ini, fin, ocupado, bloqueos)
        ]
        if not libres:
            continue
        if zona:
            en_zona = [m for m in libres if m.zona == zona]
            libres = en_zona or libres
        mejor = min(libres, key=lambda m: (m.capacidad - party, m.numero))
        candidatas.append({
            "hora": ini.astimezone(tz).strftime("%H:%M"),
            "inicio": ini,
            "mesa": mejor.numero,
            "mesa_id": mejor.id,
            "capacidad": mejor.capacidad,
            "zona": mejor.zona,
            "mesas_libres": len(libres),
        })
    if hora_preferida is not None:
        ref = timezone.make_aware(datetime.combine(dia, hora_preferida), tz)
        candidatas.sort(key=lambda c: (abs((c["inicio"] - ref).total_seconds()), c["zona"] != zona if zona else 0))
    return candidatas[:n]


def alternativas_cercanas(sucursal, inicio_local, party, n=3):
    dia = inicio_local.astimezone(sucursal.tz()).date()
    libres = slots_disponibles(sucursal, dia, party)
    libres.sort(key=lambda d: abs((d - inicio_local).total_seconds()))
    return sorted(libres[:n])


# ---------------------------------------------------------------
# Crear reserva
# ---------------------------------------------------------------
def crear_reserva(
    *, sucursal, inicio_local, party, cliente, origen="web", notas="",
    nombre_contacto="", email_contacto="", telefono_contacto="", creada_por_staff=False,
    notificar=True, mesa_preferida_id=None, zona=None, estado=None,
):
    from .models import Reserva

    party = int(party or 2)
    if timezone.is_naive(inicio_local):
        inicio_local = timezone.make_aware(inicio_local, sucursal.tz())
    inicio_local = inicio_local.astimezone(sucursal.tz()).replace(second=0, microsecond=0)

    if sucursal.empresa_id and not sucursal.empresa.activa:
        raise ReservaError("Esta sucursal no está recibiendo reservas en línea.")
    if not sucursal.activo:
        raise ReservaError("Esta sucursal no está recibiendo reservas en línea.")

    if not creada_por_staff:
        err = _validar_hora(sucursal, inicio_local, party)
        if err:
            raise ReservaError(err, alternativas_cercanas(sucursal, inicio_local, party))

    with transaction.atomic():
        _lock_sucursal(sucursal.pk)

        if not creada_por_staff and cliente is not None and cliente.pk:
            dia = inicio_local.date()
            activas = Reserva.objects.filter(
                cliente=cliente, estado__in=ACTIVAS, local_service_date=dia, sucursal__empresa_id=sucursal.empresa_id,
            ).count()
            if activas >= sucursal.regla("max_reservas_cliente_dia"):
                raise ReservaError(
                    "Ya tienes una reserva para ese día. Puedes modificarla o cancelarla desde tu enlace de reserva."
                )

        mesa = None
        dur_pref = booking_total_minutes(inicio_local, party, sucursal)
        fin_pref = inicio_local + timedelta(minutes=dur_pref)
        if mesa_preferida_id or zona:
            from .models import Mesa
            from .utils import checa_choque_reserva_o_bloqueo
            prefs = Mesa.objects.filter(sucursal=sucursal, bloqueada=False, capacidad__gte=party)
            if mesa_preferida_id:
                prefs = prefs.filter(pk=mesa_preferida_id)
            elif zona:
                prefs = prefs.filter(zona=zona).order_by("capacidad", "numero")
            for m in prefs:
                if mesa_elegible_para_party(m, party, inicio_local) and not checa_choque_reserva_o_bloqueo(m, inicio_local, fin_pref, party):
                    mesa = m
                    break
        if mesa is None:
            mesa = asignar_mesa_automatica(sucursal, inicio_local, party)
        if mesa is None:
            raise NoDisponible(
                "No hay mesas disponibles para ese horario.",
                alternativas_cercanas(sucursal, inicio_local, party),
            )

        dur = booking_total_minutes(inicio_local, party, sucursal)
        r = Reserva(
            sucursal=sucursal, mesa=mesa, cliente=cliente, num_personas=party, estado=estado or Reserva.CONF,
            origen=origen, notas=(notas or "")[:300], creada_por_staff=creada_por_staff,
            nombre_contacto=nombre_contacto or getattr(cliente, "nombre", ""),
            email_contacto=email_contacto or getattr(cliente, "email", ""),
            telefono_contacto=telefono_contacto or getattr(cliente, "telefono", ""),
        )
        r.set_from_local(inicio_local.replace(tzinfo=None), dur)
        r.save()

    if notificar:
        from .notificaciones import notificar_confirmacion
        transaction.on_commit(lambda: notificar_confirmacion(r))
    return r


def cancelar_reserva(reserva, por_cliente=True):
    from .models import Reserva

    if reserva.estado == Reserva.CANC:
        return False
    reserva.estado = Reserva.CANC
    reserva.cancelada_en = timezone.now()
    reserva.save(update_fields=["estado", "cancelada_en"])
    return True
