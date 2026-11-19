from django.conf import settings
from allauth.socialaccount.models import SocialApp
from .models import Pais


def google_maps(request):
    return {"GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", "")}


def social_flags(request):
    """Evita error DoesNotExist en signup.html si no hay app de Google configurada."""
    has_google = False

    # 1️⃣ Si está configurado por settings (via SOCIALACCOUNT_PROVIDERS)
    try:
        app_cfg = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get("google", {}).get("APP", {})
        if app_cfg.get("client_id") and app_cfg.get("secret"):
            has_google = True
    except Exception:
        pass

    # 2️⃣ O si existe una SocialApp en BD asociada al SITE_ID
    if not has_google:
        try:
            qs = SocialApp.objects.filter(provider="google")
            if getattr(settings, "SITE_ID", None):
                qs = qs.filter(sites__id=settings.SITE_ID)
            has_google = qs.exists()
        except Exception:
            pass

    return {"HAS_GOOGLE_LOGIN": has_google}

def countries_context(request):
    return {
        "all_countries": Pais.objects.order_by("nombre").only("id","nombre","iso2")
    }

def branding(request):
    """Marca blanca disponible en todas las plantillas como {{ brand }}."""
    from .branding import brand_for_empresa
    from . import tenancy
    empresa = getattr(request, "empresa", None)
    user = getattr(request, "user", None)
    return {
        "brand": brand_for_empresa(empresa),
        "es_dueno": bool(user and tenancy.is_chain_owner(user)),
        "es_superadmin": bool(user and tenancy.is_platform_admin(user)),
        "SITE_URL": settings.SITE_URL,
        "google_login": _google_activo(),
    }


def _google_activo():
    """True si hay credenciales de Google configuradas (evita error 500 en login/registro si no)."""
    from django.core.cache import cache
    v = cache.get("google_login_activo")
    if v is None:
        try:
            from allauth.socialaccount.models import SocialApp
            v = SocialApp.objects.filter(provider="google").exists()
        except Exception:
            v = False
        cache.set("google_login_activo", v, 300)
    return v



def areas_trabajo(request):
    """Áreas del usuario para el menú (cada quien ve solo lo suyo)."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {"menu_areas": [], "mis_areas": set()}
    from . import areas
    return {"menu_areas": areas.menu_de(user), "mis_areas": areas.areas_de(user)}
