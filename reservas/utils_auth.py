# reservas/utils_auth.py
from typing import Optional
from django.db.models import QuerySet
from django.contrib.auth.models import AbstractBaseUser

from .models import Pais, Sucursal

# Si tu modelo de alcance País-Usuario se llama distinto, ajusta el import:
# p. ej. from .models import CountryAdminScope
try:
    from .models import CountryAdminScope
except Exception:
    CountryAdminScope = None  # para evitar fallos si aún no existe


def user_allowed_countries(user: AbstractBaseUser) -> QuerySet[Pais]:
    """
    Devuelve un queryset de Pais que el usuario puede administrar como Country Admin.
    - Anónimo: ninguno
    - Superuser: todos
    - Country admin: los que tenga en CountryAdminScope
    - Otros: ninguno
    """
    from . import tenancy
    ids = tenancy.allowed_country_ids(user)
    if ids is None:
        return Pais.objects.all()
    return Pais.objects.filter(id__in=ids)


def scope_sucursales_for(request, base_qs: Optional[QuerySet[Sucursal]] = None) -> QuerySet[Sucursal]:
    """
    Aplica el alcance por usuario a un queryset de Sucursal.
    - Superuser: sin filtro
    - Country admin: sólo sucursales de sus países
    - Branch admin (staff sin países): sólo sucursales donde es administrador
    - Usuario sin privilegios: none()
    """
    from . import tenancy
    if base_qs is None:
        base_qs = Sucursal.objects.all()
    return tenancy.sucursales_for_user(getattr(request, "user", None), base_qs)
