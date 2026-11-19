from datetime import datetime, timedelta

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from reservas import booking
from reservas.models import Cliente, Empresa, ListaEspera, Reserva, Sucursal

from .base import BaseTenantTest


class PanelHoyTests(BaseTenantTest):
    def _reserva(self, suc, mins=0):
        cli = Cliente.objects.create(nombre="Ana Prueba", email="ana@x.mx")
        ini = (timezone.now() + timedelta(minutes=mins)).astimezone(suc.tz()).replace(second=0, microsecond=0)
        return booking.crear_reserva(sucursal=suc, inicio_local=ini, party=2, cliente=cli,
                                     creada_por_staff=True, notificar=False)

    def test_hoy_muestra_reservas_de_mi_sucursal(self):
        self._reserva(self.suc_a)
        self.login(self.staff_a)
        r = self.client.get(reverse("reservas:panel_hoy"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ana Prueba")

    def test_accion_llego_y_noshow(self):
        res = self._reserva(self.suc_a)
        self.login(self.staff_a)
        self.client.post(reverse("reservas:panel_reserva_accion", args=[res.pk, "llego"]))
        res.refresh_from_db()
        self.assertTrue(res.llego)
        self.client.post(reverse("reservas:panel_reserva_accion", args=[res.pk, "noshow"]))
        res.refresh_from_db()
        self.assertEqual(res.estado, Reserva.NOSH)

    def test_no_puedo_tocar_reservas_de_otra_empresa(self):
        res = self._reserva(self.suc_b)
        self.login(self.staff_a)
        r = self.client.post(reverse("reservas:panel_reserva_accion", args=[res.pk, "cancelar"]))
        self.assertEqual(r.status_code, 403)
        res.refresh_from_db()
        self.assertNotEqual(res.estado, Reserva.CANC)

    def test_lista_de_espera(self):
        self.login(self.staff_a)
        self.client.post(reverse("reservas:espera_agregar"), {"s": self.suc_a.pk, "nombre": "Karla", "personas": 3, "telefono": "5512345678"})
        e = ListaEspera.objects.get(nombre="Karla")
        self.assertEqual(e.sucursal, self.suc_a)
        self.client.post(reverse("reservas:espera_accion", args=[e.pk, "avisar"]))
        e.refresh_from_db()
        self.assertEqual(e.estado, ListaEspera.AVISADO)
        self.client.post(reverse("reservas:espera_accion", args=[e.pk, "sentar"]))
        e.refresh_from_db()
        self.assertEqual(e.estado, ListaEspera.SENTADO)
        # otra empresa no puede
        self.login(self.owner_b)
        r = self.client.post(reverse("reservas:espera_accion", args=[e.pk, "quitar"]))
        self.assertEqual(r.status_code, 403)

    def test_resumen_solo_dueno(self):
        self._reserva(self.suc_a)
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:resumen_negocio"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["kpi"]["total"], 1)
        self.login(self.staff_a)
        r = self.client.get(reverse("reservas:resumen_negocio"))  # el gerente de sucursal no entra a "Mi negocio"
        self.assertRedirects(r, reverse("reservas:staff_inicio"), fetch_redirect_response=False)

    def test_planes_y_home_publicos(self):
        self.assertEqual(self.client.get(reverse("reservas:planes")).status_code, 200)
        r = self.client.get(reverse("reservas:home"))
        self.assertEqual(r.status_code, 200)


class DemoTests(BaseTenantTest):
    def test_crear_demo(self):
        call_command("crear_demo", "--password", "Demo-Prueba-1", "--dias", "2", verbosity=0)
        emp = Empresa.objects.get(slug="demo")
        self.assertEqual(Sucursal.objects.filter(empresa=emp).count(), 3)
        self.assertGreater(Reserva.objects.filter(sucursal__empresa=emp).count(), 20)
        call_command("crear_demo", "--borrar", "--dias", "1", verbosity=0)
        self.assertEqual(Empresa.objects.filter(slug="demo").count(), 1)
