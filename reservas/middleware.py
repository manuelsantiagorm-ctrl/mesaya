from django.shortcuts import redirect
from django.urls import reverse, resolve, NoReverseMatch

# --- IMPORTANTE: si el modelo TOTP no está, no rompemos ---
try:
    from django_otp.plugins.otp_totp.models import TOTPDevice
except Exception:
    TOTPDevice = None


# Solo deshabilita caché en páginas de auth (accounts/ y account/)
class NoCacheForAuthPagesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        p = request.path
        if p.startswith("/accounts/") or p.startswith("/account/"):
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response


TWO_FACTOR_NAMESPACE = "two_factor"

# Vistas de 2FA que NO deben ser interceptadas por el middleware de enforcement
EXEMPT_URL_NAMES = {
    f"{TWO_FACTOR_NAMESPACE}:login",
    f"{TWO_FACTOR_NAMESPACE}:setup",
    f"{TWO_FACTOR_NAMESPACE}:qr",
    f"{TWO_FACTOR_NAMESPACE}:setup_complete",
    f"{TWO_FACTOR_NAMESPACE}:backup_tokens",
    f"{TWO_FACTOR_NAMESPACE}:phone_setup",
    f"{TWO_FACTOR_NAMESPACE}:token",
    f"{TWO_FACTOR_NAMESPACE}:disable",
    f"{TWO_FACTOR_NAMESPACE}:profile",
}

# Prefijos que no interceptamos (estáticos, media, i18n, etc.)
EXEMPT_PREFIXES = (
    "/static/",
    "/media/",
    "/i18n/",
    "/jsi18n/",
    "/accounts/",       # allauth
    "/account/",        # two_factor hotfix montado en /account/
    "/admin/login",     # login admin
)


class StaffOTPRequiredMiddleware:
    """
    Exige OTP para usuarios staff:
      - Si ya está verificado -> deja pasar
      - Si NO está verificado:
          * Si tiene TOTP confirmado -> redirige a login OTP
          * Si NO tiene TOTP -> redirige a setup
    Evita loops al no interceptar rutas de auth/2FA.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # No interceptar rutas exentas
        for prefix in EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            # Solo forzamos OTP a staff autenticado
            return self.get_response(request)

        # Si la ruta actual pertenece al namespace de 2FA, no redirigir
        try:
            match = resolve(path)
            url_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        except Exception:
            match = None
            url_name = None

        if url_name in EXEMPT_URL_NAMES or (match and match.namespace == TWO_FACTOR_NAMESPACE):
            return self.get_response(request)

        # ¿Está verificado por OTP?
        try:
            is_verified = user.is_verified()
        except Exception:
            # Fallback con request.otp_device que setea django-otp
            is_verified = getattr(request, "otp_device", None) is not None

        if is_verified:
            return self.get_response(request)

        # NO verificado: decidir si enviar a setup o a login OTP
        setup_url = _safe_reverse(f"{TWO_FACTOR_NAMESPACE}:setup", fallback="/account/two_factor/setup/")
        login_otp_url = _safe_reverse(f"{TWO_FACTOR_NAMESPACE}:login", fallback="/account/login/")

        has_confirmed_device = False
        if TOTPDevice is not None:
            try:
                has_confirmed_device = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
            except Exception:
                has_confirmed_device = False

        return redirect(login_otp_url if has_confirmed_device else setup_url)


def _safe_reverse(name: str, fallback: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return fallback



class RedirectSignupMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.path.startswith("/auth/signup"):
            return redirect("accounts:signup_start")
        return self.get_response(request)


class RedirectNonStaffFromStaffURLs:
    """Si un usuario NO es staff y entra a /staff/, lo mandamos a seleccionar_sucursal."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ''
        if path.startswith('/staff/') and request.user.is_authenticated and not request.user.is_staff:
            return redirect(reverse('reservas:seleccionar_sucursal'))
        return self.get_response(request)


# ==========================================================
# Multi-empresa: determina la empresa (marca) de la petición
# ==========================================================
class EmpresaMiddleware:
    """
    request.empresa se resuelve en este orden:
      1) Dominio propio de la empresa (Empresa.dominio == host)
      2) ?e=<slug> en la URL (se guarda en la sesión; ?e=0 la limpia)
      3) La empresa guardada en la sesión
      4) Personal con sesión: su empresa principal
    """
    SESSION_KEY = "empresa_slug"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        sop = getattr(request, "soporte", None)
        request.empresa = sop.empresa if sop else self._resolve(request)
        return self.get_response(request)

    def _resolve(self, request):
        from .models import Empresa
        from . import tenancy

        host = (request.get_host() or "").split(":")[0].lower()
        if host:
            emp = Empresa.objects.filter(dominio=host, activa=True).first()
            if emp:
                return emp

        slug = request.GET.get("e")
        if slug is not None:
            if slug in ("", "0"):
                request.session.pop(self.SESSION_KEY, None)
            else:
                emp = Empresa.objects.filter(slug=slug, activa=True).first()
                if emp:
                    request.session[self.SESSION_KEY] = emp.slug
                    return emp

        slug = request.session.get(self.SESSION_KEY) if hasattr(request, "session") else None
        if slug:
            emp = Empresa.objects.filter(slug=slug, activa=True).first()
            if emp:
                return emp

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff:
            return tenancy.empresa_de_usuario(user)
        return None



class SoporteMiddleware:
    """
    Modo soporte del operador de la plataforma: si tiene un acceso vigente (AccesoSoporte),
    marca al usuario con esa empresa durante la petición. Debe ir ANTES de EmpresaMiddleware.
    """
    SESSION_KEY = "acceso_soporte_id"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.soporte = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser:
            acc_id = request.session.get(self.SESSION_KEY)
            if acc_id:
                from .models import AccesoSoporte
                acc = AccesoSoporte.objects.select_related("empresa").filter(pk=acc_id, user=user).first()
                if acc and acc.vigente:
                    user._soporte_empresa_id = acc.empresa_id
                    request.soporte = acc
                else:
                    request.session.pop(self.SESSION_KEY, None)
        return self.get_response(request)



class AreaMiddleware:
    """
    Cada quien solo entra a su área (ver reservas/areas.py). Va después de EmpresaMiddleware.
    Recepción no entra a cocina, cocina solo ve órdenes, el mesero solo sus mesas, etc.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return None
        match = getattr(request, "resolver_match", None)
        if not match or match.namespace != "reservas":
            return None
        from . import areas
        name = match.url_name
        if name in areas.LIBRES:
            return None
        mis = areas.areas_de(user)
        permitidas = areas.RUTAS.get(name)
        if not mis and not user.is_staff:
            return None  # comensal: la vista lo manda a iniciar sesión / le niega como siempre
        if permitidas is not None and (mis & permitidas):
            return None
        return self._negar(request, user)

    @staticmethod
    def _negar(request, user):
        from django.contrib import messages
        from django.http import HttpResponseForbidden
        from django.shortcuts import redirect
        from django.utils.translation import gettext as _
        es_api = request.method != "GET" or "/api/" in request.path or \
            "application/json" in request.headers.get("Accept", "") or \
            request.headers.get("x-requested-with") == "XMLHttpRequest"
        if es_api:
            return HttpResponseForbidden(_("Esta área no es parte de tu puesto."))
        messages.warning(request, _("Esa pantalla no es parte de tu puesto. Te dejamos en tu área."))
        return redirect("reservas:staff_inicio")
