from datetime import timedelta

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from reservas import aprendizaje, booking, piso
from reservas.models import Cliente, Empresa, PerfilSucursal, Reserva, Sucursal
from reservas.utils import booking_total_minutes

from .base import BaseTenantTest


class AprendizajeTests(BaseTenantTest):
    def _historial(self, suc, mins_reales=50, n=30):
        cli = Cliente.objects.create(nombre="Hist", email="h@x.mx")
        base = timezone.now() - timedelta(days=40)
        for i in range(n):
            ini = (base + timedelta(days=i)).astimezone(suc.tz()).replace(hour=14, minute=0, second=0, microsecond=0)
            r = booking.crear_reserva(sucursal=suc, inicio_local=ini, party=2, cliente=cli,
                                      creada_por_staff=True, notificar=False)
            Reserva.objects.filter(pk=r.pk).update(llego=True, arrived_at=ini,
                                                   liberada_en=ini + timedelta(minutes=mins_reales))

    def test_aprende_duracion_real_por_sucursal(self):
        self._historial(self.suc_a, mins_reales=50)
        p = aprendizaje.aprender(self.suc_a)
        self.assertEqual(p.muestras, 30)
        self.assertEqual(len(p.duraciones), 4 * 3 * 4)
        # el error del tiempo aprendido es menor que el del tiempo fijo
        self.assertLess(p.metricas["error_ia_min"], p.metricas["error_fijo_min"])
        # aislamiento: la sucursal B no aprendió nada de A
        pb = aprendizaje.aprender(self.suc_b)
        self.assertEqual(pb.muestras, 0)

    def test_usar_aprendizaje_cambia_la_duracion_con_limites(self):
        self._historial(self.suc_a, mins_reales=45)
        p = aprendizaje.aprender(self.suc_a)
        dt = timezone.now().astimezone(self.suc_a.tz()).replace(hour=14)
        fijo = booking_total_minutes(dt, 2, Sucursal.objects.get(pk=self.suc_a.pk))
        p.usar_aprendizaje = True
        p.save()
        suc = Sucursal.objects.get(pk=self.suc_a.pk)
        nuevo = booking_total_minutes(dt, 2, suc)
        self.assertGreaterEqual(nuevo, aprendizaje.DUR_MIN)
        self.assertLessEqual(nuevo, aprendizaje.DUR_MAX)
        self.assertLessEqual(nuevo, fijo)

    def test_riesgo_no_show(self):
        cli = Cliente.objects.create(nombre="R", email="r@x.mx")
        ini = (timezone.now() + timedelta(hours=3)).astimezone(self.suc_a.tz())
        r = booking.crear_reserva(sucursal=self.suc_a, inicio_local=ini, party=2, cliente=cli,
                                  creada_por_staff=True, notificar=False)
        aprendizaje.aprender(self.suc_a)
        r = Reserva.objects.select_related("sucursal").get(pk=r.pk)
        p = aprendizaje.riesgo_no_show(r)
        self.assertIsNotNone(p)
        self.assertTrue(0 <= p <= 0.95)


class PisoTests(BaseTenantTest):
    def _res(self, mins, mesa=None, party=2, **upd):
        cli = Cliente.objects.create(nombre=f"C{mins}", email=f"c{mins}@x.mx")
        ini = (timezone.now() + timedelta(minutes=mins)).astimezone(self.suc_a.tz()).replace(second=0, microsecond=0)
        r = booking.crear_reserva(sucursal=self.suc_a, inicio_local=ini, party=party, cliente=cli,
                                  creada_por_staff=True, notificar=False,
                                  mesa_preferida_id=mesa.pk if mesa else None)
        if upd or mesa:
            Reserva.objects.filter(pk=r.pk).update(**({"mesa": mesa} if mesa else {}), **upd)
        return Reserva.objects.select_related("mesa", "sucursal").get(pk=r.pk)

    def test_mesa_excedida_genera_alerta_y_reacomodo(self):
        mesa4 = self.suc_a.mesas.get(numero=2)
        proxima = self._res(5, mesa=mesa4, party=4)
        # grupo sentado hace 2 h en la misma mesa, sin liberar
        self._res(-120, mesa=mesa4, party=4, llego=True, arrived_at=timezone.now() - timedelta(minutes=118))
        al = piso.alertas(self.suc_a)
        self.assertEqual(len(al), 1)
        self.assertEqual(al[0]["reserva"].pk, proxima.pk)
        self.assertIsNotNone(al[0]["alternativa"])
        res = piso.vigilar(self.suc_a)
        self.assertEqual(res["reacomodadas"], 1)
        proxima.refresh_from_db()
        self.assertNotEqual(proxima.mesa_id, mesa4.pk)

    def test_mesa_ocupada_pasada_de_tiempo_no_se_ofrece(self):
        mesa = self.suc_a.mesas.get(numero=1)
        self._res(-150, mesa=mesa, llego=True, arrived_at=timezone.now() - timedelta(minutes=150))
        r = Reserva.objects.filter(mesa=mesa).first()
        self.assertGreater(r.fin_efectivo(), timezone.now())

    def test_no_show_automatico(self):
        r = self._res(-30)
        self.assertEqual(piso.marcar_no_shows(self.suc_a), 1)
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.NOSH)
        llego = self._res(-25, llego=True, arrived_at=timezone.now() - timedelta(minutes=24))
        piso.marcar_no_shows(self.suc_a)
        llego.refresh_from_db()
        self.assertNotEqual(llego.estado, Reserva.NOSH)

    def test_pantallas(self):
        self._res(-40, llego=True, arrived_at=timezone.now() - timedelta(minutes=40))
        self.login(self.owner_a)
        self.assertEqual(self.client.get(reverse("reservas:panel_hoy")).status_code, 200)
        r = self.client.get(reverse("reservas:ia_sucursal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Lo que la IA aprendió")
        self.client.post(reverse("reservas:ia_sucursal"), {"s": self.suc_a.pk, "accion": "activar"})
        self.assertTrue(PerfilSucursal.objects.get(sucursal=self.suc_a).usar_aprendizaje)
        # otra empresa no puede activar la IA de A
        self.login(self.owner_b)
        r = self.client.post(reverse("reservas:ia_sucursal"), {"s": self.suc_a.pk, "accion": "desactivar"})
        self.assertTrue(PerfilSucursal.objects.get(sucursal=self.suc_a).usar_aprendizaje)


class DemoIATests(BaseTenantTest):
    def test_demo_con_aprendizaje_y_en_vivo(self):
        call_command("crear_demo", "--dias", "4", verbosity=0)
        emp = Empresa.objects.get(slug="demo")
        s = Sucursal.objects.filter(empresa=emp).first()
        self.assertTrue(PerfilSucursal.objects.filter(sucursal=s).exists())
        self.assertGreater(len(piso.sentadas(s)), 0)
        call_command("crear_demo", "--en-vivo", verbosity=0)
        self.assertGreater(len(piso.sentadas(s)), 0)


class AsistenteAltaTests(BaseTenantTest):
    def test_respuestas_del_dueno_son_el_punto_de_partida(self):
        self.login(self.owner_a)
        url = reverse("reservas:asistente_alta")
        self.assertEqual(self.client.get(url).status_code, 200)
        r = self.client.post(url, {"s": self.suc_a.pk, "tipo": "rapida", "pareja_semana": 35,
                                   "pareja_finde": 45, "grupo4": 45, "grupo6": 60})
        self.assertEqual(r.status_code, 302)
        p = PerfilSucursal.objects.get(sucursal=self.suc_a)
        self.assertTrue(p.usar_aprendizaje)
        self.assertEqual(p.duraciones["lj|comida|1-2"]["mostrar"], 35)
        suc = Sucursal.objects.get(pk=self.suc_a.pk)
        self.assertEqual(suc.colchon_min, 5)
        # fuera de rango no se guarda
        r = self.client.post(url, {"s": self.suc_a.pk, "tipo": "rapida", "pareja_semana": 5,
                                   "pareja_finde": 45, "grupo4": 45, "grupo6": 60})
        self.assertEqual(r.status_code, 200)

    def test_staff_no_configura(self):
        self.login(self.staff_a)
        self.assertEqual(self.client.get(reverse("reservas:asistente_alta")).status_code, 403)
