# reservas/views_agente.py
"""Canales del asistente de IA: chat web y WhatsApp (webhook de Meta)."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from . import tenancy
from .agente_ia import AgenteNoDisponible, AgenteReservas, conversacion_para, mensaje_fallback
from .branding import brand_for_empresa
from .models import ConversacionIA, Empresa
from .notificaciones import enviar_texto_whatsapp, normalizar_telefono

logger = logging.getLogger("reservas.agente_ia")


def _ia_configurada() -> bool:
    return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))


# ---------------------------------------------------------------
# Chat web
# ---------------------------------------------------------------
@xframe_options_exempt
def chat_web(request, slug):
    empresa = get_object_or_404(Empresa, slug=slug, activa=True)
    if not (empresa.agente_ia_activo and _ia_configurada()):
        raise Http404("Asistente no disponible")
    return render(request, "reservas/publico/asistente.html", {
        "empresa": empresa,
        "brand": brand_for_empresa(empresa),
        "embed": request.GET.get("embed") == "1",
    })


@require_POST
@ratelimit(key="ip", rate="30/m", block=True)
@ratelimit(key="ip", rate="300/d", block=True)
def chat_web_mensaje(request, slug):
    empresa = get_object_or_404(Empresa, slug=slug, activa=True)
    if not (empresa.agente_ia_activo and _ia_configurada()):
        return JsonResponse({"ok": False, "respuesta": mensaje_fallback(empresa)}, status=503)
    try:
        texto = (json.loads(request.body or b"{}").get("mensaje") or "").strip()
    except ValueError:
        texto = ""
    if not texto:
        return JsonResponse({"ok": False, "error": "Mensaje vacío"}, status=400)

    key = f"ia_chat_{empresa.pk}"
    contacto = request.session.get(key)
    if not contacto:
        contacto = "web-" + secrets.token_hex(8)
        request.session[key] = contacto
    conv = conversacion_para(empresa, "web", contacto)
    try:
        respuesta = AgenteReservas(conv).responder(texto)
    except AgenteNoDisponible:
        return JsonResponse({"ok": False, "respuesta": mensaje_fallback(empresa)}, status=503)
    except Exception:
        logger.exception("Error del asistente (web) empresa=%s", empresa.pk)
        return JsonResponse({"ok": False, "respuesta": "Tuve un problema técnico. " + mensaje_fallback(empresa)}, status=502)
    return JsonResponse({"ok": True, "respuesta": respuesta})


# ---------------------------------------------------------------
# WhatsApp (Meta Cloud API)
# ---------------------------------------------------------------
def _firma_valida(request) -> bool:
    secret = getattr(settings, "WHATSAPP_APP_SECRET", "")
    if not secret:
        return bool(settings.DEBUG)  # en producción la firma es obligatoria
    firma = request.headers.get("X-Hub-Signature-256", "")
    esperado = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(firma, esperado)


def _empresa_por_numero(phone_number_id: str):
    emp = Empresa.objects.filter(whatsapp_phone_number_id=phone_number_id, activa=True).first()
    if emp:
        return emp
    if phone_number_id == getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", ""):
        slug = getattr(settings, "WHATSAPP_EMPRESA_POR_DEFECTO", "")
        return Empresa.objects.filter(slug=slug, activa=True).first() if slug else None
    return None


@csrf_exempt  # Meta no envía token CSRF; se valida la firma HMAC
def whatsapp_webhook(request):
    if request.method == "GET":
        if (request.GET.get("hub.mode") == "subscribe"
                and settings.WHATSAPP_VERIFY_TOKEN
                and request.GET.get("hub.verify_token") == settings.WHATSAPP_VERIFY_TOKEN):
            return HttpResponse(request.GET.get("hub.challenge", ""))
        return HttpResponseForbidden("token inválido")

    if request.method != "POST":
        return HttpResponse(status=405)
    if not _firma_valida(request):
        return HttpResponseForbidden("firma inválida")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponse(status=400)

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_id = (value.get("metadata") or {}).get("phone_number_id", "")
            empresa = _empresa_por_numero(phone_id)
            if empresa is None:
                continue
            nombres = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                if not cache.add(f"wa_msg_{msg.get('id')}", 1, 60 * 60 * 24):
                    continue  # Meta reintenta: no contestar dos veces
                tel = normalizar_telefono(msg.get("from", ""), "MX")
                texto = (msg.get("text") or {}).get("body", "")
                _atender_whatsapp(empresa, phone_id, tel, texto, nombres.get(msg.get("from"), ""))
    return HttpResponse("ok")


def _atender_whatsapp(empresa, phone_id, tel, texto, nombre=""):
    if not (empresa.agente_ia_activo and _ia_configurada()):
        enviar_texto_whatsapp(tel, mensaje_fallback(empresa), phone_id)
        return
    conv = conversacion_para(empresa, "whatsapp", tel)
    if nombre and not conv.nombre:
        conv.nombre = nombre[:120]
        conv.save(update_fields=["nombre"])
    try:
        respuesta = AgenteReservas(conv).responder(texto)
    except Exception:
        logger.exception("Error del asistente (WhatsApp) empresa=%s", empresa.pk)
        respuesta = "Tuve un problema técnico. " + mensaje_fallback(empresa)
    if respuesta:
        enviar_texto_whatsapp(tel, respuesta, phone_id)


# ---------------------------------------------------------------
# Panel del dueño: conversaciones
# ---------------------------------------------------------------
@staff_member_required
def conversaciones(request):
    empresa = getattr(request, "empresa", None) or tenancy.empresa_de_usuario(request.user)
    if empresa is None or not tenancy.is_empresa_admin(request.user, empresa):
        raise Http404()
    qs = ConversacionIA.objects.filter(empresa=empresa).prefetch_related("reservas")
    if request.GET.get("humano") == "1":
        qs = qs.filter(requiere_humano=True)
    sel = None
    if request.GET.get("id"):
        sel = qs.filter(pk=request.GET["id"]).first()
        if sel and request.GET.get("atendida") == "1" and sel.requiere_humano:
            sel.requiere_humano = False
            sel.save(update_fields=["requiere_humano"])
    return render(request, "reservas/empresa/conversaciones.html", {
        "empresa": empresa,
        "conversaciones": qs[:100],
        "sel": sel,
        "ia_configurada": _ia_configurada(),
    })
