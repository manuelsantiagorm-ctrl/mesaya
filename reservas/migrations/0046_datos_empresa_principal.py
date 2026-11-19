"""
Migración de datos a multi-empresa:
- Crea la empresa "principal" con todo lo existente (si hay datos).
- Asigna sucursales, catálogo y alcances de país a esa empresa.
- Convierte a los dueños de cadena (permiso manage_branches) en administradores de la empresa.
- Rellena sucursal y token en reservas viejas.
"""
import secrets

from django.db import migrations
from django.db.models import Q


def forwards(apps, schema_editor):
    Empresa = apps.get_model("reservas", "Empresa")
    Miembro = apps.get_model("reservas", "MiembroEmpresa")
    Sucursal = apps.get_model("reservas", "Sucursal")
    Reserva = apps.get_model("reservas", "Reserva")
    CatalogCategory = apps.get_model("reservas", "CatalogCategory")
    CatalogItem = apps.get_model("reservas", "CatalogItem")
    CountryAdminScope = apps.get_model("reservas", "CountryAdminScope")
    ChainOwnerPaisRole = apps.get_model("reservas", "ChainOwnerPaisRole")
    User = apps.get_model("auth", "User")
    Permission = apps.get_model("auth", "Permission")

    # Reservas viejas sin sucursal
    for r in Reserva.objects.filter(sucursal__isnull=True).select_related("mesa"):
        r.sucursal_id = r.mesa.sucursal_id
        r.save(update_fields=["sucursal"])

    hay_datos = Sucursal.objects.exists() or CatalogCategory.objects.exists()
    if hay_datos:
        empresa, _ = Empresa.objects.get_or_create(
            slug="principal", defaults={"nombre": "Mi Restaurante", "activa": True}
        )
        Sucursal.objects.filter(empresa__isnull=True).update(empresa=empresa)
        CatalogCategory.objects.filter(empresa__isnull=True).update(empresa=empresa)
        for it in CatalogItem.objects.filter(empresa__isnull=True).select_related("categoria"):
            it.empresa_id = it.categoria.empresa_id or empresa.id
            it.save(update_fields=["empresa"])
        CountryAdminScope.objects.filter(empresa__isnull=True).update(empresa=empresa)
        ChainOwnerPaisRole.objects.filter(empresa__isnull=True).update(empresa=empresa)

        # Dueños de cadena (permiso manage_branches directo o por grupo) -> admins de la empresa
        perm = Permission.objects.filter(codename="manage_branches", content_type__app_label="reservas").first()
        if perm:
            owners = User.objects.filter(
                Q(user_permissions=perm) | Q(groups__permissions=perm), is_superuser=False
            ).distinct()
            for u in owners:
                Miembro.objects.get_or_create(empresa=empresa, user=u, defaults={"rol": "admin"})
        # Staff con alcance de país o sucursal -> miembros
        staff_ids = set(CountryAdminScope.objects.values_list("user_id", flat=True))
        staff_ids |= set(ChainOwnerPaisRole.objects.values_list("user_id", flat=True))
        staff_ids |= set(Sucursal.administradores.through.objects.values_list("user_id", flat=True))
        for uid in staff_ids:
            Miembro.objects.get_or_create(empresa=empresa, user_id=uid, defaults={"rol": "staff"})

    for r in Reserva.objects.filter(token__isnull=True).only("id"):
        Reserva.objects.filter(pk=r.pk).update(token=secrets.token_urlsafe(24))


class Migration(migrations.Migration):
    dependencies = [
        ("reservas", "0045_multiempresa"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
