# reservas/notificaciones.py
"""
Notificaciones al comensal: correo y WhatsApp (Meta WhatsApp Cloud API).

Nunca rompe el flujo de reserva: cualquier error se registra en el log.
Sin WHATSAPP_TOKEN configurado, el mensaje de WhatsApp solo se escribe en el log
(útil en desarrollo y para la demo).
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import formats, timezone

logger = logging.getLogger("reservas.notificaciones")


# ---------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------
def url_reserva(reserva) -> str:
    return settings.SITE_URL + reverse("reservas:reserva_publica", args=[reserva.token])


def _brand(reserva):
    from .branding import brand_for_empresa
    return brand_for_empresa(reserva.sucursal.empresa if reserva.sucursal_id else None)


def contexto_reserva(reserva) -> dict:
    suc = reserva.sucursal
    dt = (reserva.inicio_utc or reserva.fecha).astimezone(suc.tz())
    return {
        "reserva": reserva,
        "sucursal": suc,
        "brand": _brand(reserva),
        "nombre": (reserva.nombre_contacto or getattr(reserva.cliente, "nombre", "") or "").split(" ")[0],
        "fecha_txt": formats.date_format(dt.date(), "l j \\d\\e F"),
        "hora_txt": dt.strftime("%H:%M"),
        "personas": reserva.num_personas,
        "url_reserva": url_reserva(reserva),
        "SITE_URL": settings.SITE_URL,
    }


def normalizar_telefono(tel: str, pais_iso2: str = "MX") -> str:
    """'55 1234 5678' -> '525512345678' (formato internacional sin '+')."""
    digits = re.sub(r"\D", "", tel or "")
    if not digits:
        return ""
    if pais_iso2 == "MX":
        if len(digits) == 10:
            return "52" + digits
        if len(digits) == 13 and digits.startswith("521"):
            return "52" + digits[3:]
    return digits


def _email_destino(reserva) -> str:
    return (reserva.email_contacto or getattr(reserva.cliente, "email", "") or "").strip()


def _telefono_destino(reserva) -> str:
    tel = reserva.telefono_contacto or getattr(reserva.cliente, "telefono", "")
    iso = reserva.sucursal.pais.iso2 if reserva.sucursal.pais_id else "MX"
    return normalizar_telefono(tel, iso)


# ---------------------------------------------------------------
# Correo
# ---------------------------------------------------------------
def enviar_correo(reserva, tipo: str) -> bool:
    to = _email_destino(reserva)
    if not to:
        return False
    ctx = contexto_reserva(reserva)
    asuntos = {
        "confirmacion": f"Reserva confirmada · {ctx['sucursal'].nombre}",
        "recordatorio": f"Te esperamos {ctx['fecha_txt']} a las {ctx['hora_txt']}",
        "cancelacion": f"Reserva cancelada · {ctx['sucursal'].nombre}",
    }
    try:
        html = render_to_string(f"emails/reserva_{tipo}.html", ctx)
        txt = render_to_string(f"emails/reserva_{tipo}.txt", ctx)
        reply_to = [e for e in [ctx["sucursal"].email_contacto, ctx["brand"]["email"]] if e][:1]
        msg = EmailMultiAlternatives(asuntos[tipo], txt, settings.DEFAULT_FROM_EMAIL, [to], reply_to=reply_to or None)
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("No se pudo enviar el correo %s de la reserva %s", tipo, reserva.pk)
        return False


# ---------------------------------------------------------------
# WhatsApp (Meta Cloud API)
# ---------------------------------------------------------------
def _whatsapp_texto(tipo, ctx) -> str:
    s = ctx["sucursal"]
    if tipo == "confirmacion":
        return (f"Hola {ctx['nombre']}, tu reserva en {s.nombre} está confirmada para el "
                f"{ctx['fecha_txt']} a las {ctx['hora_txt']} ({ctx['personas']} personas). "
                f"Folio {ctx['reserva'].folio}. Ver o cancelar: {ctx['url_reserva']}")
    if tipo == "recordatorio":
        return (f"Hola {ctx['nombre']}, te recordamos tu reserva en {s.nombre} el {ctx['fecha_txt']} "
                f"a las {ctx['hora_txt']}. Si no podrás asistir, cancélala aquí: {ctx['url_reserva']}")
    return f"Tu reserva {ctx['reserva'].folio} en {s.nombre} fue cancelada."


def enviar_whatsapp(reserva, tipo: str) -> bool:
    emp = reserva.sucursal.empresa
    if emp is None or not emp.whatsapp_habilitado:
        return False
    tel = _telefono_destino(reserva)
    if not tel:
        return False
    ctx = contexto_reserva(reserva)
    texto = _whatsapp_texto(tipo, ctx)

    token = settings.WHATSAPP_TOKEN
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    if not (token and phone_id):
        logger.info("[WhatsApp simulado] a %s: %s", tel, texto)
        return True

    plantilla = {
        "confirmacion": settings.WHATSAPP_TEMPLATE_CONFIRMACION,
        "recordatorio": settings.WHATSAPP_TEMPLATE_RECORDATORIO,
    }.get(tipo)
    if plantilla:
        # Plantilla aprobada en Meta con 5 variables: nombre, sucursal, fecha, hora, enlace
        payload = {
            "messaging_product": "whatsapp", "to": tel, "type": "template",
            "template": {
                "name": plantilla, "language": {"code": settings.WHATSAPP_TEMPLATE_LANG},
                "components": [{"type": "body", "parameters": [
                    {"type": "text", "text": ctx["nombre"] or "cliente"},
                    {"type": "text", "text": ctx["sucursal"].nombre},
                    {"type": "text", "text": ctx["fecha_txt"]},
                    {"type": "text", "text": ctx["hora_txt"]},
                    {"type": "text", "text": ctx["url_reserva"]},
                ]}],
            },
        }
    else:
        # Texto libre: Meta solo lo entrega si el cliente escribió en las últimas 24 h
        payload = {"messaging_product": "whatsapp", "to": tel, "type": "text", "text": {"body": texto}}

    try:
        import requests
        url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_id}/messages"
        resp = requests.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=8)
        if resp.status_code >= 300:
            logger.warning("WhatsApp %s falló (%s): %s", tipo, resp.status_code, resp.text[:300])
            return False
        return True
    except Exception:
        logger.exception("Error enviando WhatsApp %s de la reserva %s", tipo, reserva.pk)
        return False


def enviar_texto_whatsapp(telefono: str, texto: str, phone_number_id: str | None = None) -> bool:
    """Mensaje de texto libre (respuesta dentro de la ventana de 24 h que abre el cliente)."""
    token = settings.WHATSAPP_TOKEN
    phone_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
    if not (token and phone_id):
        logger.info("[WhatsApp simulado] a %s: %s", telefono, texto)
        return True
    try:
        import requests
        url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_id}/messages"
        resp = requests.post(url, headers={"Authorization": f"Bearer {token}"}, timeout=8, json={
            "messaging_product": "whatsapp", "to": telefono, "type": "text",
            "text": {"body": texto[:4000], "preview_url": True},
        })
        if resp.status_code >= 300:
            logger.warning("WhatsApp texto falló (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception:
        logger.exception("Error enviando WhatsApp a %s", telefono)
        return False


# ---------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------
def notificar_confirmacion(reserva):
    enviar_correo(reserva, "confirmacion")
    enviar_whatsapp(reserva, "confirmacion")


def notificar_cancelacion(reserva):
    enviar_correo(reserva, "cancelacion")
    enviar_whatsapp(reserva, "cancelacion")


def enviar_recordatorio(reserva) -> bool:
    ok_mail = enviar_correo(reserva, "recordatorio")
    ok_wa = enviar_whatsapp(reserva, "recordatorio")
    if ok_mail or ok_wa:
        type(reserva).objects.filter(pk=reserva.pk).update(recordatorio_enviado_en=timezone.now())
        return True
    return False
