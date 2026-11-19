from django.utils.translation import gettext as _
import time
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.db import transaction
from django.shortcuts import render, redirect, resolve_url
from django.utils import timezone
from django.views import View

from .forms import SignupEmailForm, VerifyEmailCodeForm
from .models import EmailOTP
from .utils_email import send_otp_email

User = get_user_model()


# --------- Helpers ---------
def _rate_ok_to_send(email: str) -> bool:
    """
    Límite por hora por email para no spamear.
    """
    max_per_hour = getattr(settings, "EMAIL_OTP_MAX_PER_HOUR_PER_EMAIL", 5)
    since = timezone.now() - timedelta(hours=1)
    return EmailOTP.objects.filter(email=email, created_at__gte=since).count() < max_per_hour


def _home_reservas_url() -> str:
    """
    URL de destino al finalizar el flujo OTP.
    Intenta 'reservas:home' y si no existe, usa la raíz "/".
    """
    try:
        return resolve_url("reservas:home")
    except Exception:
        return "/"


# --------- Views ---------
class ResendOTPView(View):
    """
    Reenvía el código OTP con cooldown y rate-limit.
    """
    def post(self, request):
        email = request.session.get("signup_email")
        if not email:
            return redirect("accounts:signup_start")

        # Cooldown entre reenvíos (segundos)
        cooldown = getattr(settings, "EMAIL_OTP_RESEND_COOLDOWN_SECONDS", 60)
        last_sent_at = request.session.get("otp_last_sent_at")
        if last_sent_at and time.time() - last_sent_at < cooldown:
            remaining = int(cooldown - (time.time() - last_sent_at))
            messages.warning(request, _("Espera %(v0)ss para reenviar.") % {"v0": remaining})
            return redirect("accounts:verify_email")

        # Rate-limit por hora
        if not _rate_ok_to_send(email):
            messages.error(request, _("Has solicitado demasiados códigos. Intenta en 1 hora."))
            return redirect("accounts:verify_email")

        # Genera y envía
        otp = EmailOTP.create_for_email(
            email=email,
            purpose="signup",
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT"),
        )
        send_otp_email(email, otp._plain_code)
        request.session["otp_last_sent_at"] = time.time()
        messages.success(request, _("Te reenviamos un nuevo código."))
        return redirect("accounts:verify_email")


class SignupStartView(View):
    """
    Paso 1: el cliente pone correo y contraseña. Se genera y envía OTP.
    """
    template_name = "accounts/signup_start.html"

    def get(self, request):
        return render(request, self.template_name, {"form": SignupEmailForm()})

    def post(self, request):
        form = SignupEmailForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        email = form.cleaned_data["email"]
        password = form.cleaned_data["password1"]

        # Guarda en sesión para usar en el paso de verificación
        request.session["signup_email"] = email
        request.session["signup_password"] = password
        request.session["otp_last_sent_at"] = time.time()

        # Rate-limit por hora
        if not _rate_ok_to_send(email):
            messages.error(request, _("Has solicitado demasiados códigos. Intenta en 1 hora."))
            return redirect("accounts:verify_email")

        # Genera OTP y envía
        otp = EmailOTP.create_for_email(
            email=email,
            purpose="signup",
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT"),
        )
        send_otp_email(email, otp._plain_code)

        messages.success(request, _("Te enviamos un código a %(v0)s.") % {"v0": email})
        return redirect("accounts:verify_email")


class VerifyEmailView(View):
    """
    Paso 2: el cliente ingresa el código. Si es válido:
    - Crea usuario (si no existe) con la contraseña de la sesión
    - Inicia sesión
    - Redirige directo al home de reservas
    """
    template_name = "accounts/verify_email.html"

    def get(self, request):
        email = request.session.get("signup_email")
        if not email:
            messages.warning(request, _("Primero ingresa tu correo y contraseña."))
            return redirect("accounts:signup_start")

        form = VerifyEmailCodeForm(initial={"email": email})
        return render(request, self.template_name, {"form": form})

    @transaction.atomic
    def post(self, request):
        form = VerifyEmailCodeForm(request.POST)
        if not form.is_valid():
            # El propio form debe validar el OTP contra EmailOTP (código/expiración/uso/attempts)
            return render(request, self.template_name, {"form": form})

        # Si llegamos aquí, el código es válido para este email (según el form)
        email = form.cleaned_data["email"].strip()
        raw_password = request.session.get("signup_password")

        # Crea o recupera usuario
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            # Crear usuario nuevo. Soporta proyectos con o sin 'username' en el modelo.
            user = User(email=email)
            # Si el modelo tiene username, úsalo (email como username para simplicidad)
            if hasattr(user, "username") and user.username in (None, ""):
                user.username = email
            if raw_password:
                user.set_password(raw_password)
            else:
                user.set_unusable_password()
            user.save()
        else:
            # Si ya existía y no tiene contraseña usable (p.ej. cuenta social), asígnale la del flujo
            if not user.has_usable_password() and raw_password:
                user.set_password(raw_password)
                user.save()

        # Autologin
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        # Limpia la sesión del flujo OTP
        for k in ("signup_email", "signup_password", "otp_last_sent_at"):
            request.session.pop(k, None)

        messages.success(request, _("¡Cuenta verificada y acceso iniciado!"))
        # 🚀 Directo al home de reservas (o "/" si no existe ese nombre)
        return redirect(_home_reservas_url())
