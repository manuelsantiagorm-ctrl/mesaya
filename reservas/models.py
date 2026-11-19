# reservas/models.py
from __future__ import annotations
import secrets
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Avg, Count, Q
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from django.utils.timezone import is_naive
from django_countries.fields import CountryField  # (puedes quitarlo si no lo usas)

# ==============================================================
# Utilidades generales
# ==============================================================

def generar_folio() -> str:
    """Folio: R-YYYYMMDD-XXXXXX (ej. R-20250916-A3F91C)"""
    tz = timezone.get_current_timezone()
    today_str = timezone.now().astimezone(tz).strftime("%Y%m%d")
    suffix = secrets.token_hex(4).upper()  # 8 chars hex (4 mil millones por día)
    return f"R-{today_str}-{suffix}"

cp_mx_validator = RegexValidator(
    regex=r"^\d{5}$",
    message="El código postal debe tener 5 dígitos.",
)

User = settings.AUTH_USER_MODEL

# ==============================================================
# QuerySets con reglas de visibilidad
# ==============================================================

class SucursalQuerySet(models.QuerySet):
    """Visibilidad para staff: delega en reservas.tenancy (multi-empresa)."""
    def for_user(self, user):
        from .tenancy import sucursales_for_user
        return sucursales_for_user(user, self)

    def visibles_para(self, user):
        return self.for_user(user)

    def publicas(self, empresa=None):
        qs = self.filter(activo=True).filter(Q(empresa__isnull=True) | Q(empresa__activa=True))
        return qs.filter(empresa=empresa) if empresa is not None else qs


class OwnedBySucursalQuerySet(models.QuerySet):
    """Para modelos con FK directo 'sucursal' (Mesa, BloqueoMesa, Menú, Review)."""
    def visible_for(self, user):
        from .tenancy import scope_by_sucursal
        return scope_by_sucursal(self, user, "sucursal")


class ReservaQuerySet(models.QuerySet):
    def visible_for(self, user):
        from .tenancy import scope_by_sucursal
        return scope_by_sucursal(self, user, "sucursal")

# ==============================================================
# Helpers de duración (fallback)
# ==============================================================

try:
    from .utils import booking_total_minutes  # (dt: datetime, party: int) -> int
except Exception:
    def booking_total_minutes(dt: datetime, party: int) -> int:
        RESERVA_DURACION_MIN_NORM = int(getattr(settings, "RESERVA_DURACION_MIN_NORM", 90))
        RESERVA_DURACION_MIN_PICO = int(getattr(settings, "RESERVA_DURACION_MIN_PICO", 105))
        HORAS_PICO = list(getattr(settings, "HORAS_PICO", [(12, 15), (18, 21)]))
        extra = 15 if int(party or 2) >= 5 else 0
        local = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        es_pico = any(i <= local.hour < f for (i, f) in HORAS_PICO)
        base = RESERVA_DURACION_MIN_PICO if es_pico else RESERVA_DURACION_MIN_NORM
        return int(base + extra)

# ==============================================================
# MODELOS (core)
# ==============================================================

class Pais(models.Model):
    iso2 = models.CharField(max_length=2, unique=True)  # MX, US, ES...
    nombre = models.CharField(max_length=80)

    class Meta:
        verbose_name = "País"
        verbose_name_plural = "Países"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.iso2})"


class ChainOwnerPaisRole(models.Model):
    empresa = models.ForeignKey("Empresa", on_delete=models.CASCADE, null=True, blank=True, related_name="roles_pais")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles_pais")
    pais = models.ForeignKey(Pais, on_delete=models.CASCADE, related_name="chainowners")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("empresa", "user", "pais")
        verbose_name = "Administrador País (ChainOwner)"
        verbose_name_plural = "Administradores País (ChainOwners)"

    def __str__(self):
        estado = "activo" if self.activo else "inactivo"
        return f"{self.user} → {self.pais.iso2} ({estado})"


# ==============================================================
# MULTI-EMPRESA (cada restaurante/cadena cliente es una Empresa)
# ==============================================================

hex_color_validator = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Usa un color hexadecimal, ej. #1F6FEB")


class Empresa(models.Model):
    """Cliente de la plataforma (restaurante o cadena). Todo cuelga de aquí."""
    PLAN_BASICO = "basico"
    PLAN_PRO = "pro"
    PLAN_CADENA = "cadena"
    PLANES = [(PLAN_BASICO, _("Básico")), (PLAN_PRO, _("Pro")), (PLAN_CADENA, _("Cadena"))]

    nombre = models.CharField(max_length=150)
    slug = models.SlugField(max_length=60, unique=True)
    activa = models.BooleanField(default=True)
    plan = models.CharField(max_length=10, choices=PLANES, default=PLAN_BASICO)

    # Marca blanca
    logo = models.ImageField(upload_to="empresas/logos/", blank=True, null=True)
    color_primario = models.CharField(max_length=7, default="#1F6FEB", validators=[hex_color_validator])
    color_secundario = models.CharField(max_length=7, default="#0B1F3A", validators=[hex_color_validator])
    dominio = models.CharField(
        max_length=120, blank=True, null=True, unique=True,
        help_text="Dominio propio opcional, ej. reservas.mirestaurante.com",
    )

    # Contacto y legal
    razon_social = models.CharField(max_length=200, blank=True)
    email_contacto = models.EmailField(blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    aviso_privacidad = models.TextField(
        blank=True,
        help_text="Texto del aviso de privacidad. Si se deja vacío se usa la plantilla estándar.",
    )

    # Notificaciones
    whatsapp_habilitado = models.BooleanField(default=False)
    whatsapp_phone_number_id = models.CharField(
        max_length=40, blank=True, null=True, unique=True,
        help_text="ID del número de WhatsApp Business de esta empresa (Meta). Vacío = número de la plataforma.",
    )

    # Agente de IA (el dueño lo prende o apaga cuando quiera)
    IA_MODO_RESERVAR = "reservar"
    IA_MODO_PROPONER = "proponer"
    IA_MODOS = [
        (IA_MODO_RESERVAR, _("Reserva directamente si hay lugar")),
        (IA_MODO_PROPONER, _("Solo propone; el personal confirma")),
    ]
    agente_ia_activo = models.BooleanField(default=False)
    agente_ia_modo = models.CharField(max_length=10, choices=IA_MODOS, default=IA_MODO_RESERVAR)
    pagado_hasta = models.DateField(null=True, blank=True, help_text="Mensualidad pagada hasta esta fecha")
    agente_ia_instrucciones = models.TextField(
        blank=True, help_text="Indicaciones extra para el asistente (tono, promociones, reglas de la casa)."
    )
    recordatorio_horas = models.PositiveSmallIntegerField(
        default=24, help_text="Horas antes de la reserva para enviar el recordatorio (0 = no enviar)."
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.nombre)[:50] or "empresa"
            slug, i = base, 2
            while Empresa.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug, i = f"{base}-{i}", i + 1
            self.slug = slug
        if self.dominio:
            self.dominio = self.dominio.strip().lower() or None
        super().save(*args, **kwargs)


class MiembroEmpresa(models.Model):
    """Rol de un usuario dentro de una empresa."""
    OWNER = "owner"
    ADMIN = "admin"
    STAFF = "staff"          # gerente de sucursal
    RECEPCION = "recepcion"
    MESERO = "mesero"
    COCINA = "cocina"
    ROLES = [
        (OWNER, _("Dueño")),
        (ADMIN, _("Gerente general")),
        (STAFF, _("Gerente de sucursal")),
        (RECEPCION, _("Recepción")),
        (MESERO, _("Mesero")),
        (COCINA, _("Cocina")),
    ]
    ROLES_POR_SUCURSAL = (STAFF, RECEPCION, MESERO, COCINA)

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="miembros")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="membresias")
    rol = models.CharField(max_length=10, choices=ROLES, default=STAFF)
    activo = models.BooleanField(default=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("empresa", "user")
        verbose_name = "Miembro de empresa"
        verbose_name_plural = "Miembros de empresa"

    def __str__(self):
        return f"{self.user} @ {self.empresa} ({self.get_rol_display()})"

    @property
    def es_admin(self):
        return self.rol in (self.OWNER, self.ADMIN)


class Sucursal(models.Model):
    objects = SucursalQuerySet.as_manager()   # ← IMPORTANTE (una sola vez)

    empresa = models.ForeignKey(
        Empresa, on_delete=models.PROTECT, related_name="sucursales", null=True, blank=True,
    )
    nombre = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)
    portada = models.ImageField(upload_to="sucursales/portadas/", blank=True, null=True)
    portada_alt = models.CharField(max_length=120, blank=True)
    cocina = models.CharField(max_length=80, blank=True)
    email_contacto = models.EmailField(max_length=120, blank=True, null=True)

    # Geo
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    place_id = models.CharField(max_length=255, null=True, blank=True)

    # Plano recepción (0..100)
    recepcion_x = models.PositiveSmallIntegerField(default=3, help_text="Porcentaje X 0..100")
    recepcion_y = models.PositiveSmallIntegerField(default=3, help_text="Porcentaje Y 0..100")

    # Pública
    PRECIO_CHOICES = [(1, "$"), (2, "$$"), (3, "$$$")]
    precio_nivel = models.PositiveSmallIntegerField(choices=PRECIO_CHOICES, default=1)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    reviews = models.PositiveIntegerField(default=0)
    recomendado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)

    administradores = models.ManyToManyField(
        User, blank=True, related_name="sucursales_que_administra",
    )

    pais = models.ForeignKey("Pais", null=True, blank=True, on_delete=models.PROTECT, related_name="sucursales")
    timezone = models.CharField(max_length=64, null=True, blank=True, help_text="IANA TZ (ej. America/Mexico_City)")

    # Reglas de reservación por sucursal (vacío = usa el valor global de settings)
    hora_apertura = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Hora 0-23")
    hora_cierre = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Hora 1-24")
    intervalo_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Minutos entre horarios (ej. 15)")
    duracion_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Duración normal de una reserva")
    duracion_pico_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Duración en hora pico")
    tolerancia_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Minutos de tolerancia de llegada")
    max_personas = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Máximo de personas por reserva en línea")
    dias_adelante = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Días máximos de anticipación")
    max_reservas_cliente_dia = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Reservas activas por cliente en el mismo día (vacío = 1)"
    )
    colchon_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Minutos libres entre una reserva y la siguiente en la misma mesa")
    telefono = models.CharField(max_length=30, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nombre"]
        permissions = [
            ("manage_branches", "Puede administrar/visualizar todas las sucursales"),
        ]
        indexes = [
            models.Index(fields=["pais"]),
            models.Index(fields=["timezone"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nombre"], name="uniq_sucursal_nombre_por_empresa"),
        ]

    def __str__(self):
        return self.nombre

    def tz(self):
        try:
            return ZoneInfo(self.timezone) if self.timezone else ZoneInfo("UTC")
        except Exception:
            return ZoneInfo("UTC")

    # --- Reglas efectivas (sucursal > settings) ---
    _REGLAS = {
        "hora_apertura": ("HORARIO_APERTURA", 8),
        "hora_cierre": ("HORARIO_CIERRE", 22),
        "intervalo_min": ("RESERVA_INTERVALO_MIN", 15),
        "duracion_min": ("RESERVA_DURACION_MIN_NORM", 90),
        "duracion_pico_min": ("RESERVA_DURACION_MIN_PICO", 105),
        "tolerancia_min": ("CHECKIN_TOLERANCIA_MIN", 5),
        "max_personas": ("CAP_MAX", 12),
        "dias_adelante": ("RESERVAS_MAX_DIAS_ADELANTE", 30),
        "max_reservas_cliente_dia": ("RESERVAS_MAX_POR_CLIENTE_DIA", 1),
        "colchon_min": ("RESERVA_COLCHON_MIN", 0),
    }

    def regla(self, nombre: str) -> int:
        val = getattr(self, nombre, None)
        if val not in (None, ""):
            return int(val)
        setting, default = self._REGLAS[nombre]
        return int(getattr(settings, setting, default))


class SucursalFoto(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="fotos")
    imagen = models.ImageField(upload_to="sucursales/galeria/")
    alt = models.CharField(max_length=120, blank=True)
    orden = models.PositiveIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)
    admins = models.ManyToManyField(User, related_name="sucursales_admin", blank=True)

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.sucursal} · {self.alt or self.imagen.name}"


class Mesa(models.Model):
    ESTADOS = [
        ("disponible", _("Disponible")),
        ("reservada", _("Reservada")),
        ("ocupada", _("Ocupada")),
    ]
    ZONAS = [
        ("interior", _("Interior")),
        ("terraza", _("Terraza")),
        ("exterior", _("Exterior")),
    ]

    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="mesas")
    numero = models.PositiveIntegerField()
    capacidad = models.PositiveIntegerField(default=4)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="disponible")
    zona = models.CharField(max_length=20, choices=ZONAS, default="interior", db_index=True)
    pos_x = models.PositiveSmallIntegerField(default=0, help_text="Porcentaje X 0..100")
    pos_y = models.PositiveSmallIntegerField(default=0, help_text="Porcentaje Y 0..100")
    ubicacion = models.CharField(max_length=100, blank=True, null=True)
    notas = models.TextField(blank=True, null=True)
    bloqueada = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sucursal", "numero"], name="uniq_mesa_por_sucursal"),
        ]
        ordering = ["sucursal", "numero"]

    def __str__(self):
        from django.utils.translation import gettext
        return gettext("Mesa %(n)s - %(s)s") % {"n": self.numero, "s": self.sucursal.nombre}


class Cliente(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True, null=True, validators=[cp_mx_validator])
    # Consentimiento (LFPDPPP)
    acepto_privacidad_en = models.DateTimeField(null=True, blank=True)
    acepta_promociones = models.BooleanField(default=False)

    def __str__(self):
        return self.nombre


class PerfilAdmin(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfiladmin")
    sucursal_asignada = models.ForeignKey(Sucursal, on_delete=models.CASCADE, null=True, blank=True, related_name="admins_principales")

    def __str__(self):
        return f"Perfil de {self.user}"


class BloqueoMesa(models.Model):
    sucursal = models.ForeignKey("Sucursal", on_delete=models.CASCADE, related_name="bloqueos")
    mesa = models.ForeignKey("Mesa", on_delete=models.CASCADE, null=True, blank=True, related_name="bloqueos")
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    motivo = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    objects = OwnedBySucursalQuerySet.as_manager()

    class Meta:
        verbose_name = "Bloqueo de mesa"
        verbose_name_plural = "Bloqueos de mesa"
        ordering = ["-inicio"]
        indexes = [
            models.Index(fields=["sucursal", "inicio"]),
            models.Index(fields=["sucursal", "fin"]),
            models.Index(fields=["inicio", "fin"]),
        ]

    def clean(self):
        if self.fin <= self.inicio:
            raise ValidationError("El fin debe ser mayor que el inicio.")

    def __str__(self):
        scope = f"Mesa {self.mesa.numero}" if self.mesa_id else "Sucursal completa"
        return f"{scope}: {self.inicio:%Y-%m-%d %H:%M} → {self.fin:%H:%M}"


# ===== Menú legado (si lo sigues usando) =====

class MenuCategoria(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="menu_categorias")
    titulo = models.CharField(max_length=120)
    orden = models.PositiveIntegerField(default=0)

    objects = OwnedBySucursalQuerySet.as_manager()

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.sucursal.nombre} · {self.titulo}"


class MenuItem(models.Model):
    categoria = models.ForeignKey(MenuCategoria, on_delete=models.CASCADE, related_name="items")
    nombre = models.CharField(max_length=140)
    desc = models.TextField(blank=True, default="")
    precio = models.DecimalField(max_digits=8, decimal_places=2)  # MXN
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["categoria__orden", "orden", "id"]

    def __str__(self):
        return f"{self.nombre} (${self.precio})"


class Review(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="reviews_obj")
    autor = models.CharField(max_length=120)
    rating = models.PositiveSmallIntegerField()  # 1..5
    texto = models.TextField(blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)

    objects = OwnedBySucursalQuerySet.as_manager()

    class Meta:
        ordering = ["-creado", "id"]

    def __str__(self):
        return f"{self.sucursal.nombre} · {self.autor} ({self.rating}/5)"

# ==============================================================
# Signals auxiliares
# ==============================================================

def _recompute_rating(sucursal: "Sucursal"):
    agg = Review.objects.filter(sucursal=sucursal).aggregate(avg=Avg("rating"), cnt=Count("id"))
    sucursal.rating = round((agg["avg"] or 0), 2)
    sucursal.reviews = agg["cnt"] or 0
    sucursal.save(update_fields=["rating", "reviews"])


@receiver(post_save, sender=Review)
def _rev_saved(sender, instance, **kwargs):
    _recompute_rating(instance.sucursal)


@receiver(post_delete, sender=Review)
def _rev_deleted(sender, instance, **kwargs):
    _recompute_rating(instance.sucursal)


def _unique_slugify(instance, value, slug_field_name: str = "slug", max_length: int = 255):
    base = slugify(value)[:max_length].strip("-")
    if not base:
        base = "sucursal"
    slug = base
    Model = instance.__class__
    i = 2
    qs = Model.objects.exclude(pk=instance.pk)
    while qs.filter(**{slug_field_name: slug}).exists():
        suf = f"-{i}"
        slug = (base[: max_length - len(suf)] + suf).strip("-")
        i += 1
    return slug


@receiver(pre_save, sender=Sucursal)
def sucursal_autoslug(sender, instance: "Sucursal", **kwargs):
    if not instance.slug:
        instance.slug = _unique_slugify(instance, instance.nombre)
        return
    if instance.pk:
        try:
            anterior = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            anterior = None
        if anterior and anterior.nombre != instance.nombre:
            instance.slug = _unique_slugify(instance, instance.nombre)


# ==============================================================
# RESERVAS (UTC + locales)
# ==============================================================

class Reserva(models.Model):
    PEND = "PEND"
    CONF = "CONF"
    CANC = "CANC"
    NOSH = "NOSH"
    ESTADOS = [
        (PEND, _("Pendiente")),
        (CONF, _("Confirmada")),
        (CANC, _("Cancelada")),
        (NOSH, _("No llegó")),
    ]

    cliente = models.ForeignKey("Cliente", on_delete=models.CASCADE)
    mesa = models.ForeignKey("Mesa", on_delete=models.CASCADE)

    sucursal = models.ForeignKey(
        "Sucursal", on_delete=models.CASCADE, related_name="reservas", null=True, blank=True
    )

    # LEGADO: fecha local
    fecha = models.DateTimeField()

    # Nuevos campos
    inicio_utc = models.DateTimeField(null=True, blank=True, db_index=True)
    fin_utc = models.DateTimeField(null=True, blank=True)
    local_service_date = models.DateField(null=True, blank=True, db_index=True)
    local_inicio = models.DateTimeField(null=True, blank=True)
    local_fin = models.DateTimeField(null=True, blank=True)

    num_personas = models.PositiveSmallIntegerField(default=1)
    estado = models.CharField(max_length=4, choices=ESTADOS, default=PEND)

    folio = models.CharField(max_length=20, unique=True, default=generar_folio, editable=False, db_index=True)

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    llego = models.BooleanField(default=False)
    checkin_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)

    creada_por_staff = models.BooleanField(default=False)
    nombre_contacto = models.CharField(max_length=120, blank=True, default="")
    email_contacto = models.EmailField(blank=True, default="")
    telefono_contacto = models.CharField(max_length=30, blank=True, default="")
    liberada_en = models.DateTimeField(null=True, blank=True, db_index=True)

    # Enlace privado para que el comensal vea/cancele su reserva (y QR de llegada)
    token = models.CharField(max_length=48, unique=True, null=True, blank=True, editable=False)
    notas = models.CharField(max_length=300, blank=True, default="")
    ORIGENES = [("web", "Web"), ("widget", "Widget"), ("staff", _("Personal")), ("walkin", _("Walk-in")), ("api", "API"), ("ia", _("Asistente IA"))]
    origen = models.CharField(max_length=10, choices=ORIGENES, default="web")
    recordatorio_enviado_en = models.DateTimeField(null=True, blank=True)
    cancelada_en = models.DateTimeField(null=True, blank=True)
    cuenta_pedida_en = models.DateTimeField(null=True, blank=True)

    objects = ReservaQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-creado"]
        indexes = [
            models.Index(fields=["cliente", "estado"]),
            models.Index(fields=["fecha"]),
            models.Index(fields=["mesa", "fecha"]),
            models.Index(fields=["sucursal", "fecha"]),
            models.Index(fields=["inicio_utc"]),
            models.Index(fields=["local_service_date"]),
        ]

    def __str__(self):
        try:
            suc = self.sucursal.nombre if self.sucursal_id else self.mesa.sucursal.nombre
            dt_show = self.local_inicio or self.fecha
            return f"{self.folio} - Mesa {self.mesa.numero} ({suc}) - {dt_show:%Y-%m-%d %H:%M}"
        except Exception:
            return f"{self.folio} - {self.fecha}"

    def clean(self):
        if getattr(self, "cliente_id", None) is None:
            raise ValidationError({"cliente": "La reserva requiere un cliente (no puede ser nulo)."})
        if getattr(settings, "USE_TZ", False):
            for f in self._meta.fields:
                if isinstance(f, models.DateTimeField):
                    val = getattr(self, f.attname, None)
                    if val and is_naive(val):
                        raise ValidationError({f.name: "Debe ser timezone-aware con USE_TZ=True."})

    def fin_teorico(self, party: Optional[int] = None):
        p = int(party or getattr(self, "num_personas", 2) or 2)
        base_dt = self.local_inicio or self.fecha
        mins = int(booking_total_minutes(base_dt, p))
        return base_dt + timedelta(minutes=mins)

    def fin_efectivo(self, party: Optional[int] = None):
        """
        Hasta cuándo ocupa la mesa:
          - si ya se liberó, hasta la liberación;
          - si el grupo sigue sentado y ya se pasó de su tiempo, se considera ocupada un rato más
            (10 min si pidió la cuenta, 20 si no) para no asignar una mesa que sigue ocupada;
          - si no, hasta el fin calculado al reservar (incluye el colchón de la sucursal).
        """
        ft = self.local_fin or self.fin_teorico(party)
        lib = getattr(self, "liberada_en", None)
        if lib and lib >= (self.local_inicio or self.fecha):
            return min(ft, lib)
        if getattr(self, "llego", False) and not lib:
            ahora = timezone.now()
            inicio = self.local_inicio or self.fecha
            # solo cuenta como "sigue sentado" dentro del mismo servicio (6 h); datos viejos sin liberar no bloquean
            if ft <= ahora and inicio and ahora - inicio < timedelta(hours=6):
                extra = 10 if getattr(self, "cuenta_pedida_en", None) else 20
                return ahora + timedelta(minutes=extra)
        return ft

    def set_from_local(self, local_inicio_naive: datetime, dur_minutes: int):
        if not self.sucursal_id and self.mesa_id:
            self.sucursal_id = self.mesa.sucursal_id

        tz = self.sucursal.tz()
        local_dt = local_inicio_naive.replace(tzinfo=tz)
        self.local_inicio = local_dt
        self.local_fin = local_dt + timedelta(minutes=dur_minutes)
        self.local_service_date = local_dt.date()
        self.inicio_utc = local_dt.astimezone(ZoneInfo("UTC"))
        self.fin_utc = self.local_fin.astimezone(ZoneInfo("UTC"))
        self.fecha = local_dt

    def materialize_from_utc(self):
        if not self.inicio_utc:
            return
        tz = self.sucursal.tz()
        li = self.inicio_utc.astimezone(tz)
        self.local_inicio = li
        self.local_fin = self.fin_utc.astimezone(tz) if self.fin_utc else None
        self.local_service_date = li.date()
        self.fecha = li

    @property
    def empresa(self):
        suc = self.sucursal if self.sucursal_id else (self.mesa.sucursal if self.mesa_id else None)
        return suc.empresa if suc else None

    def save(self, *args, **kwargs):
        validate = kwargs.pop("validate", True)
        if not self.sucursal_id and self.mesa_id:
            self.sucursal_id = self.mesa.sucursal_id
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        if self._state.adding:
            for _ in range(5):  # evita choques de folio (muy raros, pero posibles)
                if not Reserva.objects.filter(folio=self.folio).exists():
                    break
                self.folio = generar_folio()
        if validate:
            self.full_clean()
        return super().save(*args, **kwargs)


class CountryAdminScope(models.Model):
    empresa = models.ForeignKey("Empresa", on_delete=models.CASCADE, null=True, blank=True, related_name="country_scopes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="country_scopes")
    pais  = models.ForeignKey("Pais", on_delete=models.CASCADE, related_name="country_admins")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("empresa", "user", "pais")
        verbose_name = "Ámbito de país (admin)"
        verbose_name_plural = "Ámbitos de país (admins)"

    def __str__(self):
        return f"{self.user} @ {self.pais}"


# ==============================================================
# Agente de IA: conversaciones con comensales
# ==============================================================
class ConversacionIA(models.Model):
    CANALES = [("web", _("Chat web")), ("whatsapp", "WhatsApp")]

    empresa = models.ForeignKey("Empresa", on_delete=models.CASCADE, related_name="conversaciones_ia")
    canal = models.CharField(max_length=10, choices=CANALES, default="web")
    contacto = models.CharField(max_length=80, db_index=True, help_text="Teléfono o identificador de sesión")
    nombre = models.CharField(max_length=120, blank=True)
    mensajes = models.JSONField(default=list, blank=True, help_text="Historial en formato de la API")
    reservas = models.ManyToManyField("Reserva", blank=True, related_name="conversaciones_ia")
    tokens_entrada = models.PositiveIntegerField(default=0)
    tokens_salida = models.PositiveIntegerField(default=0)
    requiere_humano = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-actualizado"]
        indexes = [models.Index(fields=["empresa", "canal", "contacto"])]
        verbose_name = "Conversación con IA"
        verbose_name_plural = "Conversaciones con IA"

    def __str__(self):
        return f"{self.get_canal_display()} {self.contacto} · {self.empresa}"

    def transcript(self):
        """Mensajes legibles (solo texto de cliente y asistente)."""
        out = []
        for m in self.mensajes or []:
            content = m.get("content")
            if isinstance(content, str):
                out.append((m["role"], content))
                continue
            for b in content or []:
                if b.get("type") == "text" and b.get("text"):
                    out.append((m["role"], b["text"]))
        return out



class ListaEspera(models.Model):
    """Clientes que llegan sin reservación y esperan mesa (con aviso por WhatsApp)."""
    ESPERANDO, AVISADO, SENTADO, SE_FUE = "esperando", "avisado", "sentado", "se_fue"
    ESTADOS = [(ESPERANDO, _("Esperando")), (AVISADO, _("Avisado")), (SENTADO, _("Sentado")), (SE_FUE, _("Se fue"))]

    sucursal = models.ForeignKey("Sucursal", on_delete=models.CASCADE, related_name="lista_espera")
    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=30, blank=True)
    personas = models.PositiveSmallIntegerField(default=2)
    notas = models.CharField(max_length=200, blank=True)
    espera_estimada_min = models.PositiveSmallIntegerField(default=15)
    estado = models.CharField(max_length=10, choices=ESTADOS, default=ESPERANDO, db_index=True)
    creado = models.DateTimeField(auto_now_add=True)
    avisado_en = models.DateTimeField(null=True, blank=True)
    sentado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["creado"]
        verbose_name = "Lista de espera"
        verbose_name_plural = "Lista de espera"

    def __str__(self):
        return f"{self.nombre} ({self.personas}) · {self.sucursal_id}"

    @property
    def minutos_esperando(self):
        from django.utils import timezone as _tz
        return int((_tz.now() - self.creado).total_seconds() // 60)



class PerfilSucursal(models.Model):
    """
    Lo que la IA aprendió de UNA sucursal (se recalcula cada noche con `aprender_sucursales`).
    No es un modelo de lenguaje: son estadísticas y un modelo de riesgo propios de esta sucursal.
    """
    sucursal = models.OneToOneField("Sucursal", on_delete=models.CASCADE, related_name="perfil_ia")
    usar_aprendizaje = models.BooleanField(
        default=False, help_text="Usar los tiempos aprendidos al calcular la disponibilidad")
    duraciones = models.JSONField(default=dict, blank=True)
    riesgo = models.JSONField(default=dict, blank=True)
    demanda = models.JSONField(default=dict, blank=True)
    sugerencias = models.JSONField(default=list, blank=True)
    prior_dueno = models.JSONField(default=dict, blank=True, help_text="Respuestas del dueño en el asistente de alta")
    metricas = models.JSONField(default=dict, blank=True)
    muestras = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=0)
    calculado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Perfil IA de sucursal"
        verbose_name_plural = "Perfiles IA de sucursal"

    def __str__(self):
        return f"IA · {self.sucursal} (v{self.version})"


class Prospecto(models.Model):
    """Restaurantes interesados que dejaron sus datos en la página de ventas."""
    NUEVO, CONTACTADO, DEMO, CLIENTE, DESCARTADO = "nuevo", "contactado", "demo", "cliente", "descartado"
    ESTADOS = [(NUEVO, _("Nuevo")), (CONTACTADO, _("Contactado")), (DEMO, _("Demo agendada")),
               (CLIENTE, _("Cliente")), (DESCARTADO, _("Descartado"))]

    nombre = models.CharField(max_length=120)
    restaurante = models.CharField(max_length=150)
    telefono = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    ciudad = models.CharField(max_length=80, blank=True)
    sucursales = models.PositiveSmallIntegerField(default=1)
    mensaje = models.CharField(max_length=500, blank=True)
    origen = models.CharField(max_length=40, default="web")
    estado = models.CharField(max_length=12, choices=ESTADOS, default=NUEVO, db_index=True)
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"{self.restaurante} ({self.nombre})"



class AccesoSoporte(models.Model):
    """
    Acceso temporal y auditado del operador de la plataforma a UNA empresa (modo soporte).
    Sin un acceso vigente, el operador no ve sucursales, reservas ni clientes de ningún restaurante.
    """
    DURACION_MIN = 60

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="accesos_soporte")
    empresa = models.ForeignKey("Empresa", on_delete=models.CASCADE, related_name="accesos_soporte")
    motivo = models.CharField(max_length=300)
    inicio = models.DateTimeField(auto_now_add=True)
    expira = models.DateTimeField()
    cerrado_en = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-inicio"]
        verbose_name = _("Acceso de soporte")
        verbose_name_plural = _("Accesos de soporte")

    def __str__(self):
        return f"{self.user} → {self.empresa} ({self.inicio:%Y-%m-%d %H:%M})"

    @property
    def vigente(self):
        return self.cerrado_en is None and self.expira > timezone.now()
