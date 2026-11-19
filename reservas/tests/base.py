from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from reservas.models import Empresa, Mesa, MiembroEmpresa, Pais, Sucursal

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RATELIMIT_ENABLE=False,
    SECURE_SSL_REDIRECT=False,
    WHATSAPP_TOKEN="",
)
class BaseTenantTest(TestCase):
    """Dos empresas (A y B) con una sucursal y 3 mesas cada una."""

    @classmethod
    def setUpTestData(cls):
        cls.mx, _ = Pais.objects.get_or_create(iso2="MX", defaults={"nombre": "México"})
        cls.emp_a = Empresa.objects.create(nombre="Tacos A", slug="tacos-a", whatsapp_habilitado=True)
        cls.emp_b = Empresa.objects.create(nombre="Pizzas B", slug="pizzas-b")
        cls.suc_a = Sucursal.objects.create(
            empresa=cls.emp_a, nombre="Centro", pais=cls.mx, timezone="America/Mexico_City",
            hora_apertura=0, hora_cierre=24, max_personas=10,
        )
        cls.suc_b = Sucursal.objects.create(
            empresa=cls.emp_b, nombre="Centro", pais=cls.mx, timezone="America/Mexico_City",
            hora_apertura=0, hora_cierre=24,
        )
        for s in (cls.suc_a, cls.suc_b):
            s.mesas.all().delete()
            for n, cap in ((1, 2), (2, 4), (3, 4)):
                Mesa.objects.create(sucursal=s, numero=n, capacidad=cap)

        cls.owner_a = cls._user("owner_a", staff=True)
        MiembroEmpresa.objects.create(empresa=cls.emp_a, user=cls.owner_a, rol=MiembroEmpresa.OWNER)
        cls.owner_b = cls._user("owner_b", staff=True)
        MiembroEmpresa.objects.create(empresa=cls.emp_b, user=cls.owner_b, rol=MiembroEmpresa.OWNER)
        cls.staff_a = cls._user("staff_a", staff=True)
        MiembroEmpresa.objects.create(empresa=cls.emp_a, user=cls.staff_a, rol=MiembroEmpresa.STAFF)
        cls.suc_a.administradores.add(cls.staff_a)
        cls.root = cls._user("root", staff=True, su=True)
        cls.cliente = cls._user("cliente")

    @staticmethod
    def _user(name, staff=False, su=False):
        return User.objects.create_user(
            username=name, email=f"{name}@test.mx", password="Clave-Prueba-123", is_staff=staff, is_superuser=su
        )

    def login(self, user):
        self.client.force_login(user)
        if user.is_staff:
            dev, _ = TOTPDevice.objects.get_or_create(user=user, name="t", defaults={"confirmed": True})
            s = self.client.session
            s[DEVICE_ID_SESSION_KEY] = dev.persistent_id
            s.save()

    def manana(self, h=14, m=0, suc=None):
        tz = (suc or self.suc_a).tz()
        d = (timezone.now().astimezone(tz) + timedelta(days=1)).date()
        return timezone.make_aware(datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m), tz)
