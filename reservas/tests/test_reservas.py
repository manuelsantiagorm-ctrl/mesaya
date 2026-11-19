from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from reservas import booking
from reservas.models import Cliente, Reserva

from .base import BaseTenantTest


class BookingTests(BaseTenantTest):
    def cli(self, n="Luis"):
        return Cliente.objects.create(nombre=n, email=f"{n.lower()}@x.mx", telefono="5511112222")

    def test_asigna_mesa_minima(self):
        r = booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=2, cliente=self.cli(), notificar=False)
        self.assertEqual(r.mesa.capacidad, 2)
        self.assertEqual(r.sucursal, self.suc_a)
        self.assertTrue(r.token)

    def test_sin_mesas_da_error_amable_con_alternativas(self):
        for i in range(3):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=2,
                                  cliente=self.cli(f"C{i}"), notificar=False)
        with self.assertRaises(booking.NoDisponible) as ctx:
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=2, cliente=self.cli("X"), notificar=False)
        self.assertTrue(ctx.exception.alternativas)
        self.assertTrue(all(a != self.manana() for a in ctx.exception.alternativas))

    def test_limite_por_cliente_mismo_dia(self):
        c = self.cli()
        booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(13), party=2, cliente=c, notificar=False)
        with self.assertRaises(booking.ReservaError):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(19), party=2, cliente=c, notificar=False)

    def test_grupo_mayor_al_maximo(self):
        with self.assertRaises(booking.ReservaError):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=11, cliente=self.cli(), notificar=False)

    def test_horario_pasado(self):
        with self.assertRaises(booking.ReservaError):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=timezone.now() - timedelta(hours=1),
                                  party=2, cliente=self.cli(), notificar=False)

    def test_fuera_de_horario(self):
        self.suc_a.hora_apertura, self.suc_a.hora_cierre = 8, 22
        self.suc_a.save()
        with self.assertRaises(booking.ReservaError):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(23), party=2, cliente=self.cli(), notificar=False)

    def test_slots_coinciden_con_asignacion(self):
        dia = self.manana().date()
        antes = booking.slots_disponibles(self.suc_a, dia, 4)
        self.assertIn(self.manana(), antes)
        for i in range(2):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=4, cliente=self.cli(f"G{i}"), notificar=False)
        despues = booking.slots_disponibles(self.suc_a, dia, 4)
        self.assertNotIn(self.manana(), despues)

    def test_bloqueo_de_mesa_respetado(self):
        from reservas.models import BloqueoMesa
        BloqueoMesa.objects.create(sucursal=self.suc_a, mesa=None, inicio=self.manana(12), fin=self.manana(16), motivo="Evento")
        with self.assertRaises(booking.NoDisponible):
            booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(14), party=2, cliente=self.cli(), notificar=False)


class FlujoPublicoTests(BaseTenantTest):
    def datos(self, **kw):
        d = {
            "fecha": self.manana().date().isoformat(), "hora": "14:00", "party": 2,
            "nombre": "María López", "telefono": "55 1234 5678", "email": "maria@x.mx",
            "notas": "Cumpleaños", "acepto_privacidad": "on",
        }
        d.update(kw)
        return d

    def test_reserva_sin_cuenta(self):
        url = reverse("reservas:reservar_publico", args=[self.suc_a.slug])
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(url, self.datos())
        self.assertEqual(r.status_code, 302)
        res = Reserva.objects.get(nombre_contacto="María López")
        self.assertIn(res.token, r["Location"])
        self.assertEqual(res.origen, "web")
        self.assertIsNotNone(res.cliente.acepto_privacidad_en)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Tacos A", mail.outbox[0].alternatives[0][0])
        # Página del enlace privado
        r = self.client.get(reverse("reservas:reserva_publica", args=[res.token]))
        self.assertContains(r, res.folio)
        r = self.client.get(reverse("reservas:reserva_ics", args=[res.token]))
        self.assertContains(r, "BEGIN:VCALENDAR")
        r = self.client.get(reverse("reservas:reserva_qr", args=[res.token]))
        self.assertEqual(r["Content-Type"], "image/svg+xml")

    def test_sin_aceptar_privacidad_no_reserva(self):
        url = reverse("reservas:reservar_publico", args=[self.suc_a.slug])
        r = self.client.post(url, self.datos(acepto_privacidad=""))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Reserva.objects.exists())

    def test_sin_mesa_muestra_mensaje_no_500(self):
        url = reverse("reservas:reservar_publico", args=[self.suc_a.slug])
        for i in range(3):
            self.client.post(url, self.datos(nombre=f"P{i}", email=f"p{i}@x.mx", telefono=f"55000000{i}0"))
        r = self.client.post(url, self.datos(nombre="Tarde", email="t@x.mx"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "No hay mesas disponibles")

    def test_cancelar_desde_enlace(self):
        url = reverse("reservas:reservar_publico", args=[self.suc_a.slug])
        self.client.post(url, self.datos())
        res = Reserva.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("reservas:reserva_publica_cancelar", args=[res.token]))
        self.assertEqual(r.status_code, 302)
        res.refresh_from_db()
        self.assertEqual(res.estado, Reserva.CANC)
        self.assertTrue(any("cancelada" in m.subject.lower() for m in mail.outbox))

    def test_api_horarios(self):
        r = self.client.get(reverse("reservas:api_slots_publico", args=[self.suc_a.slug]),
                            {"fecha": self.manana().date().isoformat(), "party": 2})
        self.assertEqual(r.status_code, 200)
        self.assertIn("14:00", [s["value"] for s in r.json()["slots"]])

    def test_widget_embebible(self):
        r = self.client.get(reverse("reservas:reservar_publico", args=[self.suc_a.slug]) + "?embed=1")
        self.assertNotIn("X-Frame-Options", r.headers)
        self.assertContains(r, "embed-mode")

    def test_rutas_viejas_redirigen_al_flujo_nuevo(self):
        r = self.client.post(reverse("reservas:reservar_auto", args=[self.suc_a.id]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("reservas:reservar_publico", args=[self.suc_a.slug]), r["Location"])
        r = self.client.get(reverse("reservas:sucursal_detalle", args=[self.suc_a.slug]) + "?date=2030-01-01&party=4")
        self.assertIn("fecha=2030-01-01", r["Location"])

    def test_privacidad(self):
        r = self.client.get(reverse("reservas:aviso_privacidad_empresa", args=[self.emp_a.slug]))
        self.assertContains(r, "Derechos ARCO")


class RecordatoriosTests(BaseTenantTest):
    def test_recordatorio_una_sola_vez(self):
        c = Cliente.objects.create(nombre="Eva", email="eva@x.mx", telefono="5599998888")
        r = booking.crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=2, cliente=c, notificar=False)
        Reserva.objects.filter(pk=r.pk).update(creado=timezone.now() - timedelta(days=3))
        self.emp_a.recordatorio_horas = 48
        self.emp_a.save()
        call_command("enviar_recordatorios", verbosity=0)
        call_command("enviar_recordatorios", verbosity=0)
        r.refresh_from_db()
        self.assertIsNotNone(r.recordatorio_enviado_en)
        self.assertEqual(sum("Te esperamos" in m.subject for m in mail.outbox), 1)

    def test_telefono_mx(self):
        from reservas.notificaciones import normalizar_telefono
        self.assertEqual(normalizar_telefono("55 1234 5678"), "525512345678")
        self.assertEqual(normalizar_telefono("+52 1 55 1234 5678"), "525512345678")


class PantallasStaffTests(BaseTenantTest):
    """Las pantallas que antes daban error 500."""
    def test_pantallas_staff(self):
        self.login(self.owner_a)
        urls = [
            reverse("reservas:admin_reservas"),
            reverse("reservas:admin_bloqueos", args=[self.suc_a.id]),
            reverse("reservas:admin_mesa_crear", args=[self.suc_a.id]),
            reverse("reservas:chainadmin_sucursales"),
            reverse("reservas:chainadmin_admins"),
            reverse("reservas:chainadmin_admins_all"),
            reverse("reservas:chainadmin_country_admins_all"),
            reverse("reservas:chainadmin_dashboard_country"),
            reverse("reservas:staff_sucursales"),
            reverse("reservas:sucursales_grid"),
            reverse("reservas:empresa_equipo"),
            reverse("reservas:sucursal_widget", args=[self.suc_a.id]),
            reverse("reservas:admin_dashboard"),
            reverse("reservas:admin_walkin_reserva"),
        ]
        for u in urls:
            with self.subTest(url=u):
                self.assertEqual(self.client.get(u, follow=True).status_code, 200)

    def test_crear_mesa(self):
        self.login(self.owner_a)
        r = self.client.post(reverse("reservas:admin_mesa_crear", args=[self.suc_a.id]),
                             {"numero": 20, "capacidad": 6, "zona": "terraza"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.suc_a.mesas.filter(numero=20, capacidad=6).exists())

    def test_agregar_miembro_al_equipo(self):
        self.login(self.owner_a)
        r = self.client.post(reverse("reservas:empresa_equipo"), {
            "email": "nuevo@tacos.mx", "nombre": "Nuevo", "rol": "staff",
            "sucursales": [self.suc_a.id], "password": "Otra-Clave-Larga-987",
        })
        self.assertEqual(r.status_code, 302)
        from reservas import tenancy
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.get(email="nuevo@tacos.mx")
        self.assertEqual(list(tenancy.sucursales_for_user(u)), [self.suc_a])

    def test_home_publica_sin_login(self):
        r = self.client.get(reverse("reservas:home"))
        self.assertEqual(r.status_code, 200)
