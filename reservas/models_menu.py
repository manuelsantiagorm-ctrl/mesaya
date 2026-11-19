# reservas/models_menu.py
from django.db import models
from django.utils.translation import gettext_lazy as _

class CatalogCategory(models.Model):
    empresa = models.ForeignKey(
        "reservas.Empresa", on_delete=models.CASCADE, related_name="catalogo_categorias", null=True, blank=True
    )
    nombre = models.CharField(_("Nombre"), max_length=120)
    orden = models.PositiveIntegerField(_("Orden"), default=0)
    activo = models.BooleanField(_("Activo"), default=True)

    class Meta:
        db_table = "catalog_category"
        ordering = ["orden", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nombre"], name="uniq_catcat_nombre_por_empresa"),
        ]
        verbose_name = _("Categoría de menú")
        verbose_name_plural = _("Categorías de menú")

    def __str__(self):
        return self.nombre


class CatalogItem(models.Model):
    class AreaImpresion(models.TextChoices):
        COCINA = "cocina", _("Cocina")
        BEBIDAS = "bebidas", _("Bebidas")
        POSTRES = "postres", _("Postres")

    empresa = models.ForeignKey(
        "reservas.Empresa", on_delete=models.CASCADE, related_name="catalogo_items", null=True, blank=True
    )
    codigo = models.CharField(_("Código (identificador)"), max_length=32)
    nombre = models.CharField(_("Nombre"), max_length=180)
    categoria = models.ForeignKey(CatalogCategory, on_delete=models.PROTECT, related_name="items", verbose_name=_("Categoría"))
    precio = models.DecimalField(_("Precio"), max_digits=9, decimal_places=2)
    descripcion = models.CharField(_("Descripción"), max_length=300, blank=True)
    activo = models.BooleanField(_("Activo"), default=True)

    area_impresion = models.CharField(_("Área de impresión"), max_length=12, choices=AreaImpresion.choices, default=AreaImpresion.COCINA)
    imprimible = models.BooleanField(_("Imprimible en cocina"), default=True)

    es_combo = models.BooleanField(_("Es combo"), default=False)
    precio_combo = models.DecimalField(_("Precio del combo (si fijo)"), max_digits=9, decimal_places=2, null=True, blank=True)

    aplica_impuesto = models.BooleanField(_("Aplica impuesto"), default=True)
    aplica_servicio = models.BooleanField(_("Aplica cargo por servicio"), default=False)

    class Meta:
        db_table = "catalog_item"
        ordering = ["categoria__orden", "categoria__nombre", "nombre"]
        verbose_name = _("Ítem de menú")
        verbose_name_plural = _("Ítems de menú")
        indexes = [
            models.Index(fields=["codigo"]),
            models.Index(fields=["nombre"]),
            models.Index(fields=["activo"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], name="uniq_catitem_codigo_por_empresa"),
        ]

    def save(self, *args, **kwargs):
        if not self.empresa_id and self.categoria_id:
            self.empresa_id = self.categoria.empresa_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class CatalogComboComponent(models.Model):
    combo = models.ForeignKey(
        CatalogItem, on_delete=models.CASCADE, related_name="componentes",
        limit_choices_to={"es_combo": True}, verbose_name=_("Combo")
    )
    item = models.ForeignKey(
        CatalogItem, on_delete=models.PROTECT, related_name="incluido_en_combos",
        limit_choices_to={"es_combo": False}, verbose_name=_("Ítem")
    )
    cantidad = models.PositiveIntegerField(_("Cantidad"), default=1)

    class Meta:
        db_table = "catalog_combo_component"
        verbose_name = _("Componente de combo")
        verbose_name_plural = _("Componentes de combo")
        unique_together = [("combo", "item")]

    def __str__(self):
        return f"{self.combo.codigo} -> {self.cantidad} x {self.item.codigo}"
