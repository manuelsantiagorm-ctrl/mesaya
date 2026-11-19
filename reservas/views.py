# reservas/views.py
import os
import json
import logging
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import (
    login_required, user_passes_test, permission_required
)
# BIEN: importar desde models_orders
from .models_orders import Orden, OrdenItem, Order, OrderItem as POSOrderItem

# Si usas catálogo nuevo en las vistas:
from .models_menu import CatalogItem
# Y los core (mesa/sucursal/reserva) siguen en models.py:
from .models import Sucursal, Mesa, Reserva


# Catálogo nuevo (si tu búsqueda usa catálogo)
from .models_menu import CatalogItem
from django.template.loader import render_to_string
from datetime import timezone as py_tz  # <-- para usar py_tz.utc en vez de timezone.utc
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import (
    Q, Exists, OuterRef, Value, BooleanField, Case, When, Max, Count
)
from django.http import (
    JsonResponse, HttpResponse, HttpResponseForbidden,
    HttpResponseRedirect, HttpResponseBadRequest, Http404
)
from reservas.services_orders import liberar_preorden_al_checkin

from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, formats
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_datetime, parse_date
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET, require_POST, require_http_methods
)

from .permissions import assert_user_can_manage_sucursal  # <-- IMPORTANTE
from . import tenancy
from .helpers.permisos import assert_can_manage
from .utils_auth import scope_sucursales_for, user_allowed_countries
from .utils_country import get_effective_country
from .utils import (
    mesas_disponibles_para_reserva, mover_reserva,
    booking_total_minutes, asignar_mesa_automatica
)
from .emails import enviar_correo_reserva_confirmada
from .forms import (
    WalkInReservaForm, ClientePerfilForm, ClienteRegistrationForm,
    ReservaForm, SucursalForm, SucursalFotoForm, SucursalFotoFormSet,
)
from .models import (
    Cliente, Mesa, Reserva, Sucursal, SucursalFoto,
    PerfilAdmin, BloqueoMesa,
)


@login_required
def reserva_scan_entry(request, folio):
    if not request.user.is_staff:
        raise Http404("No encontrado")
    r = get_object_or_404(
        tenancy.scope_by_sucursal(
            Reserva.objects.select_related("sucursal", "mesa", "cliente", "cliente__user"), request.user
        ),
        folio=folio,
    )

    # TZ sucursal y textos de fecha/hora/duración
    tz = _tz_for_sucursal(r.sucursal or (r.mesa and r.mesa.sucursal))
    li = r.local_inicio or (r.inicio_utc and timezone.localtime(r.inicio_utc, tz))
    lf = r.local_fin or (r.fin_utc and timezone.localtime(r.fin_utc, tz))
    fecha_txt = formats.date_format(li.date(), "DATE_FORMAT") if li else ""
    hora_txt = li.strftime("%H:%M") if li else ""
    duracion_min = int(((lf - li).total_seconds() // 60)) if (li and lf) else 0

    ctx = {
        "reserva": r,
        "fecha_txt": fecha_txt,
        "hora_txt": hora_txt,
        "duracion_min": duracion_min,
        "personas": r.num_personas,
        "for_staff": request.user.is_staff,
        **_contacto_from_reserva(r),
    }
    return render(request, "reservas/reserva_scan_entry.html", ctx)

@require_POST
@login_required
def reserva_checkin(request, folio):
    if not request.user.is_staff:
        return HttpResponseForbidden("Solo personal autorizado")

    reserva = get_object_or_404(
        tenancy.scope_by_sucursal(Reserva.objects.all(), request.user), folio__iexact=folio.strip()
    )
    reserva.llego = True
    reserva.checkin_at = dj_tz.now()
    reserva.arrived_at = reserva.checkin_at
    if hasattr(reserva, "estado") and not reserva.estado:
        pass
    reserva.save(update_fields=["llego", "checkin_at", "arrived_at"])

    # ✅ Liberar pre-orden al hacer check-in
    from reservas.services_orders import liberar_preorden_al_checkin
    liberar_preorden_al_checkin(reserva)

    messages.success(request, _("¡Check-in registrado y pedido enviado a cocina!"))
    return redirect("reservas:reserva_scan_entry", folio=reserva.folio)






# --- Rate limit (django-ratelimit, ver requirements.txt) ---
from django_ratelimit.decorators import ratelimit






def _tz_for_sucursal(s) -> timezone.tzinfo:
    """
    Devuelve la TZ de una sucursal.
    Intenta, en orden: s.timezone (o zona_horaria), s.pais.tz; si falla, usa TZ actual de Django.
    """
    # nombres posibles que tú usas en tus modelos
    posibles = ("timezone", "zona_horaria", "tz",)
    tzname = None

    for attr in posibles:
        val = getattr(s, attr, None)
        if val:
            tzname = val
            break

    # intentar via país (s.pais.tz)
    if not tzname:
        try:
            tzname = getattr(getattr(s, "pais", None), "tz", None)
        except Exception:
            tzname = None

    if tzname and ZoneInfo:
        try:
            return ZoneInfo(tzname)
        except Exception:
            pass

    return timezone.get_current_timezone()

# ===================================================================
# Constantes y utilidades internas
# ===================================================================

STEP_MIN = 15  # genera slots cada 15 min
logger = logging.getLogger("reservas.mail")







def _en_ventana_debug_o_ajax(request):
    if settings.DEBUG:
        return True
    if request.user.is_authenticated and request.user.is_staff:
        return True
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_fecha_param(fecha_qs: str):
    """
    Acepta 'YYYY-MM-DD' (ISO) o 'DD/MM/YYYY' y devuelve date().
    Si viene vacío o inválido, regresa hoy (timezone.localdate()).
    """
    if not fecha_qs:
        return timezone.localdate()
    fecha_qs = fecha_qs.strip()
    try:
        return date.fromisoformat(fecha_qs)  # 2025-09-19
    except Exception:
        pass
    try:
        d, m, y = [int(x) for x in fecha_qs.replace(".", "/").split("/")[:3]]  # 19/09/2025
        return date(y, m, d)
    except Exception:
        return timezone.localdate()










# ===================================================================
# HOME / REGISTRO / PERFIL
# ===================================================================


# ===============================
#   HOME
# ===============================

def _sucursales_publicas(request):
    """
    Sucursales que ve el público:
    - Con empresa resuelta (dominio propio, ?e=slug o personal): solo las de esa empresa.
    - En la portada general de la plataforma: las del país detectado (si tiene alguna), si no todas.
    """
    empresa = getattr(request, "empresa", None)
    qs = Sucursal.objects.publicas(empresa).select_related("pais", "empresa")
    if empresa is None:
        pais = get_effective_country(request)
        if pais is not None and qs.filter(pais=pais).exists():
            qs = qs.filter(pais=pais)
    return qs


def home(request):
    user = request.user
    # Visitante sin restaurante elegido → página comercial de la plataforma
    if getattr(request, "empresa", None) is None and not user.is_authenticated and not request.GET.get("q"):
        from .views_ventas import landing
        return landing(request)
    is_admin_staff = user.is_authenticated and user.is_staff

    # ---- Panel “Admin de sucursal” (solo personal) ----
    admin_sucursales = tenancy.sucursales_for_user(user).order_by("nombre") if is_admin_staff else Sucursal.objects.none()

    # ---- Listado público ----
    todas = _sucursales_publicas(request).order_by("nombre")

    # ===== Carrusel: 12 sucursales =====
    sucursales = list(todas[:12])

    # Horarios REALES disponibles hoy para 2 personas (mismas reglas que al reservar)
    from . import booking as _booking
    for s in sucursales:
        try:
            tz = s.tz()
            dia = timezone.now().astimezone(tz).date()
            slots = _booking.slots_disponibles(s, dia, 2, limit=4)
            s.dia_txt = ""
            if not slots:  # hoy ya cerró: mostramos los de mañana
                dia = dia + timedelta(days=1)
                slots = _booking.slots_disponibles(s, dia, 2, limit=4)
                s.dia_txt = "Mañana"
            s.sugerencias = [
                {"txt": d.astimezone(tz).strftime("%H:%M"), "fecha": dia.isoformat()} for d in slots
            ]
        except Exception:
            s.sugerencias = []

    # ===== Recomendadas / Otras (por CP del cliente) =====
    cliente = getattr(user, "cliente", None) if user.is_authenticated else None
    recomendadas_qs = Sucursal.objects.none()
    otras_qs = todas
    if cliente and getattr(cliente, "codigo_postal", None):
        cp = (cliente.codigo_postal or "").strip()
        if cp:
            exactas = todas.filter(codigo_postal=cp)
            if exactas.exists():
                recomendadas_qs = exactas
                otras_qs = todas.exclude(id__in=exactas.values("id"))
            else:
                pref = cp[:3]
                similares = todas.filter(codigo_postal__startswith=pref)
                if similares.exists():
                    recomendadas_qs = similares
                    otras_qs = todas.exclude(id__in=similares.values("id"))

    ctx = {
        "is_admin_staff": is_admin_staff,
        "admin_sucursales": admin_sucursales,
        "sucursales": sucursales,
        "sucursales_recomendadas": recomendadas_qs,
        "otras_sucursales": otras_qs,
        "hoy": timezone.localdate(),
        "party_range": range(1, 13),
        "party_default": "2",
        "user_country": locals().get("user_country", None),  # 👈 agregado
    }
    return render(request, "reservas/home.html", ctx)

@login_required
def perfil(request):
    cliente, _nuevo = Cliente.objects.get_or_create(
        user=request.user,
        defaults={
            "nombre": request.user.get_full_name() or request.user.username,
            "email": request.user.email or "",
        },
    )

    if request.method == "POST":
        form = ClientePerfilForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, _("Perfil actualizado ✅"))
            return redirect("reservas:perfil")
        else:
            messages.error(request, _("Revisa los campos del formulario."))
    else:
        form = ClientePerfilForm(instance=cliente)

    return render(request, "reservas/perfil.html", {"form": form})

# ===================================================================
# BÚSQUEDA / RESULTADOS (tipo OpenTable) + NearMe (lat/lng)
# ===================================================================


def _coords_from_sucursal(s):
    """
    Devuelve (lat, lng) o (None, None) buscando en varios nombres de campo:
    - PointField: ubicacion/location/geo/point (.y=lat, .x=lng)
    - Pares: (latitud,longitud), (latitude,longitude), (lat,lng), (lat,long)
    """
    # GeoDjango PointField
    for field in ("ubicacion", "location", "geo", "point"):
        val = getattr(s, field, None)
        if val is not None and hasattr(val, "x") and hasattr(val, "y"):
            try:
                return float(val.y), float(val.x)
            except Exception:
                pass

    # Pares comunes
    for a, b in (("latitud","longitud"), ("latitude","longitude"),
                 ("lat","lng"), ("lat","long")):
        la = getattr(s, a, None)
        lo = getattr(s, b, None)
        if la is not None and lo is not None:
            try:
                return float(la), float(lo)
            except Exception:
                continue

    return None, None


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def _slots_reales(suc, base_dt, party, n=4):
    """Horarios con mesa REAL para ese día y personas, los más cercanos a la hora pedida."""
    from . import booking as _booking
    try:
        tz = suc.tz()
        loc = base_dt.astimezone(tz)
        slots = _booking.slots_disponibles(suc, loc.date(), int(party or 2))
    except Exception:
        return []
    slots.sort(key=lambda d: abs((d - loc).total_seconds()))
    elegidos = sorted(slots[:n])
    return [{"txt": d.astimezone(tz).strftime("%H:%M"), "fecha": d.astimezone(tz).date().isoformat()} for d in elegidos]


def seleccionar_sucursal(request):
    """
    Lista sucursales con filtro y orden de recomendadas o por distancia.
    GET: q, date (YYYY-MM-DD), time (HH:MM), party (int), page,
         lat, lng, radius_km | km
    """
    q = request.GET.get("q", "").strip()
    date_str = request.GET.get("date")
    time_str = request.GET.get("time")
    party = request.GET.get("party")
    lat = request.GET.get("lat")
    lng = request.GET.get("lng")

    radius_str = request.GET.get("radius_km", request.GET.get("km", "50"))
    try:
        radius_km = float(radius_str)
    except Exception:
        radius_km = 50.0

    # ---- Base: sucursales públicas (empresa / país) ----
    qs = _sucursales_publicas(request)

    # ---- Filtro texto ----
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) |
            Q(direccion__icontains=q) |
            Q(codigo_postal__icontains=q) |
            Q(cocina__icontains=q)
        )

    # ---- Si es Branch Admin (sin países asignados) ----
    if (
        request.user.is_authenticated and request.user.is_staff
        and not request.user.is_superuser
        and not user_allowed_countries(request.user).exists()
    ):
        qs = qs.filter(administradores=request.user)

    # Helper: base_dt por sucursal (en su TZ)
    def _base_dt_for_sucursal(suc: Sucursal) -> datetime:
        tz = ZoneInfo(suc.timezone)
        if date_str:
            try:
                t = datetime.strptime(time_str or "19:00", "%H:%M").time()
                d = date.fromisoformat(date_str)
                return dj_tz.make_aware(datetime.combine(d, t), tz)
            except Exception:
                pass
        # sin fecha: hoy a la hora de cena (19:00) o ahora, lo que sea más tarde
        ahora_loc = timezone.now().astimezone(tz)
        return max(ahora_loc, ahora_loc.replace(hour=19, minute=0, second=0, microsecond=0))

    user_lat = user_lng = None
    results_raw = []

    # --- MODO CERCA DE MÍ ---
    if lat and lng:
        try:
            user_lat, user_lng = float(lat), float(lng)
        except ValueError:
            user_lat = user_lng = None

    if user_lat is not None and user_lng is not None:
        for s in qs:
            s_lat, s_lng = _coords_from_sucursal(s)
            d = None
            if s_lat is not None and s_lng is not None:
                d = _haversine_km(user_lat, user_lng, s_lat, s_lng)
                if d > radius_km:
                    continue
            tz = ZoneInfo(s.timezone)
            base_dt = _base_dt_for_sucursal(s)
            results_raw.append({
                "obj": s,
                "map_lat": s_lat,
                "map_lng": s_lng,
                "distance_km": (None if d is None else round(d, 1)),
                "proximos_slots": _slots_reales(s, base_dt, party),
            })
        results_raw.sort(key=lambda item: (item["distance_km"] is None, item["distance_km"] or 0.0))
    else:
        # --- MODO NORMAL ---
        for s in qs.order_by("-recomendado", "nombre"):
            s_lat, s_lng = _coords_from_sucursal(s)
            tz = ZoneInfo(s.timezone)
            base_dt = _base_dt_for_sucursal(s)
            results_raw.append({
                "obj": s,
                "map_lat": s_lat,
                "map_lng": s_lng,
                "distance_km": None,
                "proximos_slots": _slots_reales(s, base_dt, party),
            })

    paginator = Paginator(results_raw, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    ctx = {
        "q": q,
        "date": date_str or dj_tz.localdate().strftime("%Y-%m-%d"),
        "time": time_str or "19:00",
        "party": party or "2",
        "page_obj": page_obj,
        "results": list(page_obj.object_list),
        "party_range": range(1, 13),
        "user_lat": user_lat,
        "user_lng": user_lng,
        "radius_km": int(radius_km),
        "user_country": locals().get("user_country", None),
    }
    return render(request, "reservas/seleccionar_sucursal.html", ctx)



# --- Redirección directa desde "Ver disponibilidad" al detalle de sucursal ---





# ===================================================================
# HACER UNA RESERVA
# ===================================================================






@login_required
def mis_reservas(request):
    cliente, _nuevo = Cliente.objects.get_or_create(
        user=request.user,
        defaults={"nombre": request.user.get_full_name() or request.user.username, "email": request.user.email or ""},
    )
    ahora = timezone.now()
    base = Reserva.objects.filter(cliente=cliente).select_related("sucursal", "sucursal__empresa", "mesa")
    proximas = (base.filter(estado__in=[Reserva.PEND, Reserva.CONF], local_inicio__gte=ahora - timedelta(minutes=30))
                .order_by("local_inicio"))
    pasadas = base.exclude(pk__in=proximas.values("pk")).order_by("-local_inicio", "-fecha")[:12]
    return render(request, "reservas/mis_reservas.html", {"proximas": proximas, "pasadas": pasadas, "ahora": ahora})


# ===================================================================
# SUCURSAL y MESAS (cliente)
# ===================================================================
# reservas/views.py

# ===================================================================
# ADMIN: SUCURSALES (UI propia) + FORM crear/editar con imagen
# ===================================================================






# ===================================================================
# ADMIN: MAPA/DETALLE/CONFIRMAR/AGENDA
# ===================================================================
@staff_member_required
def admin_mapa_sucursal(request, sucursal_id):
    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)
    if not _puede_ver_sucursal(request.user, sucursal):
        return HttpResponseForbidden("No tienes permiso para esta sucursal.")

    # ventana para “estado actual”
    ahora = timezone.now()
    tol_min = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ventana_ini = ahora - timedelta(minutes=tol_min)
    ventana_fin = ahora + timedelta(minutes=tol_min)

    # prefetch simple
    mesas = (
        Mesa.objects.filter(sucursal=sucursal)
        .order_by("numero", "id")
    )

    estado_mesas = []
    for m in mesas:
        # reservas relevantes (hoy +- un margen)
        reservas = list(
            Reserva.objects
            .filter(sucursal=sucursal, mesa=m, fecha__date=ahora.date())
            .order_by("fecha")[:5]
        )

        # estado: bloqueada / reservada (en ventana) / ocupada (si llegó) / disponible
        if m.bloqueada:
            est = "OCUPADA"
        else:
            r_actual = next((r for r in reservas if ventana_ini <= r.fecha <= ventana_fin), None)
            if r_actual and r_actual.llego:
                est = "OCUPADA"
            elif r_actual:
                est = "RESERVADA"
            else:
                est = "DISPONIBLE"

        estado_mesas.append({"mesa": m, "estado": est, "reservas": reservas})

    ctx = {
        "sucursal": sucursal,
        "estado_mesas": estado_mesas,
    }
    return render(request, "reservas/admin_mapa_sucursal.html", ctx)








@staff_member_required
def admin_mesa_detalle(request, mesa_id):
    """
    Vista de detalle de mesa (panel staff/admin).

    - Dueño de cadena (superuser o con permiso manage_branches) puede ver todas.
    - Staff solo puede ver mesas de sus sucursales visibles.
    - Muestra la reserva activa o próxima, y habilita acciones de confirmar/finalizar.
    """
    mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.select_related("sucursal"), request.user), pk=mesa_id)
    if not _puede_ver_sucursal(request.user, mesa.sucursal):
        return HttpResponseForbidden("No tienes permiso para ver esta mesa.")

    # Configuración de tolerancia para llegada (CHECKIN)
    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    gracia = int(getattr(settings, "CHECKIN_GRACIA_MIN", tol))
    ahora = timezone.now()


    reserva = (
        Reserva.objects.filter(
            mesa=mesa,
            estado__in=[Reserva.PEND, Reserva.CONF],
            fecha__gte=ahora - timedelta(minutes=gracia),
        )
        .order_by("fecha")
        .first()
    )
    if not reserva:
        reserva = (
            Reserva.objects.filter(
                mesa=mesa,
                estado__in=[Reserva.PEND, Reserva.CONF],
                fecha__gte=ahora,
            )
            .order_by("fecha")
            .first()
        )

    # Determinar permisos de acción sobre la reserva
    puede_confirmar = False
    puede_finalizar = False

    if reserva:
        inicio = reserva.fecha - timedelta(minutes=tol)
        fin = reserva.fecha + timedelta(minutes=tol)

        puede_confirmar = (
            (not getattr(reserva, "llego", False))
            and (reserva.estado in [Reserva.PEND, Reserva.CONF])
            and (inicio <= ahora <= fin)
        )
        
        puede_finalizar = bool(getattr(reserva, "llego", False))

    # Contexto para template
    ctx = {
        "mesa": mesa,
        "reserva": reserva,
        "puede_confirmar": puede_confirmar,
        "puede_finalizar": puede_finalizar,
    }
    return render(request, "reservas/admin_mesa_detalle.html", ctx)

#####################################################################
@require_POST
@staff_member_required
@transaction.atomic
def admin_confirmar_llegada(request, reserva_id):
    """
    Confirma llegada (check-in) de una reserva con:
    - bloqueo select_for_update
    - validación de tolerancia de tiempo
    - validación de permisos por sucursal
    - opción 'force' solo para superuser
    """
    r = get_object_or_404(tenancy.scope_by_sucursal(Reserva.objects.select_for_update(), request.user), pk=reserva_id)

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        return HttpResponseForbidden("No tienes permiso para confirmar esta reserva.")

    if getattr(r, "llego", False):
        messages.info(request, _("La llegada ya estaba confirmada."))
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    if r.estado not in [Reserva.PEND, Reserva.CONF]:
        messages.error(request, _("La reserva no está en un estado válido para check-in."))
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ahora = timezone.now()
    inicio = r.fecha - timedelta(minutes=tol)
    fin    = r.fecha + timedelta(minutes=tol)

    force = bool(request.POST.get("force")) and request.user.is_superuser
    if not (inicio <= ahora <= fin) and not force:
        messages.error(request, _("Fuera de la ventana de llegada."))
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    r.llego = True
    if hasattr(r, "checkin_at"):
        r.checkin_at = ahora
    else:
        setattr(r, "arrived_at", ahora)
    if r.estado == Reserva.PEND:
        r.estado = Reserva.CONF

    update_fields = ["llego", "estado"]
    if hasattr(r, "checkin_at"):
        update_fields.append("checkin_at")
    else:
        update_fields.append("arrived_at")
    if hasattr(r, "modificado"):
        update_fields.append("modificado")

    r.save(update_fields=update_fields)
    messages.success(request, _("Llegada confirmada ✅"))
    return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)








#####################################################################

# ===================================================================
# DISPONIBILIDAD (cliente y staff) / AGENDA
# ===================================================================




@require_GET
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def agenda_mesa(request, mesa_id):
    if not _en_ventana_debug_o_ajax(request):
        return HttpResponseForbidden("Sólo AJAX")
    try:
        mesa = tenancy.scope_by_sucursal(Mesa.objects.all(), request.user).get(pk=mesa_id)
    except Mesa.DoesNotExist:
        return JsonResponse({"error": "Mesa no existe"}, status=404)

    fecha_qs = request.GET.get("fecha")
    dia = _parse_fecha_param(fecha_qs)

    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime(dia.year, dia.month, dia.day, 0, 0), tz)
    fin = inicio + timedelta(days=1)

    reservas = (
        Reserva.objects
        .filter(mesa=mesa, fecha__gte=inicio, fecha__lt=fin)
        .only("fecha", "num_personas", "liberada_en", "estado", "cliente")
        .order_by("fecha")
    )

    items = []
    for r in reservas:
        fin_eff = r.fin_efectivo(getattr(r, "num_personas", 2) or 2)
        items.append({
            "id": r.id,
            "estado": r.estado,
            "inicio": r.fecha.astimezone(tz).strftime("%H:%M"),
            "fin":  fin_eff.astimezone(tz).strftime("%H:%M"),
            "cliente": getattr(r.cliente, "nombre", ""),
        })

    return JsonResponse({"items": items})



# ===================================================================
# ADMIN: BUSCAR/CHECK-IN/CANCELAR/REACTIVAR por FOLIO
# ===================================================================

@login_required
def admin_buscar_folio(request):
    if not request.user.is_staff:
        return redirect("reservas:home")

    folio = (request.GET.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    reserva = None
    error = None
    puede_confirmar = False
    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ventana_ini = ventana_fin = None

    if folio:
        try:
            reserva = (tenancy.scope_by_sucursal(Reserva.objects.all(), request.user)
                       .select_related("mesa__sucursal", "cliente")
                       .get(folio=folio))

            ahora = timezone.now()
            inicio = reserva.fecha - timedelta(minutes=tol)
            fin    = reserva.fecha + timedelta(minutes=tol)

            puede_confirmar = (
                (not getattr(reserva, "llego", False)) and
                (reserva.estado in ["PEND", "CONF"]) and
                (inicio <= ahora <= fin)
            )

            tz = timezone.get_current_timezone()
            ventana_ini = inicio.astimezone(tz).strftime("%d/%b/%Y %H:%M")
            ventana_fin = fin.astimezone(tz).strftime("%d/%b/%Y %H:%M")

        except Reserva.DoesNotExist:
            error = f"No se encontró ninguna reserva con el folio {folio}."

    ctx = {
        "folio": folio,
        "reserva": reserva,
        "error": error,
        "puede_confirmar": puede_confirmar,
        "tolerancia_min": tol,
        "ventana_ini": ventana_ini,
        "ventana_fin": ventana_fin,
    }
    return render(request, "reservas/admin_buscar_folio.html", ctx)


@staff_member_required
def admin_checkin_por_folio(request):
    if request.method != "POST":
        return redirect("reservas:admin_buscar_folio")

    folio = (request.POST.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    try:
        r = tenancy.scope_by_sucursal(Reserva.objects.all(), request.user).get(folio=folio)
    except Reserva.DoesNotExist:
        messages.error(request, _("No se encontró la reserva."))
        return redirect("reservas:admin_buscar_folio")

    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ahora = timezone.now()
    inicio = r.fecha - timedelta(minutes=tol)
    fin    = r.fecha + timedelta(minutes=tol)

    force = bool(request.POST.get("force")) and request.user.is_superuser

    if getattr(r, "llego", False):
        messages.warning(request, _("Esta reserva ya fue marcada como llegada."))
    elif r.estado not in ["PEND", "CONF"]:
        messages.error(request, _("La reserva no está en un estado válido para check-in."))
    elif not (inicio <= ahora <= fin) and not force:
        messages.error(request, _("Fuera de la ventana de llegada."))
    else:
        r.llego = True
        if hasattr(r, "checkin_at"):
            r.checkin_at = ahora
        else:
            setattr(r, "arrived_at", ahora)
        if r.estado != "CONF":
            r.estado = "CONF"

        update_fields = ["llego", "estado"]
        if hasattr(r, "checkin_at"):
            update_fields.append("checkin_at")
        else:
            update_fields.append("arrived_at")
        if hasattr(r, "modificado"):
            update_fields.append("modificado")

        r.save(update_fields=update_fields)
        messages.success(request, _("✅ Llegada confirmada para folio %(v0)s.") % {"v0": r.folio})

    return HttpResponseRedirect(f"{reverse('reservas:admin_buscar_folio')}?folio={folio}")


@staff_member_required
@require_POST
def admin_cancelar_por_folio(request):
    folio = (request.POST.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    try:
        r = Reserva.objects.select_related("mesa__sucursal").get(folio=folio)
    except Reserva.DoesNotExist:
        messages.error(request, _("No se encontró la reserva."))
        return redirect("reservas:admin_buscar_folio")

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        messages.error(request, _("No tienes permiso para cancelar esta reserva."))
        return HttpResponseRedirect(f"{reverse('reservas:admin_buscar_folio')}?folio={folio}")

    if r.estado == "CANC":
        messages.info(request, _("La reserva %(v0)s ya estaba cancelada.") % {"v0": r.folio})
    else:
        r.estado = "CANC"
        r.save(update_fields=["estado"])
        messages.success(request, _("✅ Reserva %(v0)s cancelada correctamente.") % {"v0": r.folio})

    return HttpResponseRedirect(f"{reverse('reservas:admin_buscar_folio')}?folio={folio}")


@staff_member_required
@require_POST
def admin_reactivar_por_folio(request):
    folio = (request.POST.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    try:
        r = Reserva.objects.select_related("mesa__sucursal").get(folio=folio)
    except Reserva.DoesNotExist:
        messages.error(request, _("No se encontró la reserva."))
        return HttpResponseRedirect(reverse("reservas:admin_dashboard"))

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        messages.error(request, _("No tienes permiso sobre esta sucursal."))
        return HttpResponseRedirect(reverse("reservas:admin_dashboard"))

    if r.estado != "CANC":
        messages.info(request, _("La reserva %(v0)s no está cancelada.") % {"v0": r.folio})
    else:
        r.estado = "PEND"
        r.save(update_fields=["estado"])
        messages.success(request, _("✅ Reserva %(v0)s reactivada como %(v1)s.") % {"v0": r.folio, "v1": r.get_estado_display()})

    fecha = request.GET.get("fecha")
    url = reverse("reservas:admin_dashboard")
    return HttpResponseRedirect(f"{url}?fecha={fecha}" if fecha else url)


# ===================================================================
# ADMIN: DASHBOARD y WALK-IN
# ===================================================================


@staff_member_required
def admin_walkin_reserva(request):
    """
    Crea una reserva Walk-in, opcionalmente fijando sucursal del PerfilAdmin.
    """
    suc_pref = None
    if True:
        try:
            suc_pref = PerfilAdmin.objects.get(user=request.user).sucursal_asignada
        except PerfilAdmin.DoesNotExist:
            suc_pref = None

    if request.method == "POST":
        form = WalkInReservaForm(request.POST, user=request.user, sucursal_pref=suc_pref)
        if form.is_valid():
            reserva = form.save()
            tz = timezone.get_current_timezone()
            dia = timezone.localdate(reserva.fecha, tz).isoformat()
            messages.success(
                request,
                mark_safe(
                    f"✅ Walk-in creada para <b>{reserva.cliente.nombre}</b> "
                    f"({timezone.localtime(reserva.fecha, tz):%d/%b %H:%M}). "
                    f"Folio: <b>{reserva.folio}</b>"
                ),
            )
            url = reverse("reservas:admin_dashboard")
            return redirect(f"{url}?fecha={dia}")
        messages.error(request, _("Revisa los campos del formulario."))
    else:
        form = WalkInReservaForm(user=request.user, sucursal_pref=suc_pref)

    return render(request, "reservas/admin_walkin_form.html", {"form": form})
# ===================================================================
# API Staff: mesas y bloqueos (JSON)
# ===================================================================

def _json_bad(msg, status=400):
    return JsonResponse({"ok": False, "error": msg}, status=status)


@staff_member_required
@require_POST
def admin_api_mesa_create(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return _json_bad("JSON inválido")

    sucursal_id = data.get("sucursal_id")
    numero      = data.get("numero")
    capacidad   = data.get("capacidad")
    ubicacion   = data.get("ubicacion","")
    bloqueada   = bool(data.get("bloqueada", False))

    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)

    if not numero:
        return _json_bad("Falta 'numero'.")
    if not capacidad:
        return _json_bad("Falta 'capacidad'.")

    try:
        capacidad = int(capacidad)
        if capacidad <= 0:
            raise ValueError
    except ValueError:
        return _json_bad("Capacidad debe ser entero > 0.")

    m = Mesa.objects.create(
        sucursal=sucursal,
        numero=numero,
        capacidad=capacidad,
        ubicacion=ubicacion or "",
        bloqueada=bloqueada if hasattr(Mesa, "bloqueada") else False,
    )
    return JsonResponse({"ok": True, "mesa": {
        "id": m.id, "numero": m.numero, "capacidad": m.capacidad,
        "ubicacion": getattr(m, "ubicacion", "") or "",
        "bloqueada": getattr(m, "bloqueada", False),
    }})


def _slots_disponibles(mesa, fecha_dt, party=2):
    """
    Devuelve lista de datetimes (aware) con inicios posibles para ese día,
    considerando la duración dinámica, choques con reservas (con fin efectivo)
    y bloqueos. Usa paso de 15 minutos.
    """
    from .utils import booking_total_minutes  # asegúrate de tener esta función en utils

    if hasattr(mesa, "bloqueada") and getattr(mesa, "bloqueada", False):
        return []

    tz = ZoneInfo(mesa.sucursal.timezone)
    base = timezone.make_aware(datetime(fecha_dt.year, fecha_dt.month, fecha_dt.day, 0, 0, 0), tz)

    apertura = int(getattr(settings, 'HORARIO_APERTURA', 8))
    cierre   = int(getattr(settings, 'HORARIO_CIERRE', 22))
    paso     = 15

    inicio_j = base + timedelta(hours=apertura)
    fin_j    = base + timedelta(hours=cierre)

    # Cargar reservas del rango del día (un poco más amplio) y bloqueos
    # Importante: no uses .only('fecha') a secas; necesitamos num_personas y liberada_en
    reservas = (
        Reserva.objects
        .filter(
            mesa=mesa,
            estado__in=['PEND', 'CONF'],
            fecha__gte=inicio_j - timedelta(hours=3),
            fecha__lt=fin_j + timedelta(hours=3),
        )
        .only('fecha', 'num_personas', 'liberada_en')  # evita queries extra al calcular fin_efectivo
        .order_by('fecha')
    )

    bloqueos = (
        BloqueoMesa.objects
        .filter(sucursal=mesa.sucursal)
        .filter(Q(mesa__isnull=True) | Q(mesa=mesa))
        .filter(Q(inicio__lt=fin_j) & Q(fin__gt=inicio_j))
        .only('inicio', 'fin')
    )

    def se_traslapa(ini_a, fin_a, ini_b, fin_b):
        return ini_a < fin_b and fin_a > ini_b

    def esta_libre(slot_ini):
        # duración dinámica del slot propuesto (depende de hora y tamaño de grupo)
        total_min = booking_total_minutes(slot_ini, party)
        slot_fin = slot_ini + timedelta(minutes=total_min)

        # Reservas: usar fin EFECTIVO (respeta liberada_en)
        for r in reservas:
            r_ini = r.fecha
            r_fin = r.fin_efectivo(getattr(r, "num_personas", party) or party)
            if se_traslapa(slot_ini, slot_fin, r_ini, r_fin):
                return False

        # Bloqueos
        for b in bloqueos:
            if se_traslapa(slot_ini, slot_fin, b.inicio, b.fin):
                return False

        return True

    out = []
    cur = inicio_j
    ahora = timezone.localtime()
    while cur < fin_j:
        dur_min = booking_total_minutes(cur, party)
        if cur + timedelta(minutes=dur_min) > fin_j:
            break
        if cur >= ahora and esta_libre(cur):
            out.append(cur)
        cur += timedelta(minutes=paso)

    return out






@staff_member_required
@require_http_methods(["POST"])
def admin_api_bloqueo_create(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=data.get("sucursal_id"))

    if not _puede_ver_sucursal(request.user, sucursal):
        return JsonResponse({"ok": False, "error": "Sin permiso sobre la sucursal."}, status=403)

    mesa = None
    mesa_id = data.get("mesa_id")
    if mesa_id:
        mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id, sucursal=sucursal)

    inicio = parse_datetime(data.get("inicio") or "")
    fin    = parse_datetime(data.get("fin") or "")
    if not inicio or not fin:
        return JsonResponse({"ok": False, "error": "Fechas 'inicio' y 'fin' requeridas (ISO 8601)."}, status=400)
    if fin <= inicio:
        return JsonResponse({"ok": False, "error": "El fin debe ser mayor al inicio."}, status=400)

    tz = timezone.get_current_timezone()
    if timezone.is_naive(inicio):
        inicio = timezone.make_aware(inicio, tz)
    if timezone.is_naive(fin):
        fin = timezone.make_aware(fin, tz)

    mot = (data.get("motivo") or "").strip()[:200]

    try:
        b = BloqueoMesa.objects.create(
            sucursal=sucursal, mesa=mesa, inicio=inicio, fin=fin, motivo=mot,
        )
    except TypeError as e:
        return JsonResponse({"ok": False, "error": f"Error al crear bloqueo: {e}"}, status=500)

    return JsonResponse({"ok": True, "bloqueo": {
        "id": b.id, "mesa_id": b.mesa_id, "sucursal_id": b.sucursal_id,
        "inicio": b.inicio.isoformat(), "fin": b.fin.isoformat(), "motivo": b.motivo,
    }})


@staff_member_required
@require_http_methods(["GET"])
def admin_api_bloqueo_list(request):
    """
    Lista bloqueos en JSON.
    Querystring:
      - sucursal_id (int) [requerido]
      - mesa_id (int|opcional)
      - desde (YYYY-MM-DD|opcional, por defecto hoy local)
    """
    try:
        sucursal_id = int(request.GET.get("sucursal_id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "sucursal_id requerido"}, status=400)

    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)
    if not _puede_ver_sucursal(request.user, sucursal):
        return JsonResponse({"ok": False, "error": "Sin permiso sobre la sucursal"}, status=403)

    mesa_id = request.GET.get("mesa_id")
    mesa = None
    if mesa_id:
        try:
            mesa_id = int(mesa_id)
            mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id, sucursal=sucursal)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "mesa_id inválido"}, status=400)

    try:
        dstr = request.GET.get("desde", "") or timezone.localdate().isoformat()
        y_, m_, d_ = [int(x) for x in dstr.split("-")]
        desde = timezone.make_aware(datetime(y_, m_, d_, 0, 0), timezone.get_current_timezone())
    except Exception:
        return JsonResponse({"ok": False, "error": "desde inválido (YYYY-MM-DD)"}, status=400)

    qs = BloqueoMesa.objects.filter(sucursal=sucursal, fin__gte=desde)
    if mesa:
        qs = qs.filter(Q(mesa__isnull=True) | Q(mesa=mesa))
    qs = qs.order_by("inicio")[:200]

    items = []
    for b in qs:
        items.append({
            "id": b.id,
            "sucursal_id": b.sucursal_id,
            "mesa_id": b.mesa_id,
            "inicio": b.inicio.isoformat(),
            "fin": b.fin.isoformat(),
            "motivo": b.motivo or "",
            "scope": "mesa" if b.mesa_id else "sucursal",
        })
    return JsonResponse({"ok": True, "items": items})


@staff_member_required
@require_http_methods(["POST"])
def admin_api_bloqueo_delete(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    try:
        bid = int(data.get("id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "id requerido"}, status=400)

    b = get_object_or_404(tenancy.scope_by_sucursal(BloqueoMesa.objects.all(), request.user), pk=bid)
    if not _puede_ver_sucursal(request.user, b.sucursal):
        return JsonResponse({"ok": False, "error": "Sin permiso"}, status=403)

    b.delete()
    return JsonResponse({"ok": True, "deleted": bid})


# ===================================================================
# Utilidades menores / navegación
# ===================================================================









# ===================================================================
# STAFF: LISTA DE RESERVAS
# ===================================================================

@staff_member_required
def admin_reservas(request):
    """Reservaciones de las sucursales del usuario, con filtros por texto, fecha, estado y sucursal."""
    q = (request.GET.get("q") or "").strip()
    estado = request.GET.get("estado") or ""
    fecha = request.GET.get("fecha") or ""
    sucs = tenancy.sucursales_for_user(request.user).order_by("nombre")
    suc_id = request.GET.get("s") or ""

    qs = tenancy.scope_by_sucursal(
        Reserva.objects.select_related("cliente", "mesa", "sucursal"), request.user
    )
    if q:
        qs = qs.filter(Q(folio__icontains=q) | Q(cliente__nombre__icontains=q) | Q(nombre_contacto__icontains=q)
                       | Q(telefono_contacto__icontains=q))
    if estado in dict(Reserva.ESTADOS):
        qs = qs.filter(estado=estado)
    if fecha:
        try:
            qs = qs.filter(local_service_date=date.fromisoformat(fecha))
        except ValueError:
            pass
    if suc_id.isdigit():
        qs = qs.filter(sucursal_id=int(suc_id))
    total = qs.count()
    reservaciones = qs.order_by("-local_inicio", "-fecha")[:300]
    return render(request, "reservas/admin_reservas.html", {
        "reservaciones": reservaciones, "q": q, "estado": estado, "fecha": fecha, "suc_id": suc_id,
        "sucs": sucs, "estados": Reserva.ESTADOS, "total": total,
    })


# --- Compat: endpoint antiguo /staff/api/disponibilidad/?mesa_id=... ---
@staff_member_required
@require_GET
def staff_disponibilidad_json(request):
    """
    Proxy compatible con la URL antigua.
    Parámetros:
      - mesa_id (int) [requerido]
      - fecha=YYYY-MM-DD (opcional)
    Devuelve el mismo JSON que admin_disponibilidad_mesa.
    """
    mesa_id = request.GET.get("mesa_id")
    if not mesa_id:
        return JsonResponse({"ok": False, "error": "mesa_id requerido"}, status=400)
    try:
        mesa_id = int(mesa_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "mesa_id inválido"}, status=400)

    # Reutilizamos la lógica existente
    return admin_disponibilidad_mesa(request, mesa_id)







# --- API: actualizar mesa (JSON) ---

# ---- API: actualizar mesa (incluye posiciones del canvas) ----
@staff_member_required
def admin_api_mesa_update(request, mesa_id):
    mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id)
    if request.method == "POST":
        mesa.numero = request.POST.get("numero") or mesa.numero
        mesa.capacidad = request.POST.get("capacidad") or mesa.capacidad
        mesa.ubicacion = request.POST.get("ubicacion") or ""
        mesa.notas = request.POST.get("notas") or ""

        zona = request.POST.get("zona")
        if zona in {"interior", "terraza", "exterior"}:
            mesa.zona = zona

        mesa.save(update_fields=["numero", "capacidad", "ubicacion", "notas", "zona"])
        return JsonResponse({"ok": True})
    return JsonResponse({
        "ok": True,
        "mesa": {"id": mesa.id, "numero": mesa.numero, "capacidad": mesa.capacidad,
                 "zona": mesa.zona, "ubicacion": mesa.ubicacion or "", "notas": mesa.notas or ""},
    })


@staff_member_required
def admin_mesa_crear(request, sucursal_id):
    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)
    assert_user_can_manage_sucursal(request.user, sucursal)  # 🔒

    if request.method == "POST":
        try:
            numero = int(request.POST.get("numero") or 0)
        except (TypeError, ValueError):
            numero = 0

        capacidad = int(request.POST.get("capacidad") or 4)
        zona = request.POST.get("zona") or "interior"

        # Si el número no viene o ya existe, toma el siguiente consecutivo
        if numero <= 0 or Mesa.objects.filter(sucursal=sucursal, numero=numero).exists():
            ultimo = Mesa.objects.filter(sucursal=sucursal).order_by("-numero").first()
            numero = (ultimo.numero + 1) if ultimo else 1

        Mesa.objects.create(
            sucursal=sucursal,
            numero=numero,
            capacidad=capacidad,
            zona=zona,
            ubicacion=request.POST.get("ubicacion") or "",
            notas=request.POST.get("notas") or "",
        )

        messages.success(request, _("Mesa %(v0)s creada correctamente.") % {"v0": numero})
        return redirect("reservas:admin_mapa_sucursal", sucursal_id=sucursal.id)

    return render(request, "reservas/admin_mesa_crear.html", {"sucursal": sucursal})


# reservas/views.py








@login_required
@staff_member_required

def admin_sucursal_contenido(request, sucursal_id):
    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), id=sucursal_id)

    # (Opcional) Si quieres restringir a administradores asignados:
    # if not (request.user.is_superuser or request.user in sucursal.administradores.all()):
    #     messages.error(request, _("No tienes permiso para editar esta sucursal."))
    #     return redirect("reservas:admin_sucursales")

    if request.method == "POST":
        form = SucursalForm(request.POST, request.FILES, instance=sucursal)
        formset = SucursalFotoFormSet(request.POST, request.FILES, instance=sucursal, prefix="gal")
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, _("Contenido actualizado correctamente."))
            return redirect("reservas:admin_sucursal_contenido", sucursal_id=sucursal.id)
        else:
            messages.error(request, _("Revisa los campos marcados."))
    else:
        form = SucursalForm(instance=sucursal)
        formset = SucursalFotoFormSet(instance=sucursal, prefix="gal")

    return render(request, "reservas/admin_sucursal_contenido.html", {
        "sucursal": sucursal,
        "form": form,
        "formset": formset,
    })
 



@login_required
def admin_sucursales(request):
    hoy = timezone.localdate()
    sucursales = (
        tenancy.sucursales_for_user(request.user)
        .select_related("empresa")
        .annotate(
            n_mesas=Count("mesas", distinct=True),
            n_hoy=Count("reservas", filter=Q(reservas__local_service_date=hoy, reservas__estado__in=["PEND", "CONF"]), distinct=True),
        )
        .order_by("empresa__nombre", "nombre")
    )
    if not sucursales.exists():
        messages.info(request, _("No tienes sucursal asignada."))
    return render(request, "reservas/admin_sucursales.html", {"sucursales": sucursales})





@require_GET
def api_slots_sucursal(request, sucursal_id):
    """Horarios disponibles reales (mismas reglas que la asignación de mesa)."""
    from . import booking
    from .utils import booking_total_minutes

    sucursal = get_object_or_404(Sucursal.objects.publicas(), pk=sucursal_id)
    tz = sucursal.tz()
    fecha_raw = (request.GET.get("fecha") or request.GET.get("date") or "").strip()
    dia = parse_date(fecha_raw) if fecha_raw else None
    dia = dia or timezone.now().astimezone(tz).date()
    try:
        party = max(1, int((request.GET.get("party") or "2").strip()))
    except Exception:
        party = 2
    try:
        limit = max(1, int((request.GET.get("limit") or "12").strip()))
    except Exception:
        limit = 12

    slots = booking.slots_disponibles(sucursal, dia, party)
    hraw = (request.GET.get("hora") or request.GET.get("time") or "").strip()
    if hraw:
        try:
            ancla = timezone.make_aware(datetime.combine(dia, datetime.strptime(hraw, "%H:%M").time()), tz)
            slots = [s for s in slots if s >= ancla] or slots
        except ValueError:
            pass
    slots = slots[:limit]
    ref = slots[0] if slots else timezone.make_aware(datetime.combine(dia, datetime.min.time()), tz)
    return JsonResponse({
        "sucursal": sucursal.id,
        "fecha": dia.isoformat(),
        "party": party,
        "slots": [{"label": s.astimezone(tz).strftime("%H:%M"), "value": s.astimezone(tz).strftime("%H:%M")} for s in slots],
        "duracion_min": booking_total_minutes(ref, party, sucursal),
    })





@staff_member_required
def admin_disponibilidad_mesa(request, mesa_id):
    """
    Devuelve (solo staff) los slots disponibles de una mesa en un día.
    GET: ?fecha=YYYY-MM-DD  (default hoy local)
         ?party=2 (opcional)
    """
    from .utils import booking_total_minutes  # <-- helper de duración dinámica

    mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id)

    # fecha
    fecha_q = request.GET.get("fecha", "")
    try:
        if fecha_q:
            y, m, d = [int(x) for x in fecha_q.split("-")]
            d_dia = date(y, m, d)
        else:
            d_dia = timezone.localdate()
    except Exception:
        d_dia = timezone.localdate()

    # party
    try:
        party = int((request.GET.get("party") or "2").strip())
    except Exception:
        party = 2

    # slots disponibles considerando duración dinámica por party y hora
    slots_dt = _slots_disponibles(mesa, d_dia, party=party)

    # duración “base” que mostraremos junto con la respuesta
    tz = timezone.get_current_timezone()
    totalmin = booking_total_minutes(
        timezone.make_aware(datetime(d_dia.year, d_dia.month, d_dia.day, 0, 0), tz),
        party
    )

    # formateo HH:MM local
    slots_str = [s.astimezone(tz).strftime("%H:%M") for s in slots_dt]

    return JsonResponse({
        "mesa": mesa.id,
        "fecha": d_dia.isoformat(),
        "duracion_min": totalmin,
        "slots": slots_str,
    })


@require_POST
@staff_member_required
@transaction.atomic
def admin_finalizar_reserva(request, reserva_id):
    """
    Finaliza una reserva (libera mesa). Solo si ya se confirmó la llegada.
    Acepta POST opcional dt="YYYY-MM-DD HH:MM" para fijar la hora de liberación.
    """
    r = get_object_or_404(tenancy.scope_by_sucursal(Reserva.objects.select_for_update(), request.user), pk=reserva_id)

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        return HttpResponseForbidden("No tienes permiso para operar esta reserva.")

    # Regla: solo si ya hubo check-in
    if not getattr(r, "llego", False):
        messages.error(request, _("Primero confirma la llegada para poder finalizar la reserva."))
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    # Hora opcional
    tz = timezone.get_current_timezone()
    dt_txt = (request.POST.get("dt") or "").strip()
    dt = None
    if dt_txt:
        try:
            dt = timezone.make_aware(datetime.strptime(dt_txt, "%Y-%m-%d %H:%M"), tz)
        except Exception:
            dt = None

    r.marcar_liberada(dt or timezone.now())

    hora_local = timezone.localtime(r.liberada_en).strftime("%H:%M")
    messages.success(request, _("Reservación finalizada. Mesa liberada desde las %(v0)s.") % {"v0": hora_local})

    # Redirección
    next_param = (request.POST.get("next") or request.GET.get("next") or "").lower()
    if next_param == "mesa":
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)
    return redirect("reservas:admin_mapa_sucursal", sucursal_id=r.mesa.sucursal_id)
from django.contrib.auth.decorators import login_required
from reservas.models import Reserva, Cliente






def _staff_puede_gestionar_reserva(user, reserva):
    """Solo recepción/gerencia con acceso a la sucursal de la reserva (ver tenancy.py y areas.py)."""
    from . import areas
    return (bool(user.is_staff) and tenancy.user_can_manage_sucursal(user, reserva.sucursal)
            and bool(areas.areas_de(user) & {areas.RECEPCION, areas.SUCURSAL}))

@login_required
def admin_reasignar_reserva(request, reserva_id):
    reserva = get_object_or_404(tenancy.scope_by_sucursal(Reserva.objects.all(), request.user), pk=reserva_id)
    if not _staff_puede_gestionar_reserva(request.user, reserva):
        messages.error(request, _("No tienes permisos para gestionar esta reserva."))
        return redirect("/")

    if request.method == "POST":
        mesa_id = request.POST.get("mesa_id")
        forzar = bool(request.POST.get("forzar"))
        nueva_mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id, sucursal=reserva.mesa.sucursal)

        ok, motivo = mover_reserva(reserva, nueva_mesa, forzar=forzar)
        if ok:
            messages.success(request, motivo)
        else:
            messages.error(request, motivo)

        # AJUSTA este reverse al nombre de tu panel de mesas
        try:
            return redirect(reverse("reservas:admin_mapa_sucursal", args=[reserva.mesa.sucursal_id]))
        except Exception:
            return redirect("/")

    # GET: mostrar candidatas
    forzar = bool(request.GET.get("forzar"))
    candidatas = mesas_disponibles_para_reserva(reserva, forzar=forzar)
    contexto = {
        "reserva": reserva,
        "candidatas": candidatas,
        "forzar": forzar,
    }
    return render(request, "reservas/admin_reasignar_reserva.html", contexto)














# views.py (filtro por sucursal del staff)






# views.py






# reservas/views.py




def healthz(request):
    return JsonResponse({"ok": True})

def readyz(request):
    status = {"db": False, "cache": False}
    # DB
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1;")
        status["db"] = True
    except Exception:
        status["db"] = False
    # Cache
    try:
        cache.set("readyz_ping", "1", 5)
        status["cache"] = cache.get("readyz_ping") == "1"
    except Exception:
        status["cache"] = False

    ok = all(status.values())
    return JsonResponse({"ok": ok, **status}, status=200 if ok else 500)







@staff_member_required
@require_GET
def staff_api_disponibilidad(request):
    """
    Shim: redirige a la API pública /api/sucursal/<id>/slots/ manteniendo querystring.
    Evita 400 del endpoint staff mientras implementas la lógica propia.
    """
    suc_id = request.GET.get("sucursal_id")
    # Si no viene en el query, intenta tomar la del PerfilAdmin:
    if not suc_id and hasattr(request.user, "perfiladmin") and request.user.perfiladmin.sucursal_asignada_id:
        suc_id = str(request.user.perfiladmin.sucursal_asignada_id)
    if not suc_id:
        return HttpResponseRedirect(reverse("reservas:api_slots_sucursal", args=[0]))  # caerá en 404 controlado

    base = reverse("reservas:api_slots_sucursal", args=[int(suc_id)])
    qs = request.META.get("QUERY_STRING", "")
    url = f"{base}?{qs}" if qs else base
    return HttpResponseRedirect(url)



def _puede_ver_sucursal(user, sucursal):
    return bool(user.is_authenticated and user.is_staff and tenancy.user_can_manage_sucursal(user, sucursal))



@login_required
@require_POST
def admin_api_mesa_setpos(request, mesa_id):
    """
    Guarda la posición (pos_x, pos_y) de una mesa en px relativos al canvas.
    Espera POST con x, y (ints).
    """
    mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id)
    if not _puede_ver_sucursal(request.user, mesa.sucursal):
        return HttpResponseForbidden("Sin permiso")

    try:
        x = int(request.POST.get("x", "0"))
        y = int(request.POST.get("y", "0"))
    except ValueError:
        return JsonResponse({"ok": False, "error": "coords_invalidas"}, status=400)

    # Opcional: límites mínimos
    if x < 0: x = 0
    if y < 0: y = 0

    mesa.pos_x = x
    mesa.pos_y = y
    mesa.save(update_fields=["pos_x", "pos_y"])
    return JsonResponse({"ok": True, "x": x, "y": y})





@login_required
@require_POST
def admin_api_mesa_pos(request, mesa_id):
    mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id)
    # misma regla de visibilidad que usas en el resto:
    if not _puede_ver_sucursal(request.user, mesa.sucursal):
        return HttpResponseForbidden("Sin permiso.")

    try:
        data = json.loads(request.body.decode("utf-8"))
        pos_x = float(data.get("pos_x"))
        pos_y = float(data.get("pos_y"))
    except Exception:
        return HttpResponseBadRequest("payload inválido")

    # acotar a 0..100
    pos_x = max(0.0, min(100.0, pos_x))
    pos_y = max(0.0, min(100.0, pos_y))

    mesa.pos_x = pos_x
    mesa.pos_y = pos_y
    mesa.save(update_fields=["pos_x", "pos_y"])

    return JsonResponse({"ok": True, "pos_x": float(mesa.pos_x), "pos_y": float(mesa.pos_y)})



@login_required
@require_POST
def admin_api_recepcion_pos(request, sucursal_id):
    # permisos básicos: que el usuario pueda ver/gestionar esta sucursal
    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)

    # (opcional) si tienes helper de visibilidad, úsalo aquí
    # if not Sucursal.objects.visibles_para(request.user).filter(pk=sucursal_id).exists():
    #     return HttpResponseForbidden("No autorizado")

    try:
        data = json.loads(request.body.decode("utf-8"))
        x = float(data.get("pos_x", 0))
        y = float(data.get("pos_y", 0))
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    # clamp 0..100 y redondeo a 2 decimales
    x = max(0.0, min(100.0, round(x, 2)))
    y = max(0.0, min(100.0, round(y, 2)))

    sucursal.recepcion_x = int(round(x))
    sucursal.recepcion_y = int(round(y))
    sucursal.save(update_fields=["recepcion_x", "recepcion_y"])

    return JsonResponse({"ok": True, "x": sucursal.recepcion_x, "y": sucursal.recepcion_y})





# --- Nueva vista para editar una mesa desde el mapa ---
from django import forms

@staff_member_required
def admin_mesa_editar(request, mesa_id):
    """
    Formulario para editar una mesa desde el mapa interactivo.
    Si se guarda correctamente, redirige de nuevo al mapa de la sucursal.
    """
    mesa = get_object_or_404(tenancy.scope_by_sucursal(Mesa.objects.all(), request.user), pk=mesa_id)
    sucursal = mesa.sucursal

    # Verifica permiso de visibilidad
    if not _puede_ver_sucursal(request.user, sucursal):
        return HttpResponseForbidden("No tienes permiso para editar mesas de esta sucursal.")

    class MesaEditForm(forms.ModelForm):
        class Meta:
            model = Mesa
            fields = ["numero", "capacidad", "zona", "ubicacion", "notas", "bloqueada"]
            widgets = {
                "zona": forms.Select(choices=[
                    ("interior", "Interior"),
                    ("terraza", "Terraza"),
                    ("exterior", "Exterior"),
                ]),
                "notas": forms.Textarea(attrs={"rows": 2}),
            }

    if request.method == "POST":
        form = MesaEditForm(request.POST, instance=mesa)
        if form.is_valid():
            form.save()
            messages.success(request, _("✅ Mesa actualizada correctamente."))
            return redirect("reservas:admin_mapa_sucursal", sucursal_id=sucursal.id)
        else:
            messages.error(request, _("Revisa los campos del formulario."))
    else:
        form = MesaEditForm(instance=mesa)

    ctx = {
        "mesa": mesa,
        "sucursal": sucursal,
        "form": form,
    }
    return render(request, "reservas/admin_mesa_editar.html", ctx)




@staff_member_required
def admin_bloqueos(request, sucursal_id):
    sucursal = get_object_or_404(tenancy.sucursales_for_user(request.user), pk=sucursal_id)
    if not _puede_ver_sucursal(request.user, sucursal):
        return HttpResponseForbidden("Sin permiso sobre la sucursal.")
    # Traemos mesas para filtros
    mesas = Mesa.objects.filter(sucursal=sucursal).order_by("numero", "id")
    return render(request, "reservas/admin_bloqueos.html", {
        "sucursal": sucursal,
        "mesas": mesas,
    })



# reservas/views.py















# ===============================
#   REGISTER
# ===============================





# tu helper existente
# _tz_for_sucursal(sucursal)  -> devuelve ZoneInfo de la sucursal

@login_required
def reserva_detalle(request, pk):
    """Enlace antiguo: lleva a la página de la reserva SOLO a su comensal o al personal con acceso a esa sucursal."""
    reserva = get_object_or_404(Reserva.objects.select_related("cliente", "sucursal"), pk=pk)
    es_suya = bool(reserva.cliente_id and getattr(reserva.cliente, "user_id", None) == request.user.pk)
    if not (es_suya or _staff_puede_gestionar_reserva(request.user, reserva)):
        raise Http404()
    return redirect("reservas:reserva_publica", reserva.token)


def _contacto_from_reserva(reserva):
    """
    Devuelve un dict con nombre/email/tel usando fallbacks:
    Reserva -> Cliente -> User.
    """
    cliente = getattr(reserva, "cliente", None)
    user = getattr(cliente, "user", None)

    nombre = (
        (reserva.nombre_contacto or "").strip()
        or (getattr(cliente, "nombre", "") or "").strip()
        or (
            (" ".join([
                (getattr(user, "first_name", "") or "").strip(),
                (getattr(user, "last_name", "") or "").strip()
            ])).strip() if user else ""
        )
        or (getattr(user, "username", "") if user else "")
        or ""
    )
    email = (
        (reserva.email_contacto or "").strip()
        or (getattr(cliente, "email", "") or "").strip()
        or (getattr(user, "email", "") if user else "")
        or ""
    )
    tel = (
        (reserva.telefono_contacto or "").strip()
        or (getattr(cliente, "telefono", "") or "").strip()
        or ""
    )
    return {"contacto_nombre": nombre, "contacto_email": email, "contacto_tel": tel}




# ⬇️ AJUSTA estos imports a tus modelos reales si difieren





