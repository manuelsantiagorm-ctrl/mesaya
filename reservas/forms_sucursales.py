from django.utils.translation import gettext_lazy as _
from django import forms
from .models import Sucursal, Pais
from .utils_auth import user_allowed_countries  # helper para filtrar países por usuario


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = [
            "nombre", "direccion", "codigo_postal", "pais", "timezone",
            "lat", "lng", "place_id",
            "recepcion_x", "recepcion_y", "precio_nivel", "cocina", "activo",
            "portada", "portada_alt", "administradores", "email_contacto",
        ]
        labels = {
            "nombre": _("Nombre"),
            "direccion": _("Dirección"),
            "codigo_postal": _("Código postal"),
            "pais": _("País"),
            "timezone": _("Zona horaria (IANA)"),
            "recepcion_x": _("Recepción X"),
            "recepcion_y": _("Recepción Y"),
            "precio_nivel": _("Precio nivel"),
            "cocina": _("Cocina / concepto"),
            "activo": _("Activo"),
            "portada": _("Imagen de portada"),
            "portada_alt": _("Texto alternativo"),
            "administradores": _("Administradores de la sucursal"),
            "email_contacto": _("Correo de contacto"),
        }
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control", "placeholder": _("Sucursal Centro")
            }),
            "direccion": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": _("Escribe y selecciona de Google Maps"),
                "autocomplete": "off"
            }),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control"}),
            "pais": forms.Select(attrs={"class": "form-select"}),
            "timezone": forms.TextInput(attrs={
                "class": "form-control", "placeholder": _("America/Mexico_City")
            }),

            "lat": forms.TextInput(attrs={
                "class": "form-control-plaintext border rounded px-2",
                "readonly": True
            }),
            "lng": forms.TextInput(attrs={
                "class": "form-control-plaintext border rounded px-2",
                "readonly": True
            }),
            "place_id": forms.TextInput(attrs={
                "class": "form-control-plaintext border rounded px-2",
                "readonly": True
            }),

            "recepcion_x": forms.NumberInput(attrs={"class": "form-control"}),
            "recepcion_y": forms.NumberInput(attrs={"class": "form-control"}),
            "precio_nivel": forms.Select(attrs={"class": "form-select"}),
            "cocina": forms.TextInput(attrs={
                "class": "form-control", "placeholder": _("Americana • Desayunos")
            }),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),

            "portada": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "portada_alt": forms.TextInput(attrs={"class": "form-control"}),

            "administradores": forms.SelectMultiple(attrs={
                "class": "form-select", "size": 6
            }),
            "email_contacto": forms.EmailInput(attrs={"class": "form-control"}),
        }

    # -------------------------------------------------------------
    # Inicialización con control de países según usuario logueado
    # -------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # 🔹 Asegura que haya países cargados y un label vacío
        self.fields["pais"].queryset = Pais.objects.all().order_by("nombre")
        self.fields["pais"].empty_label = "Selecciona un país"

        # 🔹 País: el dueño de la empresa puede abrir sucursales en cualquier país;
        #    un admin de país solo en los suyos.
        from . import tenancy
        from django.contrib.auth import get_user_model
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not tenancy.is_chain_owner(user):
            allowed = user_allowed_countries(user).order_by("nombre")
            self.fields["pais"].queryset = allowed
            if allowed.count() == 1 and not self.instance.pk:
                self.fields["pais"].initial = allowed.first().pk

        # 🔹 Administradores: solo personal de la misma empresa
        empresa = getattr(self.instance, "empresa", None) or getattr(request, "empresa", None)
        User = get_user_model()
        if empresa is not None:
            self.fields["administradores"].queryset = User.objects.filter(
                membresias__empresa=empresa, membresias__activo=True, is_staff=True
            ).order_by("email").distinct()
        else:
            self.fields["administradores"].queryset = User.objects.none()
        self.fields["administradores"].required = False
