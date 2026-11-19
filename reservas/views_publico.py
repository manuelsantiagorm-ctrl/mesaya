# reservas/views_publico.py
"""
Flujo público del comensal (sin necesidad de crear cuenta):
reservar -> enlace privado de la reserva (ver / cancelar / calendario / QR) y aviso de privacidad.
"""
from __future__ import annotations

from django.utils.translation import gettext as _

from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from . import booking
from .branding import brand_for_empresa
from .forms_publico import ReservaPublicaForm
from .models import Cliente, Reserva, Sucursal


def _sucursal_publica(**lookup):
    return get_object_or_404(Sucursal.objects.publicas().select_related("empresa", "pais"), **lookup)


def _cliente_para(request, data):
    """Usa el Cliente del usuario con sesión, o crea uno nuevo para el invitado."""
    if request.user.is_authenticated:
        cli, _nuevo = Cliente.objects.get_or_create(
            user=request.user, defaults={"nombre": data["nombre"], "email": request.user.email or data.get("email", "")}
        )
        cambios = []
        if data.get("telefono") and cli.telefono != data["telefono"]:
            cli.telefono = data["telefono"][:20]; cambios.append("telefono")
        if not cli.email and data.get("email"):
            cli.email = data["email"]; cambios.append("email")
        if cambios:
            cli.save(update_fields=cambios)
    else:
        cli = Cliente.objects.create(
            nombre=data["nombre"], email=data.get("email") or "", telefono=data["telefono"][:20],
        )
    cli.acepto_privacidad_en = timezone.now()
    cli.acepta_promociones = bool(data.get("acepta_promociones"))
    cli.save(update_fields=["acepto_privacidad_en", "acepta_promociones"])
    return cli


@xframe_options_exempt
@ratelimit(key="ip", rate="20/h", method="POST", block=True)
def reservar(request, slug):
    """Formulario de reserva (también embebible con ?embed=1 en la web del restaurante)."""
    suc = _sucursal_publica(slug=slug)
    tz = suc.tz()
    embed = request.GET.get("embed") == "1" or request.POST.get("embed") == "1"
    ahora_loc = timezone.now().astimezone(tz)

    initial = {
        "fecha": parse_date(request.GET.get("fecha") or "") or ahora_loc.date(),
        "hora": request.GET.get("hora") or "",
        "party": request.GET.get("party") or 2,
    }
    if not request.GET.get("fecha"):
        # Si hoy ya no hay lugar (p. ej. ya cerró), abrimos directamente en el siguiente día con horarios
        from datetime import timedelta as _td
        for k in range(0, 7):
            dia = ahora_loc.date() + _td(days=k)
            if booking.slots_disponibles(suc, dia, 2, limit=1):
                initial["fecha"] = dia
                break
    if request.user.is_authenticated:
        cli = Cliente.objects.filter(user=request.user).first()
        initial.update({
            "nombre": (cli.nombre if cli else "") or request.user.get_full_name(),
            "email": (cli.email if cli else "") or request.user.email,
            "telefono": cli.telefono if cli else "",
        })

    form = ReservaPublicaForm(request.POST or None, initial=initial, max_personas=suc.regla("max_personas"))
    alternativas = []
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        inicio = timezone.make_aware(datetime.combine(d["fecha"], d["hora"]), tz)
        try:
            cliente = _cliente_para(request, d)
            r = booking.crear_reserva(
                sucursal=suc, inicio_local=inicio, party=d["party"], cliente=cliente,
                origen="widget" if embed else "web", notas=d.get("notas", ""),
                nombre_contacto=d["nombre"], email_contacto=d.get("email", ""), telefono_contacto=d["telefono"],
            )
        except booking.ReservaError as e:
            form.add_error(None, e.mensaje)
            alternativas = [a.astimezone(tz).strftime("%H:%M") for a in e.alternativas]
        else:
            url = reverse("reservas:reserva_publica", args=[r.token]) + "?nueva=1"
            if embed:
                url += "&embed=1"
            return redirect(url)

    return render(request, "reservas/publico/reservar.html", {
        "sucursal": suc,
        "form": form,
        "alternativas": alternativas,
        "embed": embed,
        "brand": brand_for_empresa(suc.empresa),
        "ia_disponible": bool(settings.ANTHROPIC_API_KEY),
        "hoy": ahora_loc.date().isoformat(),
        "max_fecha": (ahora_loc.date() + timedelta(days=suc.regla("dias_adelante"))).isoformat(),
    })


@require_GET
def api_slots(request, slug):
    """Horarios disponibles reales (los mismos que acepta la reserva)."""
    suc = _sucursal_publica(slug=slug)
    dia = parse_date(request.GET.get("fecha") or "") or timezone.now().astimezone(suc.tz()).date()
    try:
        party = max(1, min(int(request.GET.get("party") or 2), suc.regla("max_personas")))
    except ValueError:
        party = 2
    slots = booking.slots_disponibles(suc, dia, party)
    return JsonResponse({
        "sucursal": suc.slug,
        "fecha": dia.isoformat(),
        "party": party,
        "slots": [{"value": s.astimezone(suc.tz()).strftime("%H:%M"),
                   "label": s.astimezone(suc.tz()).strftime("%H:%M")} for s in slots],
    })


def _reserva_por_token(token):
    return get_object_or_404(
        Reserva.objects.select_related("sucursal", "sucursal__empresa", "sucursal__pais", "mesa", "cliente"),
        token=token,
    )


@xframe_options_exempt
def reserva_publica(request, token):
    r = _reserva_por_token(token)
    suc = r.sucursal
    dt = (r.inicio_utc or r.fecha).astimezone(suc.tz())
    puede_cancelar = r.estado in (Reserva.PEND, Reserva.CONF) and dt > timezone.now()
    return render(request, "reservas/publico/reserva.html", {
        "r": r,
        "sucursal": suc,
        "dt": dt,
        "nueva": request.GET.get("nueva") == "1",
        "embed": request.GET.get("embed") == "1",
        "puede_cancelar": puede_cancelar,
        "brand": brand_for_empresa(suc.empresa),
        "maps_url": (f"https://www.google.com/maps/search/?api=1&query={suc.lat},{suc.lng}"
                     if suc.lat and suc.lng else ""),
    })


@require_POST
def reserva_publica_cancelar(request, token):
    r = _reserva_por_token(token)
    dt = (r.inicio_utc or r.fecha)
    if dt <= timezone.now():
        messages.error(request, _("La reserva ya pasó y no se puede cancelar."))
    elif booking.cancelar_reserva(r):
        messages.success(request, _("Tu reserva fue cancelada."))
    return redirect("reservas:reserva_publica", token=r.token)


def reserva_ics(request, token):
    r = _reserva_por_token(token)
    ini = (r.inicio_utc or r.fecha).astimezone(dt_timezone.utc)
    fin = (r.fin_utc or (ini + timedelta(minutes=90))).astimezone(dt_timezone.utc)
    fmt = "%Y%m%dT%H%M%SZ"
    suc = r.sucursal
    nombre = (suc.empresa.nombre + " · " if suc.empresa_id else "") + suc.nombre
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Reservas//ES", "METHOD:PUBLISH", "BEGIN:VEVENT",
        f"UID:{r.token}@reservas", f"DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime(fmt)}",
        f"DTSTART:{ini.strftime(fmt)}", f"DTEND:{fin.strftime(fmt)}",
        f"SUMMARY:Reserva en {nombre} ({r.num_personas} personas)",
        f"LOCATION:{(suc.direccion or '').replace(',', ' ')}",
        f"DESCRIPTION:Folio {r.folio}", "END:VEVENT", "END:VCALENDAR", "",
    ])
    resp = HttpResponse(ics, content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="reserva-{r.folio}.ics"'
    return resp


def reserva_qr(request, token):
    """QR para mostrar en recepción: abre la ficha de llegada (solo el personal puede hacer check-in)."""
    import io
    import qrcode
    import qrcode.image.svg
    r = _reserva_por_token(token)
    url = request.build_absolute_uri(reverse("reservas:reserva_scan_entry", args=[r.folio]))
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return HttpResponse(buf.getvalue(), content_type="image/svg+xml")


def aviso_privacidad(request, slug=None):
    from .models import Empresa
    empresa = get_object_or_404(Empresa, slug=slug, activa=True) if slug else getattr(request, "empresa", None)
    return render(request, "reservas/publico/privacidad.html", {
        "empresa": empresa,
        "brand": brand_for_empresa(empresa),
        "hoy": timezone.localdate(),
    })
