# reservas/forms.py
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
from django.db import IntegrityError, transaction
from datetime import datetime   # <--- ESTE es el que falta
from django.forms.models import construct_instance  # <-- ESTE ES EL QUE FALTABA

from django.forms import inlineformset_factory
from .models import SucursalFoto
from .models import Cliente, Reserva, Sucursal, Mesa
from .utils import conflicto_y_disponible, generar_folio
from .emails import enviar_correo_reserva_confirmada
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

# =========================
# Registro de cliente
# =========================
class ClienteRegistrationForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput)
    nombre = forms.CharField(max_length=100)
    telefono = forms.CharField(max_length=20, required=False)
    codigo_postal = forms.CharField(max_length=10, required=True, label=_("Código Postal"))

    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "email", "password", "codigo_postal"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(username=email).exists():
            raise ValidationError(_("Ese correo ya está registrado."))
        return email

    def save(self, commit=True):
        email = self.cleaned_data["email"].lower()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data["password"],
            first_name=self.cleaned_data["nombre"],
        )
        cliente = Cliente(
            user=user,
            nombre=self.cleaned_data["nombre"],
            email=email,
            telefono=self.cleaned_data.get("telefono", ""),
            codigo_postal=self.cleaned_data["codigo_postal"],
        )
        if commit:
            cliente.save()
        return user


# =========================
# Form de Reserva (cliente)
# =========================
DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M"]  # para <input type="datetime-local">

class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ["fecha", "num_personas"]
        widgets = {
            "fecha": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "num_personas": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def __init__(self, *args, **kwargs):
        self.mesa = kwargs.pop("mesa", None)
        self.cliente = kwargs.pop("cliente", None)
        super().__init__(*args, **kwargs)
        self.fields["fecha"].input_formats = DATETIME_INPUT_FORMATS

    def clean_fecha(self):
        fecha = self.cleaned_data.get("fecha")
        if not fecha:
            raise forms.ValidationError(_("Selecciona fecha y hora."))

        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha, timezone.get_current_timezone())

        ahora = timezone.now()

        if fecha < ahora:
            raise forms.ValidationError(_("La fecha/hora no puede estar en el pasado."))

        lead_min = int(getattr(settings, "RESERVA_LEAD_MIN", 15))
        if fecha < ahora + timezone.timedelta(minutes=lead_min):
            raise forms.ValidationError(
                f"Debes reservar con al menos {lead_min} minutos de anticipación."
            )

        max_dias = int(getattr(settings, "RESERVAS_MAX_DIAS_ADELANTE", 30))
        if fecha.date() > (timezone.localdate() + timezone.timedelta(days=max_dias)):
            raise forms.ValidationError(
                f"No puedes reservar con más de {max_dias} días de anticipación."
            )

        return fecha


# =========================
# Admin: reserva rápida por mesa (si la usas en algún detalle)
# =========================
class AdminReservaRapidaForm(forms.Form):
    fecha = forms.DateTimeField(
        label=_("Fecha y hora"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )
    asistentes = forms.IntegerField(label=_("Asistentes"), min_value=1)
    nombre = forms.CharField(label=_("Nombre del cliente (opcional)"), required=False)
    email = forms.EmailField(label=_("Correo (opcional)"), required=False)

    def __init__(self, *args, mesa: Mesa | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mesa = mesa

    def clean_asistentes(self):
        a = self.cleaned_data["asistentes"]
        if self.mesa and getattr(self.mesa, "capacidad", None) and a > self.mesa.capacidad:
            raise forms.ValidationError(f"La mesa tiene capacidad {self.mesa.capacidad}.")
        return a


# =========================
# Perfil de cliente
# =========================
class ClientePerfilForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "email", "telefono", "codigo_postal"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Tu nombre")}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": _("tucorreo@dominio.com")}),
            "telefono": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Teléfono")}),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control", "placeholder": _("CP")}),
        }


# =========================
# Walk-in (staff)
# =========================
# ---- imports necesarios (arriba de forms.py) ----


class WalkInReservaForm(forms.ModelForm):
    # Campos UI (no del modelo)
    nombre_cliente = forms.CharField(label=_("Nombre del cliente"), max_length=120)
    email_cliente = forms.EmailField(label=_("Email (opcional)"), required=False)
    telefono_cliente = forms.CharField(label=_("Teléfono (opcional)"), max_length=30, required=False)

    # Selecciones
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.all(), required=False, label=_("Sucursal"))
    mesa = forms.ModelChoiceField(queryset=Mesa.objects.none(), label=_("Mesa"))

    # Fecha/hora (para <input type="datetime-local">)
    fecha = forms.DateTimeField(
        label=_("Fecha y hora"),
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )

    class Meta:
        model = Reserva
        fields = ["sucursal", "mesa", "fecha", "num_personas"]

    # 1) Excluir 'cliente' de la validación del modelo
    def _get_validation_exclusions(self):
        excl = super()._get_validation_exclusions()
        excl.add("cliente")
        return excl

    # 3) Filtrar errores del modelo en 'cliente' para que no reviente add_error
    def _post_clean(self):
        # Copia del flujo de ModelForm._post_clean con intercept
        # 3.1: pasar cleaned_data al instance
        construct_instance(self, self.instance, self._meta.fields, self._meta.exclude)
        # 3.2: validar campos de modelo (sin unique)
        exclude = self._get_validation_exclusions()
        try:
            self.instance.full_clean(exclude=exclude, validate_unique=False)
        except ValidationError as e:
            error_dict = e.error_dict.copy()
            # quitar 'cliente' si vino del modelo
            if "cliente" in error_dict:
                error_dict.pop("cliente", None)
            if error_dict:
                # reinyectar solo si quedan otros errores válidos
                raise ValidationError(error_dict)
            # si no quedó nada, lo ignoramos
        # 3.3: validar uniqueness normal del ModelForm
        try:
            self.validate_unique()
        except ValidationError as e:
            self._update_errors(e)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        suc_pref = kwargs.pop("sucursal_pref", None)
        super().__init__(*args, **kwargs)

        # Widget fecha
        self.fields["fecha"].widget.format = "%Y-%m-%dT%H:%M"
        self.fields["fecha"].widget.attrs["step"] = 60

        # Bootstrap
        for name in ["nombre_cliente", "email_cliente", "telefono_cliente", "fecha", "num_personas"]:
            if name in self.fields:
                cls = self.fields[name].widget.attrs.get("class", "")
                self.fields[name].widget.attrs["class"] = (cls + " form-control").strip()
        for name in ["sucursal", "mesa"]:
            if name in self.fields:
                cls = self.fields[name].widget.attrs.get("class", "")
                self.fields[name].widget.attrs["class"] = (cls + " form-select").strip()

        # Sucursales que el usuario puede administrar (multi-empresa)
        from . import tenancy
        visibles = tenancy.sucursales_for_user(self.user).filter(activo=True).order_by("nombre")
        self.fields["sucursal"].queryset = visibles
        self.fields["sucursal"].required = True
        suc = None
        if suc_pref and visibles.filter(pk=suc_pref.pk).exists():
            suc = suc_pref
        elif visibles.count() == 1:
            suc = visibles.first()
        if suc:
            self.fields["sucursal"].initial = suc.id
        if visibles.count() == 1:
            self.fields["sucursal"].widget = forms.HiddenInput()

        # Mesas por sucursal (solo de sucursales visibles)
        suc_id = self.data.get("sucursal") or self.fields["sucursal"].initial
        try:
            suc_id = int(suc_id) if suc_id else None
        except (TypeError, ValueError):
            suc_id = None
        if suc_id and visibles.filter(pk=suc_id).exists():
            self.fields["mesa"].queryset = Mesa.objects.filter(sucursal_id=suc_id).order_by("numero")
        else:
            self.fields["mesa"].queryset = Mesa.objects.none()

        # Fecha por defecto
        if not self.initial.get("fecha") and not self.data.get("fecha"):
            tz = timezone.get_current_timezone()
            now = timezone.now().astimezone(tz).replace(second=0, microsecond=0)
            step = int(getattr(settings, "RESERVA_PASO_MINUTOS", 15))
            extra = (step - (now.minute % step)) % step
            self.initial["fecha"] = (now + timezone.timedelta(minutes=extra))

    def clean_fecha(self):
        dt = self.cleaned_data["fecha"]
        tz = timezone.get_current_timezone()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, tz)
        return dt.replace(second=0, microsecond=0)

    def clean(self):
        cleaned = super().clean()

        # 2) Crear/asignar SIEMPRE el cliente al instance (aunque falte mesa/fecha)
        email = (self.cleaned_data.get("email_cliente") or "").strip()
        nombre = (self.cleaned_data.get("nombre_cliente") or "").strip()
        tel = (self.cleaned_data.get("telefono_cliente") or "").strip()

        if email:
            cliente = Cliente.objects.filter(email__iexact=email, user__isnull=True).order_by("-id").first() \
                or Cliente.objects.filter(email__iexact=email).order_by("-id").first()
            if cliente is None:
                cliente = Cliente.objects.create(email=email, nombre=nombre, telefono=tel)
            to_update = []
            if not getattr(cliente, "nombre", "") and nombre:
                cliente.nombre = nombre
                to_update.append("nombre")
            if tel and not getattr(cliente, "telefono", ""):
                cliente.telefono = tel
                to_update.append("telefono")
            if to_update:
                cliente.save(update_fields=to_update)
        else:
            # Walk-in sin email: lo creamos con nombre/tel
            cliente = Cliente.objects.create(nombre=nombre, telefono=tel or "")

        self.instance.cliente = cliente
        self.instance.estado = "CONF"

        # Validaciones de mesa/fecha/capacidad/choques
        mesa = cleaned.get("mesa")
        fecha = cleaned.get("fecha")
        num = cleaned.get("num_personas") or 1
        sucursal = cleaned.get("sucursal")

        if mesa and sucursal and mesa.sucursal_id != sucursal.id:
            self.add_error("mesa", _("La mesa no pertenece a la sucursal seleccionada."))
            return cleaned

        if mesa and getattr(mesa, "capacidad", None) and num > mesa.capacidad:
            self.add_error("num_personas", f"La mesa admite hasta {mesa.capacidad} personas.")

        if mesa and fecha:
            hay, hasta = conflicto_y_disponible(mesa, fecha)
            if hay:
                self.add_error(
                    "fecha",
                    f"Choque: la mesa está ocupada hasta las "
                    f"{hasta.astimezone(timezone.get_current_timezone()).strftime('%H:%M')}."
                )

        return cleaned

    def save(self, commit=True):
        reserva = super().save(commit=False)

        if not getattr(reserva, "folio", ""):
            reserva.folio = generar_folio(reserva)

        if commit:
            for _ in range(5):
                try:
                    with transaction.atomic():
                        reserva.save()
                    break
                except IntegrityError:
                    reserva.folio = generar_folio(reserva)
            else:
                raise

            email = (self.cleaned_data.get("email_cliente") or "").strip()
            if email:
                try:
                    enviar_correo_reserva_confirmada(reserva, bcc_sucursal=True)
                except Exception:
                    pass

        return reserva


# reservas/forms.py
# reservas/forms.py
from django import forms
from django.forms import inlineformset_factory

from .models import Sucursal, SucursalFoto


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = [
            "nombre", "direccion", "codigo_postal",
            "portada", "portada_alt",
            "cocina", "precio_nivel", "rating", "reviews",
            "recomendado", "activo",
        ]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "direccion": forms.TextInput(attrs={"class": "form-control"}),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control"}),
            "portada": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "portada_alt": forms.TextInput(attrs={"class": "form-control"}),
            "cocina": forms.TextInput(attrs={"class": "form-control"}),
            "precio_nivel": forms.TextInput(attrs={"class": "form-control", "placeholder": "$, $$, $$$, $$$$"}),
            "rating": forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "min": "0", "max": "5"}),
            "reviews": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "recomendado": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SucursalFotoForm(forms.ModelForm):
    class Meta:
        model = SucursalFoto
        fields = ["imagen", "alt", "orden"]
        widgets = {
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "alt": forms.TextInput(attrs={"class": "form-control"}),
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }


SucursalFotoFormSet = inlineformset_factory(
    parent_model=Sucursal,
    model=SucursalFoto,
    form=SucursalFotoForm,
    extra=1,
    can_delete=True,
)



