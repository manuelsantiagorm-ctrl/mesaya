# reservas/permissions.py
"""Compat: delega en reservas.tenancy (multi-empresa)."""
from django.http import Http404

from . import tenancy


def user_country_ids(user):
    """IDs de países que el usuario puede gestionar. None = sin restricción (superusuario)."""
    return tenancy.allowed_country_ids(user)


def user_can_manage_sucursal(user, sucursal):
    return tenancy.user_can_manage_sucursal(user, sucursal)


def assert_user_can_manage_sucursal(user, sucursal):
    """404 si el usuario no tiene permiso sobre la sucursal (no revela que existe)."""
    if not user_can_manage_sucursal(user, sucursal):
        raise Http404("Sucursal no encontrada o sin permisos.")
