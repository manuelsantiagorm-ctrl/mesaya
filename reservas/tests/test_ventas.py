from django.urls import reverse

from reservas.models import Empresa, Prospecto

from .base import BaseTenantTest


class VentasTests(BaseTenantTest):
    def test_landing_para_visitante(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Tu restaurante lleno")
        self.assertContains(r, 'id="calculadora"')

    def test_con_empresa_se_ve_la_home_del_restaurante(self):
        r = self.client.get("/?e=tacos-a")
        self.assertNotContains(r, "Tu restaurante lleno")

    def test_solicitar_demo(self):
        r = self.client.post(reverse("reservas:solicitar_demo"), {
            "nombre": "Luis", "restaurante": "Tacos El Güero", "telefono": "55 1234 5678",
            "sucursales": 2, "ciudad": "CDMX", "mensaje": "Quiero WhatsApp"})
        self.assertEqual(r.status_code, 302)
        p = Prospecto.objects.get()
        self.assertEqual(p.telefono, "5512345678")
        # trampa para bots
        self.client.post(reverse("reservas:solicitar_demo"), {"nombre": "x", "restaurante": "x",
                                                              "telefono": "5512345678", "sucursales": 1, "website": "spam"})
        self.assertEqual(Prospecto.objects.count(), 1)
        # teléfono inválido
        r = self.client.post(reverse("reservas:solicitar_demo"), {"nombre": "a", "restaurante": "b", "telefono": "12", "sucursales": 1})
        self.assertEqual(r.status_code, 200)

    def test_panel_plataforma_solo_superadmin(self):
        Prospecto.objects.create(nombre="A", restaurante="R", telefono="5512345678")
        self.login(self.owner_a)
        self.assertEqual(self.client.get(reverse("reservas:plataforma")).status_code, 403)
        self.login(self.root)
        r = self.client.get(reverse("reservas:plataforma"))
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("reservas:plataforma_pago", args=[self.emp_a.pk]), {"meses": 3})
        self.assertIsNotNone(Empresa.objects.get(pk=self.emp_a.pk).pagado_hasta)
