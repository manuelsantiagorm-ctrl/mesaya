# reservas/forms_menu.py
from django import forms
from django.utils.translation import gettext_lazy as _

from .models_menu import CatalogCategory, CatalogComboComponent, CatalogItem


class CategoryForm(forms.ModelForm):
    class Meta:
        model = CatalogCategory
        fields = ["nombre", "orden", "activo"]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        qs = CatalogCategory.objects.filter(empresa=self.empresa, nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("Ya existe una categoría con ese nombre."))
        return nombre


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = CatalogItem
        fields = [
            "codigo", "nombre", "categoria", "precio", "descripcion",
            "activo", "area_impresion", "imprimible",
            "es_combo", "precio_combo",
            "aplica_impuesto", "aplica_servicio",
        ]

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields["categoria"].queryset = CatalogCategory.objects.filter(empresa=empresa).order_by("orden", "nombre")

    def clean_codigo(self):
        value = (self.cleaned_data.get("codigo") or "").strip().upper()
        if " " in value:
            raise forms.ValidationError(_("El código no debe contener espacios"))
        qs = CatalogItem.objects.filter(empresa=self.empresa, codigo=value).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("Ese código ya existe en tu menú."))
        return value


class ComboComponentForm(forms.ModelForm):
    class Meta:
        model = CatalogComboComponent
        fields = ["item", "cantidad"]
        widgets = {"cantidad": forms.NumberInput(attrs={"min": 1})}

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = CatalogItem.objects.filter(empresa=empresa, es_combo=False).order_by("nombre")
