# reservas/forms_publico.py
from django import forms
from django.utils.translation import gettext_lazy as _


class ReservaPublicaForm(forms.Form):
    fecha = forms.DateField(label=_("Fecha"), widget=forms.DateInput(attrs={"type": "date"}))
    hora = forms.TimeField(label=_("Hora"), widget=forms.TimeInput(attrs={"type": "time", "step": 300}))
    party = forms.IntegerField(label=_("Personas"), min_value=1, max_value=50, initial=2)
    nombre = forms.CharField(label=_("Nombre"), max_length=100)
    telefono = forms.CharField(
        label=_("WhatsApp / teléfono"), max_length=20,
        help_text=_("Te enviaremos la confirmación y un recordatorio."),
    )
    email = forms.EmailField(label=_("Correo (opcional)"), required=False)
    notas = forms.CharField(
        label=_("Notas (opcional)"), required=False, max_length=300,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": _("Cumpleaños, silla para bebé, alergias…")}),
    )
    acepto_privacidad = forms.BooleanField(label=_("Acepto el aviso de privacidad"), required=True)
    acepta_promociones = forms.BooleanField(label=_("Quiero recibir promociones"), required=False)
    # Campo trampa anti-bots (debe quedar vacío)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, max_personas=12, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["party"].max_value = max_personas
        self.fields["party"].widget.attrs.update({"min": 1, "max": max_personas})
        for name, f in self.fields.items():
            if isinstance(f.widget, forms.CheckboxInput):
                f.widget.attrs["class"] = "form-check-input"
            elif not isinstance(f.widget, forms.HiddenInput):
                f.widget.attrs["class"] = "form-control"
        self.fields["telefono"].widget.attrs.update({"inputmode": "tel", "autocomplete": "tel"})
        self.fields["nombre"].widget.attrs["autocomplete"] = "name"
        self.fields["email"].widget.attrs["autocomplete"] = "email"

    def clean_telefono(self):
        import re
        tel = self.cleaned_data["telefono"]
        if len(re.sub(r"\D", "", tel)) < 8:
            raise forms.ValidationError(_("Escribe un teléfono válido."))
        return tel.strip()

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError(_("bot"))
        return ""
