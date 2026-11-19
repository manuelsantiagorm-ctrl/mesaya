# reservas/views_ventas.py
"""Página de inicio comercial de la plataforma, captura de prospectos y panel del dueño de la plataforma."""
from django.utils.translation import gettext_lazy as _
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .branding import brand_for_empresa
from .models import ConversacionIA, Empresa, Prospecto, Reserva, Sucursal

PRECIOS = {"basico": 599, "pro": 1199, "cadena": 999}


class ProspectoForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # trampa para bots

    class Meta:
        model = Prospecto
        fields = ["nombre", "restaurante", "telefono", "email", "ciudad", "sucursales", "mensaje"]
        labels = {"nombre": "Tu nombre", "restaurante": "Restaurante", "telefono": "WhatsApp",
                  "email": _("Correo (opcional)"), "ciudad": "Ciudad", "sucursales": "Sucursales",
                  "mensaje": _("¿Qué te gustaría resolver?")}
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "autocomplete": "name"}),
            "restaurante": forms.TextInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control", "inputmode": "tel", "autocomplete": "tel"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "autocomplete": "email"}),
            "ciudad": forms.TextInput(attrs={"class": "form-control"}),
            "sucursales": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 500}),
            "mensaje": forms.Textarea(attrs={"class": "form-control", "rows": 2,
                                             "placeholder": _("Ej. contestar WhatsApp, menos no-shows, lista de espera…")}),
        }

    def clean_telefono(self):
        tel = "".join(c for c in self.cleaned_data["telefono"] if c.isdigit() or c == "+")
        if len(tel.replace("+", "")) < 10:
            raise forms.ValidationError(_("Escribe un número de 10 dígitos."))
        return tel


def landing(request, form=None):
    demo = Sucursal.objects.filter(activo=True, empresa__slug="demo").order_by("nombre").first() \
        or Sucursal.objects.filter(activo=True, empresa__activa=True).order_by("id").first()
    ctx = {
        "brand": brand_for_empresa(None),
        "form": form or ProspectoForm(),
        "demo": demo,
        "gracias": request.GET.get("gracias") == "1",
        "ventas_whatsapp": getattr(settings, "VENTAS_WHATSAPP", ""),
        "precios": PRECIOS,
        "stats": {
            "reservas": Reserva.objects.exclude(estado=Reserva.CANC).count(),
            "sucursales": Sucursal.objects.filter(activo=True).count(),
        },
    }
    from django.utils.translation import get_language
    plantilla = "landing/landing_en.html" if (get_language() or "es").startswith("en") else "landing/landing.html"
    return render(request, plantilla, ctx)


@require_POST
@ratelimit(key="ip", rate="8/h", method="POST", block=True)
def solicitar_demo(request):
    form = ProspectoForm(request.POST)
    if form.data.get("website"):
        return redirect("/?gracias=1#demo")  # bot: fingimos éxito
    if not form.is_valid():
        return landing(request, form=form)
    p = form.save(commit=False)
    p.origen = (request.GET.get("utm_source") or request.POST.get("origen") or "web")[:40]
    p.save()
    destino = getattr(settings, "VENTAS_EMAIL", "")
    if destino:
        try:
            send_mail(
                f"Nuevo prospecto: {p.restaurante}",
                f"{p.nombre} · {p.telefono} · {p.email}\n{p.ciudad} · {p.sucursales} sucursal(es)\n\n{p.mensaje}",
                None, [destino], fail_silently=True,
            )
        except Exception:
            pass
    return redirect("/?gracias=1#demo")


def _solo_plataforma(request):
    if not (request.user.is_authenticated and request.user.is_superuser):
        raise PermissionDenied("Solo el operador de la plataforma.")


@login_required
def plataforma(request):
    _solo_plataforma(request)
    hoy = timezone.localdate()
    desde = hoy - timedelta(days=30)
    empresas = (Empresa.objects.annotate(
        n_suc=Count("sucursales", filter=Q(sucursales__activo=True), distinct=True),
        n_res=Count("sucursales__reservas", filter=Q(sucursales__reservas__local_service_date__gte=desde), distinct=True),
    ).order_by("-activa", "nombre"))
    filas, mrr = [], 0
    for e in empresas:
        precio = PRECIOS.get(e.plan, 0) * (max(e.n_suc, 3) if e.plan == "cadena" else 1)
        if e.activa:
            mrr += precio
        estado = "al_dia" if (e.pagado_hasta and e.pagado_hasta >= hoy) else ("vencido" if e.pagado_hasta else "sin_registro")
        filas.append({"e": e, "precio": precio, "estado_pago": estado})
    prospectos = Prospecto.objects.all()[:200]
    ctx = {
        "filas": filas, "mrr": mrr, "prospectos": prospectos, "estados": Prospecto.ESTADOS,
        "kpi": {
            "empresas": sum(1 for f in filas if f["e"].activa),
            "sucursales": Sucursal.objects.filter(activo=True).count(),
            "reservas30": Reserva.objects.filter(local_service_date__gte=desde).count(),
            "conversaciones30": ConversacionIA.objects.filter(creado__date__gte=desde).count(),
            "prospectos_nuevos": Prospecto.objects.filter(estado=Prospecto.NUEVO).count(),
        },
    }
    return render(request, "reservas/plataforma.html", ctx)


@login_required
@require_POST
def plataforma_prospecto(request, pk):
    _solo_plataforma(request)
    p = get_object_or_404(Prospecto, pk=pk)
    estado = request.POST.get("estado")
    if estado in dict(Prospecto.ESTADOS):
        p.estado = estado
    if "notas" in request.POST:
        p.notas = request.POST["notas"][:2000]
    p.save()
    messages.success(request, _("%(v0)s: actualizado.") % {"v0": p.restaurante})
    return redirect("reservas:plataforma")


@login_required
@require_POST
def plataforma_pago(request, pk):
    _solo_plataforma(request)
    e = get_object_or_404(Empresa, pk=pk)
    meses = max(1, min(int(request.POST.get("meses") or 1), 12))
    base = e.pagado_hasta if (e.pagado_hasta and e.pagado_hasta >= timezone.localdate()) else timezone.localdate()
    y, m = base.year, base.month + meses
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    import calendar
    d = min(base.day, calendar.monthrange(y, m)[1])
    e.pagado_hasta = base.replace(year=y, month=m, day=d)
    e.save(update_fields=["pagado_hasta"])
    messages.success(request, _("%(v0)s: pagado hasta %(v1)s.") % {"v0": e.nombre, "v1": e.pagado_hasta.strftime("%d/%m/%Y")})
    return redirect("reservas:plataforma")



@login_required
@require_POST
def soporte_entrar(request, pk):
    """El operador entra a UNA empresa por 60 min, con motivo. Queda en la bitácora que ve el dueño."""
    _solo_plataforma(request)
    from .models import AccesoSoporte
    from .middleware import SoporteMiddleware
    e = get_object_or_404(Empresa, pk=pk, activa=True)
    motivo = (request.POST.get("motivo") or "").strip()[:300]
    if len(motivo) < 5:
        messages.error(request, _("Escribe el motivo del acceso (lo verá el dueño)."))
        return redirect("reservas:plataforma")
    AccesoSoporte.objects.filter(user=request.user, cerrado_en__isnull=True).update(cerrado_en=timezone.now())
    acc = AccesoSoporte.objects.create(
        user=request.user, empresa=e, motivo=motivo,
        expira=timezone.now() + timedelta(minutes=AccesoSoporte.DURACION_MIN),
        ip=(request.META.get("REMOTE_ADDR") or None),
    )
    request.session[SoporteMiddleware.SESSION_KEY] = acc.pk
    return redirect("reservas:panel_hoy")


@login_required
@require_POST
def soporte_salir(request):
    from .models import AccesoSoporte
    from .middleware import SoporteMiddleware
    acc_id = request.session.pop(SoporteMiddleware.SESSION_KEY, None)
    if acc_id:
        AccesoSoporte.objects.filter(pk=acc_id, user=request.user, cerrado_en__isnull=True).update(cerrado_en=timezone.now())
    return redirect("reservas:plataforma")
