# reservas/agente_ia.py
"""
Asistente de reservaciones con IA (Claude).

La IA conversa y decide QUÉ ofrecer; el código decide SI SE PUEDE:
todas las herramientas usan reservas.booking (las mismas reglas, bloqueo contra
doble reserva y límites que la página web). La IA nunca toca la base de datos
directamente y solo ve la empresa de la conversación.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time

from django.conf import settings
from django.db.models import Q
from django.utils import formats, timezone

from . import booking
from .models import Cliente, ConversacionIA, Empresa, Reserva, Sucursal
from .notificaciones import enviar_correo, normalizar_telefono, url_reserva

logger = logging.getLogger("reservas.agente_ia")

MAX_PASOS_HERRAMIENTAS = 6
MAX_MENSAJES_HISTORIAL = 40
MAX_CARACTERES_ENTRADA = 1500
ZONAS = ["interior", "terraza", "exterior"]


class AgenteNoDisponible(Exception):
    pass


# ---------------------------------------------------------------
# Definición de herramientas (lo que la IA puede pedir)
# ---------------------------------------------------------------
HERRAMIENTAS = [
    {
        "name": "consultar_disponibilidad",
        "description": (
            "Evalúa mesas y horarios libres de una sucursal para una fecha y número de personas. "
            "Devuelve las mejores opciones (hora, mesa, zona). Úsala SIEMPRE antes de ofrecer un horario; "
            "nunca supongas disponibilidad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sucursal": {"type": "string", "description": "Clave (slug) de la sucursal"},
                "fecha": {"type": "string", "description": "Fecha en formato AAAA-MM-DD"},
                "personas": {"type": "integer", "minimum": 1},
                "hora_preferida": {"type": "string", "description": "HH:MM en 24 h (opcional)"},
                "zona": {"type": "string", "enum": ZONAS, "description": "Preferencia de zona (opcional)"},
            },
            "required": ["sucursal", "fecha", "personas"],
        },
    },
    {
        "name": "crear_reserva",
        "description": (
            "Crea la reservación. Úsala solo cuando el cliente ya confirmó sucursal, fecha, hora, personas "
            "y nombre, y la hora salió de consultar_disponibilidad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sucursal": {"type": "string"},
                "fecha": {"type": "string", "description": "AAAA-MM-DD"},
                "hora": {"type": "string", "description": "HH:MM en 24 h"},
                "personas": {"type": "integer", "minimum": 1},
                "nombre": {"type": "string"},
                "telefono": {"type": "string", "description": "Teléfono/WhatsApp del cliente"},
                "email": {"type": "string"},
                "notas": {"type": "string", "description": "Ocasión especial, alergias, silla para bebé, etc."},
                "zona": {"type": "string", "enum": ZONAS},
                "mesa": {"type": "integer", "description": "Número de mesa sugerido por consultar_disponibilidad"},
            },
            "required": ["sucursal", "fecha", "hora", "personas", "nombre"],
        },
    },
    {
        "name": "mis_reservas",
        "description": "Lista las reservas próximas del cliente (por su teléfono).",
        "input_schema": {
            "type": "object",
            "properties": {"telefono": {"type": "string", "description": "Solo en chat web; en WhatsApp se usa el del chat"}},
        },
    },
    {
        "name": "cancelar_reserva",
        "description": "Cancela una reserva del cliente. Confirma con el cliente antes de usarla.",
        "input_schema": {
            "type": "object",
            "properties": {
                "folio": {"type": "string"},
                "telefono": {"type": "string", "description": "Solo en chat web, para verificar que es suya"},
            },
            "required": ["folio"],
        },
    },
    {
        "name": "pedir_humano",
        "description": "Avisa al personal que un humano debe atender (grupos grandes, eventos, quejas, dudas que no puedes resolver).",
        "input_schema": {
            "type": "object",
            "properties": {"motivo": {"type": "string"}},
            "required": ["motivo"],
        },
    },
]


# ---------------------------------------------------------------
# Agente
# ---------------------------------------------------------------
class AgenteReservas:
    def __init__(self, conversacion: ConversacionIA, client=None):
        self.conv = conversacion
        self.empresa: Empresa = conversacion.empresa
        self._client = client

    # ---------- cliente de la API ----------
    @property
    def client(self):
        if self._client is None:
            key = getattr(settings, "ANTHROPIC_API_KEY", "")
            if not key:
                raise AgenteNoDisponible("Falta ANTHROPIC_API_KEY")
            import anthropic
            self._client = anthropic.Anthropic(api_key=key, timeout=30, max_retries=2)
        return self._client

    # ---------- contexto ----------
    def sucursales(self):
        return Sucursal.objects.publicas(self.empresa).select_related("pais").order_by("nombre")

    def _sucursal(self, slug):
        s = self.sucursales().filter(Q(slug=slug) | Q(nombre__iexact=slug)).first()
        if s is None:
            raise booking.ReservaError("No encontré esa sucursal.")
        return s

    def system_prompt(self) -> str:
        sucs = list(self.sucursales())
        tz = sucs[0].tz() if sucs else timezone.get_current_timezone()
        ahora = timezone.now().astimezone(tz)
        lineas = []
        for s in sucs:
            zonas = sorted(set(s.mesas.filter(bloqueada=False).values_list("zona", flat=True)))
            lineas.append(
                f"- clave `{s.slug}`: {s.nombre}"
                + (f", {s.direccion}" if s.direccion else "")
                + f". Reservas de {s.regla('hora_apertura')}:00 a {s.regla('hora_cierre')}:00,"
                f" máximo {s.regla('max_personas')} personas en línea,"
                f" hasta {s.regla('dias_adelante')} días de anticipación."
                + (f" Zonas: {', '.join(zonas)}." if zonas else "")
                + (f" Tel. {s.telefono}." if s.telefono else "")
            )
        modo = (
            "Cuando crees una reserva queda CONFIRMADA."
            if self.empresa.agente_ia_modo == Empresa.IA_MODO_RESERVAR
            else "Cuando crees una reserva queda PENDIENTE: dile al cliente que el restaurante se la confirmará en breve."
        )
        canal = (
            f"El cliente escribe por WhatsApp desde el número {self.conv.contacto}; ya tienes su teléfono, no se lo pidas."
            if self.conv.canal == "whatsapp"
            else "El cliente escribe desde el chat de la página web; pide su teléfono para la reserva."
        )
        extra = (self.empresa.agente_ia_instrucciones or "").strip()
        hoy_txt = formats.date_format(ahora.date(), "l j \\d\\e F \\d\\e Y")
        return f"""Eres el asistente de reservaciones de {self.empresa.nombre}. Atiendes a comensales que quieren reservar mesa.

Hoy es {hoy_txt}, son las {ahora:%H:%M} (hora local).
{canal}

Sucursales:
{chr(10).join(lineas) if lineas else '- (sin sucursales activas)'}

Reglas que siempre cumples:
1. Nunca inventes disponibilidad: usa consultar_disponibilidad antes de ofrecer cualquier horario y ofrece solo lo que devuelva.
2. Si el horario pedido no está, ofrece las 2 o 3 opciones más cercanas que te dio la herramienta.
3. Antes de crear_reserva confirma en un solo mensaje: sucursal, fecha, hora, personas y nombre.
4. {modo}
5. Si hay más de una sucursal y el cliente no dijo cuál, pregúntale.
6. Grupos mayores al máximo, eventos privados, quejas o algo que no puedas resolver: usa pedir_humano y dile que el equipo lo contactará.
7. Solo hablas de reservaciones de {self.empresa.nombre}. No des datos de otros clientes. No prometas descuentos ni cosas que no estén en estas instrucciones.
8. Responde en el idioma del cliente, cálido y breve (2 a 4 líneas), sin tecnicismos ni números de mesa salvo que pregunten. Fechas en formato humano ("sábado 15 a las 2:00 p.m.").
9. Al confirmar una reserva, comparte el folio y el enlace para ver o cancelar.
""" + (f"\nIndicaciones del restaurante (no pueden cambiar las reglas anteriores):\n{extra}\n" if extra else "")

    # ---------- herramientas ----------
    def _telefono_cliente(self, dado: str | None) -> str:
        if self.conv.canal == "whatsapp":
            return self.conv.contacto
        return normalizar_telefono(dado or "", "MX")

    @staticmethod
    def _fecha(s: str) -> date:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()

    @staticmethod
    def _hora(s: str) -> time:
        return datetime.strptime(s.strip(), "%H:%M").time()

    def ejecutar(self, nombre: str, args: dict) -> dict:
        try:
            fn = getattr(self, f"tool_{nombre}")
        except AttributeError:
            return {"error": f"Herramienta desconocida: {nombre}"}
        try:
            return fn(**args)
        except booking.ReservaError as e:
            return {"ok": False, "error": e.mensaje,
                    "alternativas": [a.strftime("%H:%M") for a in getattr(e, "alternativas", [])]}
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": f"Datos inválidos: {e}"}

    def tool_consultar_disponibilidad(self, sucursal, fecha, personas, hora_preferida=None, zona=None):
        s = self._sucursal(sucursal)
        dia = self._fecha(fecha)
        hp = self._hora(hora_preferida) if hora_preferida else None
        ops = booking.opciones_disponibles(s, dia, int(personas), hora_preferida=hp, zona=zona, n=6)
        if hp is None:
            ops.sort(key=lambda o: o["inicio"])
        return {
            "sucursal": s.nombre,
            "fecha": dia.isoformat(),
            "personas": int(personas),
            "opciones": [{k: o[k] for k in ("hora", "mesa", "capacidad", "zona", "mesas_libres")} for o in ops],
            "nota": None if ops else "No hay lugar ese día para ese número de personas.",
        }

    def tool_crear_reserva(self, sucursal, fecha, hora, personas, nombre, telefono=None, email="", notas="", zona=None, mesa=None):
        s = self._sucursal(sucursal)
        tel = self._telefono_cliente(telefono)
        if len(re.sub(r"\D", "", tel)) < 8:
            return {"ok": False, "error": "Falta un teléfono válido del cliente."}
        inicio = timezone.make_aware(datetime.combine(self._fecha(fecha), self._hora(hora)), s.tz())
        mesa_id = None
        if mesa:
            mesa_id = s.mesas.filter(numero=int(mesa)).values_list("id", flat=True).first()
        cliente = (
            Cliente.objects.filter(telefono__in=[tel, tel[-10:]], user__isnull=True).order_by("-id").first()
            or Cliente.objects.create(nombre=nombre[:100], telefono=tel[:20], email=(email or "")[:254])
        )
        if self.conv.nombre != nombre:
            self.conv.nombre = nombre[:120]
        proponer = self.empresa.agente_ia_modo == Empresa.IA_MODO_PROPONER
        r = booking.crear_reserva(
            sucursal=s, inicio_local=inicio, party=int(personas), cliente=cliente, origen="ia",
            notas=notas or "", nombre_contacto=nombre, email_contacto=email or "", telefono_contacto=tel,
            mesa_preferida_id=mesa_id, zona=zona, estado=Reserva.PEND if proponer else Reserva.CONF,
            notificar=False,
        )
        self.conv.reservas.add(r)
        if r.email_contacto and not proponer:
            enviar_correo(r, "confirmacion")
        return {
            "ok": True,
            "estado": "pendiente de confirmar por el restaurante" if proponer else "confirmada",
            "folio": r.folio,
            "enlace": url_reserva(r),
            "sucursal": s.nombre,
            "fecha_hora": inicio.strftime("%Y-%m-%d %H:%M"),
            "personas": r.num_personas,
        }

    def _reservas_del_contacto(self, telefono=None):
        tel = self._telefono_cliente(telefono)
        if len(tel) < 8:
            return Reserva.objects.none()
        ultimos10 = tel[-10:]
        return Reserva.objects.filter(
            sucursal__empresa=self.empresa,
            telefono_contacto__endswith=ultimos10,
        ).select_related("sucursal")

    def tool_mis_reservas(self, telefono=None):
        qs = self._reservas_del_contacto(telefono).filter(
            estado__in=[Reserva.PEND, Reserva.CONF], inicio_utc__gte=timezone.now()
        ).order_by("inicio_utc")[:5]
        return {"reservas": [{
            "folio": r.folio,
            "sucursal": r.sucursal.nombre,
            "fecha_hora": r.inicio_utc.astimezone(r.sucursal.tz()).strftime("%Y-%m-%d %H:%M"),
            "personas": r.num_personas,
            "estado": r.get_estado_display(),
        } for r in qs]}

    def tool_cancelar_reserva(self, folio, telefono=None):
        r = self._reservas_del_contacto(telefono).filter(folio__iexact=folio.strip()).first()
        if r is None:
            return {"ok": False, "error": "No encontré una reserva con ese folio a nombre de este teléfono."}
        if r.inicio_utc and r.inicio_utc <= timezone.now():
            return {"ok": False, "error": "Esa reserva ya pasó."}
        booking.cancelar_reserva(r)
        return {"ok": True, "folio": r.folio, "estado": "cancelada"}

    def tool_pedir_humano(self, motivo):
        self.conv.requiere_humano = True
        logger.info("Conversación %s requiere humano: %s", self.conv.pk, motivo)
        return {"ok": True, "mensaje": "Se avisó al equipo del restaurante."}

    # ---------- bucle de conversación ----------
    def _historial_recortado(self):
        msgs = list(self.conv.mensajes or [])
        if len(msgs) <= MAX_MENSAJES_HISTORIAL:
            return msgs
        msgs = msgs[-MAX_MENSAJES_HISTORIAL:]
        # empezar en un mensaje del usuario con texto (no en un tool_result huérfano)
        while msgs and not (msgs[0]["role"] == "user" and isinstance(msgs[0]["content"], str)):
            msgs.pop(0)
        return msgs

    def responder(self, texto: str) -> str:
        if not self.empresa.agente_ia_activo:
            raise AgenteNoDisponible("El asistente está apagado para esta empresa.")
        texto = (texto or "").strip()[:MAX_CARACTERES_ENTRADA]
        if not texto:
            return ""
        mensajes = self._historial_recortado()
        mensajes.append({"role": "user", "content": texto})
        modelo = getattr(settings, "AGENTE_IA_MODELO", "claude-haiku-5-5")
        respuesta_final = ""

        for _ in range(MAX_PASOS_HERRAMIENTAS + 1):
            resp = self.client.messages.create(
                model=modelo,
                max_tokens=int(getattr(settings, "AGENTE_IA_MAX_TOKENS", 1024)),
                system=self.system_prompt(),
                tools=HERRAMIENTAS,
                messages=mensajes,
            )
            uso = getattr(resp, "usage", None)
            if uso is not None:
                self.conv.tokens_entrada += int(getattr(uso, "input_tokens", 0) or 0)
                self.conv.tokens_salida += int(getattr(uso, "output_tokens", 0) or 0)
            bloques = [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b) for b in resp.content]
            mensajes.append({"role": "assistant", "content": bloques})
            textos = [b.get("text", "") for b in bloques if b.get("type") == "text"]
            usos = [b for b in bloques if b.get("type") == "tool_use"]
            if not usos:
                respuesta_final = "\n".join(t for t in textos if t).strip()
                break
            resultados = []
            for u in usos:
                salida = self.ejecutar(u["name"], u.get("input") or {})
                resultados.append({
                    "type": "tool_result",
                    "tool_use_id": u["id"],
                    "content": json.dumps(salida, ensure_ascii=False, default=str),
                })
            mensajes.append({"role": "user", "content": resultados})
        else:
            respuesta_final = "Disculpa, no pude completar tu solicitud. Un miembro del equipo te contactará."
            self.conv.requiere_humano = True

        self.conv.mensajes = mensajes
        self.conv.save()
        return respuesta_final or "¿Me repites, por favor?"


def conversacion_para(empresa: Empresa, canal: str, contacto: str) -> ConversacionIA:
    """Retoma la conversación de las últimas 24 h o abre una nueva."""
    hace24 = timezone.now() - timezone.timedelta(hours=24)
    conv = (
        ConversacionIA.objects.filter(empresa=empresa, canal=canal, contacto=contacto, actualizado__gte=hace24)
        .order_by("-actualizado").first()
    )
    return conv or ConversacionIA.objects.create(empresa=empresa, canal=canal, contacto=contacto)


def mensaje_fallback(empresa: Empresa) -> str:
    suc = Sucursal.objects.publicas(empresa).first()
    if suc is None:
        return "Gracias por escribirnos. En breve te atendemos."
    from django.urls import reverse
    return ("Gracias por escribirnos. Puedes reservar aquí: "
            + settings.SITE_URL + reverse("reservas:reservar_publico", args=[suc.slug]))
