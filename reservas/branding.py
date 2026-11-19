# reservas/branding.py
"""Marca blanca: nombre, logo y colores de la empresa que se está mostrando."""
from django.conf import settings


def brand_for_empresa(empresa):
    if empresa is None:
        return {
            "nombre": getattr(settings, "PLATFORM_NAME", "Reservas"),
            "logo_url": "",
            "plataforma": True,
            "color_primario": "#E4572E",
            "color_secundario": "#1E1B18",
            "email": "",
            "telefono": "",
            "slug": "",
            "empresa": None,
        }
    return {
        "nombre": empresa.nombre,
        "logo_url": empresa.logo.url if empresa.logo else "",
        "color_primario": empresa.color_primario or "#1F6FEB",
        "color_secundario": empresa.color_secundario or "#0B1F3A",
        "email": empresa.email_contacto,
        "telefono": empresa.telefono,
        "slug": empresa.slug,
        "empresa": empresa,
    }
