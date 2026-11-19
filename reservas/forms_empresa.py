# reservas/forms_empresa.py
from django.utils.translation import gettext_lazy as _
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from .models import Empresa, MiembroEmpresa, Sucursal

User = get_user_model()


class _Bootstrap:
    def _bs(self):
        for f in self.fields.values():
            w = f.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs["class"] = "form-check-input"
            elif isinstance(w, forms.Select):
                w.attrs["class"] = "form-select"
            else:
                w.attrs["class"] = "form-control"


class EmpresaConfigForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = Empresa
        fields = [
            "nombre", "logo", "color_primario", "color_secundario",
            "razon_social", "email_contacto", "telefono",
            "whatsapp_habilitado", "recordatorio_horas", "aviso_privacidad",
            "agente_ia_activo", "agente_ia_modo", "agente_ia_instrucciones",
        ]
        widgets = {
            "color_primario": forms.TextInput(attrs={"type": "color"}),
            "color_secundario": forms.TextInput(attrs={"type": "color"}),
            "aviso_privacidad": forms.Textarea(attrs={"rows": 10}),
            "agente_ia_instrucciones": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": _("Ej. Trata de usted. Los domingos hay buffet. Terraza solo con buen clima."),
            }),
        }
        labels = {
            "nombre": _("Nombre comercial"),
            "razon_social": _("Razón social"),
            "email_contacto": _("Correo de contacto"),
            "telefono": _("Teléfono"),
            "color_primario": _("Color principal"),
            "color_secundario": _("Color secundario"),
            "whatsapp_habilitado": _("Enviar confirmación y recordatorio por WhatsApp"),
            "recordatorio_horas": _("Horas antes para el recordatorio"),
            "aviso_privacidad": _("Aviso de privacidad (vacío = plantilla estándar)"),
            "agente_ia_activo": _("Activar asistente de IA (chat web y WhatsApp)"),
            "agente_ia_modo": _("Cuando el asistente encuentra lugar"),
            "agente_ia_instrucciones": _("Indicaciones para el asistente"),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._bs()
        self.fields["color_primario"].widget.attrs["class"] = "form-control form-control-color"
        self.fields["color_secundario"].widget.attrs["class"] = "form-control form-control-color"


class SucursalReglasForm(_Bootstrap, forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = [
            "telefono", "email_contacto", "hora_apertura", "hora_cierre", "intervalo_min",
            "duracion_min", "duracion_pico_min", "tolerancia_min", "max_personas",
            "dias_adelante", "max_reservas_cliente_dia", "colchon_min", "activo",
        ]
        labels = {
            "hora_apertura": _("Abre (hora 0-23)"),
            "hora_cierre": _("Cierra (hora 1-24)"),
            "intervalo_min": _("Cada cuántos minutos se ofrecen horarios"),
            "duracion_min": _("Duración normal (min)"),
            "duracion_pico_min": _("Duración en hora pico (min)"),
            "tolerancia_min": _("Tolerancia de llegada (min)"),
            "max_personas": _("Máximo de personas por reserva en línea"),
            "dias_adelante": _("Días máximos de anticipación"),
            "max_reservas_cliente_dia": _("Reservas por cliente el mismo día"),
            "colchon_min": _("Colchón entre reservas de la misma mesa (min)"),
            "email_contacto": _("Correo de contacto"),
            "telefono": _("Teléfono"),
            "activo": _("Recibir reservas en línea"),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._bs()
        for name in self.Meta.fields:
            f = self.fields[name]
            if name not in ("activo", "telefono", "email_contacto"):
                f.widget.attrs["placeholder"] = str(self.instance.regla(name)) if name in Sucursal._REGLAS else ""

    def clean(self):
        cd = super().clean()
        a, c = cd.get("hora_apertura"), cd.get("hora_cierre")
        if a is not None and not 0 <= a <= 23:
            self.add_error("hora_apertura", _("Usa una hora entre 0 y 23."))
        if c is not None and not 1 <= c <= 24:
            self.add_error("hora_cierre", _("Usa una hora entre 1 y 24."))
        if a is not None and c is not None and c <= a:
            self.add_error("hora_cierre", _("La hora de cierre debe ser después de la apertura."))
        return cd


def _roles_permitidos(puede_owner):
    excluir = set() if puede_owner else {MiembroEmpresa.OWNER, MiembroEmpresa.ADMIN}
    return [c for c in MiembroEmpresa.ROLES if c[0] not in excluir]


class _PuestoMixin:
    """Puesto + sucursales, con las sucursales obligatorias para puestos de una sucursal."""

    def _puesto_fields(self, empresa, puede_owner):
        self.fields["rol"].choices = _roles_permitidos(puede_owner)
        self.fields["sucursales"].queryset = empresa.sucursales.order_by("nombre") if empresa else Sucursal.objects.none()
        if empresa and empresa.sucursales.count() == 1 and not self.is_bound:
            self.initial.setdefault("sucursales", list(empresa.sucursales.values_list("pk", flat=True)))

    def _clean_puesto(self, cd):
        if cd.get("rol") in MiembroEmpresa.ROLES_POR_SUCURSAL and not cd.get("sucursales"):
            self.add_error("sucursales", _("Elige en qué sucursal va a trabajar."))
        return cd


class NuevoMiembroForm(_PuestoMixin, _Bootstrap, forms.Form):
    nombre = forms.CharField(label=_("Nombre"), max_length=150)
    email = forms.EmailField(label=_("Correo (con este entra al sistema)"))
    rol = forms.ChoiceField(label=_("Puesto"), choices=MiembroEmpresa.ROLES, initial=MiembroEmpresa.MESERO,
                            widget=forms.RadioSelect)
    sucursales = forms.ModelMultipleChoiceField(
        label=_("¿En qué sucursal trabaja?"), queryset=Sucursal.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    password = forms.CharField(
        label=_("Contraseña para entrar"), widget=forms.PasswordInput, required=False,
        help_text=_("Solo si es una persona nueva. Dásela en persona; podrá cambiarla después."),
    )

    def __init__(self, *a, empresa=None, puede_owner=False, **kw):
        super().__init__(*a, **kw)
        self.empresa = empresa
        self._puesto_fields(empresa, puede_owner)
        self._bs()

    def clean(self):
        cd = super().clean()
        email = (cd.get("email") or "").lower()
        existe = User.objects.filter(email__iexact=email).first()
        if existe and existe.is_superuser:
            raise forms.ValidationError(_("Ese usuario no se puede agregar."))
        if not existe:
            pw = cd.get("password")
            if not pw:
                self.add_error("password", _("Escribe una contraseña inicial para el usuario nuevo."))
            else:
                try:
                    validate_password(pw)
                except forms.ValidationError as e:
                    self.add_error("password", e)
        cd["usuario_existente"] = existe
        return self._clean_puesto(cd)

    def save(self):
        cd = self.cleaned_data
        user = cd["usuario_existente"]
        if user is None:
            email = cd["email"].lower()
            username = email
            i = 2
            while User.objects.filter(username=username).exists():
                username = f"{email}-{i}"; i += 1
            user = User.objects.create_user(username=username, email=email, password=cd["password"],
                                            first_name=cd["nombre"][:150])
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        m, _nuevo = MiembroEmpresa.objects.update_or_create(
            empresa=self.empresa, user=user, defaults={"rol": cd["rol"], "activo": True}
        )
        asignar_sucursales(self.empresa, user, cd["rol"], cd.get("sucursales") or [])
        return m


def asignar_sucursales(empresa, user, rol, sucursales):
    """Deja al usuario EXACTAMENTE en esas sucursales de la empresa (dueño y gerente general: todas, sin lista)."""
    elegidas = {s.pk for s in sucursales} if rol in MiembroEmpresa.ROLES_POR_SUCURSAL else set()
    for s in empresa.sucursales.all():
        if s.pk in elegidas:
            s.administradores.add(user)
        else:
            s.administradores.remove(user)


class EditarPuestoForm(_PuestoMixin, _Bootstrap, forms.Form):
    rol = forms.ChoiceField(label=_("Puesto"), choices=MiembroEmpresa.ROLES, widget=forms.RadioSelect)
    sucursales = forms.ModelMultipleChoiceField(
        label=_("¿En qué sucursal trabaja?"), queryset=Sucursal.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *a, empresa=None, puede_owner=False, **kw):
        super().__init__(*a, **kw)
        self.empresa = empresa
        self._puesto_fields(empresa, puede_owner)
        self._bs()

    def clean(self):
        return self._clean_puesto(super().clean())
