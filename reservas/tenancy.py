# reservas/tenancy.py
"""
Multi-empresa: UNA sola fuente de verdad para saber qué puede ver cada usuario.

Reglas
- Superusuario = operador de la plataforma. NO ve datos de ningún restaurante (sucursales, reservas,
  clientes, conversaciones). Solo entra a UNA empresa con un acceso de soporte temporal y auditado
  (AccesoSoporte), que el middleware coloca en user._soporte_empresa_id.
- Dueño/Administrador de una empresa (MiembroEmpresa OWNER/ADMIN): todas las sucursales de SU empresa.
- Admin de país (CountryAdminScope / ChainOwnerPaisRole): sucursales de ese país DENTRO de su empresa.
- Admin de sucursal (Sucursal.administradores o PerfilAdmin.sucursal_asignada): solo esas sucursales.
- Nadie ve sucursales, reservas, mesas u órdenes de otra empresa.
"""
from __future__ import annotations

from django.apps import apps
from django.db.models import Q


def _m(name):
    return apps.get_model("reservas", name)


def is_auth(user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False) and user.is_active)


def is_platform_admin(user) -> bool:
    return is_auth(user) and user.is_superuser


def soporte_empresa_id(user):
    """Empresa a la que el operador tiene un acceso de soporte vigente (o None)."""
    if not is_platform_admin(user):
        return None
    return getattr(user, "_soporte_empresa_id", None)


def empresas_admin_ids(user) -> list[int]:
    """Empresas donde el usuario es dueño o administrador (incluye la empresa en modo soporte)."""
    if not is_auth(user):
        return []
    if user.is_superuser:  # el operador nunca es miembro de un restaurante: solo modo soporte
        sop = soporte_empresa_id(user)
        return [sop] if sop else []
    Miembro = _m("MiembroEmpresa")
    ids = list(
        Miembro.objects.filter(
            user=user, activo=True, rol__in=[Miembro.OWNER, Miembro.ADMIN], empresa__activa=True
        ).values_list("empresa_id", flat=True)
    )
    sop = soporte_empresa_id(user)
    if sop and sop not in ids:
        ids.append(sop)
    return ids


def is_chain_owner(user) -> bool:
    """Dueño/administrador de al menos una empresa. Ser superusuario NO basta."""
    return bool(empresas_admin_ids(user))


def _sucursal_q(user) -> Q:
    q = Q(empresa_id__in=empresas_admin_ids(user)) | Q(administradores=user)

    perfil = getattr(user, "perfiladmin", None)
    try:
        suc_id = perfil.sucursal_asignada_id if perfil else None
    except Exception:
        suc_id = None
    if suc_id:
        q |= Q(pk=suc_id)

    for model_name, active_field in (("CountryAdminScope", "is_active"), ("ChainOwnerPaisRole", "activo")):
        Model = _m(model_name)
        for empresa_id, pais_id in Model.objects.filter(user=user, **{active_field: True}).values_list(
            "empresa_id", "pais_id"
        ):
            if empresa_id:  # sin empresa no hay alcance (evita fugas entre empresas)
                q |= Q(empresa_id=empresa_id, pais_id=pais_id)
    return q


def sucursales_for_user(user, base=None):
    """QuerySet de sucursales que el usuario puede administrar."""
    Sucursal = _m("Sucursal")
    base = Sucursal.objects.all() if base is None else base
    if not is_auth(user):
        return base.none()
    if user.is_superuser:
        sop = soporte_empresa_id(user)
        return base.filter(empresa_id=sop, empresa__activa=True) if sop else base.none()
    ids = Sucursal.objects.filter(_sucursal_q(user)).values("pk")
    return base.filter(pk__in=ids, empresa__activa=True)


def sucursal_ids_for_user(user):
    """Lista de IDs de sucursales visibles (nunca 'todas')."""
    return list(sucursales_for_user(user).values_list("pk", flat=True))


def user_can_manage_sucursal(user, sucursal) -> bool:
    if not is_auth(user) or sucursal is None:
        return False
    return sucursales_for_user(user).filter(pk=sucursal.pk).exists()


def user_empresa_ids(user):
    """Empresas a las que pertenece el usuario (el operador solo la de su acceso de soporte)."""
    if not is_auth(user):
        return []
    if user.is_superuser:
        sop = soporte_empresa_id(user)
        return [sop] if sop else []
    Miembro = _m("MiembroEmpresa")
    ids = set(
        Miembro.objects.filter(user=user, activo=True, empresa__activa=True).values_list("empresa_id", flat=True)
    )
    ids.update(
        sucursales_for_user(user).exclude(empresa_id=None).values_list("empresa_id", flat=True)
    )
    if soporte_empresa_id(user):
        ids.add(soporte_empresa_id(user))
    return sorted(ids)


def empresas_for_user(user):
    Empresa = _m("Empresa")
    return Empresa.objects.filter(pk__in=user_empresa_ids(user))


def empresa_de_usuario(user):
    """La empresa 'principal' del usuario (la primera donde es admin, o la primera a la que pertenece)."""
    Empresa = _m("Empresa")
    admin_ids = empresas_admin_ids(user)
    if admin_ids:
        return Empresa.objects.filter(pk__in=admin_ids).order_by("pk").first()
    return empresas_for_user(user).order_by("pk").first() if is_auth(user) else None


def is_empresa_admin(user, empresa) -> bool:
    if empresa is None or not is_auth(user):
        return False
    return empresa.pk in empresas_admin_ids(user)


def scope_by_sucursal(qs, user, field: str = "sucursal"):
    """Filtra cualquier QuerySet con FK a Sucursal (mesas, reservas, órdenes, bloqueos...)."""
    if not is_auth(user):
        return qs.none()
    return qs.filter(**{f"{field}__in": sucursales_for_user(user).values("pk")})


def _has_field(model, name) -> bool:
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def scope_queryset(qs, user):
    """
    Filtro genérico por alcance del usuario, según el modelo:
    Sucursal -> sus sucursales; modelos con 'sucursal' -> por sucursal;
    con 'empresa' -> sus empresas; con 'pais' -> países de sus sucursales.
    """
    if not is_auth(user):
        return qs.none()
    model = qs.model
    if model is _m("Sucursal"):
        return sucursales_for_user(user, qs)
    if model is _m("Empresa"):
        return qs.filter(pk__in=user_empresa_ids(user) or [])
    if _has_field(model, "sucursal"):
        return scope_by_sucursal(qs, user, "sucursal")
    if _has_field(model, "empresa"):
        return qs.filter(empresa_id__in=user_empresa_ids(user) or [])
    if model is _m("Pais"):
        return qs.filter(pk__in=sucursales_for_user(user).values("pais_id"))
    if _has_field(model, "pais"):
        return qs.filter(pais_id__in=sucursales_for_user(user).values("pais_id"))
    return qs.none()


def allowed_country_ids(user):
    """Países que el usuario puede usar: dueños/administradores, todos (para abrir sucursales nuevas);
    los demás, los países de sus sucursales visibles."""
    if empresas_admin_ids(user):
        return list(_m("Pais").objects.values_list("pk", flat=True))
    return list(sucursales_for_user(user).exclude(pais=None).values_list("pais_id", flat=True).distinct())
