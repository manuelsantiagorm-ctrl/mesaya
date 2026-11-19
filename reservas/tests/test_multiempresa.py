from django.urls import reverse

from reservas import tenancy
from reservas.booking import crear_reserva
from reservas.models import Cliente, Reserva, Sucursal
from reservas.models_menu import CatalogCategory, CatalogItem

from .base import BaseTenantTest


class AislamientoTests(BaseTenantTest):
    def setUp(self):
        cli = Cliente.objects.create(nombre="Ana", email="ana@x.mx", telefono="5512345678")
        self.res_b = crear_reserva(sucursal=self.suc_b, inicio_local=self.manana(14, suc=self.suc_b),
                                   party=2, cliente=cli, notificar=False)

    def test_tenancy_sucursales(self):
        self.assertEqual(list(tenancy.sucursales_for_user(self.owner_a)), [self.suc_a])
        self.assertEqual(list(tenancy.sucursales_for_user(self.staff_a)), [self.suc_a])
        self.assertFalse(tenancy.sucursales_for_user(self.root).exists())  # el operador no ve restaurantes sin modo soporte
        self.root._soporte_empresa_id = self.emp_b.pk
        self.assertEqual(list(tenancy.sucursales_for_user(self.root)), [self.suc_b])
        del self.root._soporte_empresa_id
        self.assertFalse(tenancy.sucursales_for_user(self.cliente).exists())

    def test_dueno_a_no_ve_reserva_de_b(self):
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:admin_buscar_folio") + f"?folio={self.res_b.folio}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "No se encontró")
        self.assertNotContains(r, "ana@x.mx")
        r = self.client.get(reverse("reservas:reserva_scan_entry", args=[self.res_b.folio]))
        self.assertEqual(r.status_code, 404)

    def test_dueno_a_no_abre_mapa_de_b(self):
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:admin_mapa_sucursal", args=[self.suc_b.id]))
        self.assertIn(r.status_code, (403, 404))
        r = self.client.get(reverse("reservas:admin_mapa_sucursal", args=[self.suc_a.id]))
        self.assertEqual(r.status_code, 200)

    def test_checkin_de_otra_empresa_bloqueado(self):
        self.login(self.staff_a)
        r = self.client.post(reverse("reservas:reserva_checkin", args=[self.res_b.folio]))
        self.assertEqual(r.status_code, 404)
        self.res_b.refresh_from_db()
        self.assertFalse(self.res_b.llego)

    def test_cliente_no_entra_a_dashboard_de_dueno(self):
        self.login(self.cliente)
        r = self.client.get(reverse("reservas:chainadmin_dashboard_country"))
        self.assertIn(r.status_code, (302, 403))

    def test_dashboard_dueno_solo_cuenta_su_empresa(self):
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:chainadmin_dashboard_country"), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["kpi"]["total"], 0)
        self.assertEqual([s["sucursal__nombre"] for s in r.context["top_suc"]], [])

    def test_listado_sucursales_por_empresa(self):
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:chainadmin_sucursales"), follow=True)
        self.assertEqual([s.pk for s in r.context["sucursales"]], [self.suc_a.pk])

    def test_crear_sucursal_queda_en_mi_empresa(self):
        self.login(self.owner_a)
        r = self.client.post(reverse("reservas:chainadmin_sucursal_nueva"), {
            "nombre": "Norte", "pais": self.mx.pk, "timezone": "America/Mexico_City",
            "recepcion_x": 3, "recepcion_y": 3, "precio_nivel": 1, "activo": "on",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        self.assertEqual(Sucursal.objects.get(nombre="Norte").empresa, self.emp_a)

    def test_mismo_nombre_en_dos_empresas(self):
        self.assertEqual(self.suc_a.nombre, self.suc_b.nombre)  # permitido entre empresas

    def test_menu_aislado(self):
        cat_b = CatalogCategory.objects.create(empresa=self.emp_b, nombre="Pizzas")
        CatalogItem.objects.create(empresa=self.emp_b, categoria=cat_b, codigo="P1", nombre="Hawaiana", precio=100)
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:chainadmin_menu_catalogo"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Hawaiana")

    def test_admins_list_aislada(self):
        self.login(self.owner_b)
        r = self.client.get(reverse("reservas:chainadmin_admins"), follow=True)
        self.assertNotContains(r, "staff_a")

    def test_admin_django_solo_superusuario(self):
        self.login(self.owner_a)
        r = self.client.get("/admin/")
        self.assertNotEqual(r.status_code, 200)

    def test_config_empresa(self):
        self.login(self.owner_a)
        r = self.client.post(reverse("reservas:empresa_config"), {
            "nombre": "Tacos A Renovado", "color_primario": "#AA0000", "color_secundario": "#111111",
            "recordatorio_horas": 3, "whatsapp_habilitado": "on", "agente_ia_modo": "reservar", "agente_ia_activo": "on",
        })
        self.assertEqual(r.status_code, 302)
        self.emp_a.refresh_from_db()
        self.assertEqual(self.emp_a.nombre, "Tacos A Renovado")
        self.assertTrue(self.emp_a.agente_ia_activo)
        self.login(self.staff_a)
        r = self.client.get(reverse("reservas:empresa_config"))
        self.assertRedirects(r, reverse("reservas:staff_inicio"), fetch_redirect_response=False)

    def test_reglas_sucursal_ajena(self):
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:sucursal_reglas", args=[self.suc_b.id]))
        self.assertEqual(r.status_code, 404)
        r = self.client.get(reverse("reservas:sucursal_reglas", args=[self.suc_a.id]))
        self.assertEqual(r.status_code, 200)

    def test_marca_en_paginas_publicas(self):
        r = self.client.get(reverse("reservas:reservar_publico", args=[self.suc_a.slug]))
        self.assertContains(r, "Tacos A")
        self.assertNotContains(r, "IHOP")

    def test_empresa_inactiva_no_recibe_reservas(self):
        self.emp_b.activa = False
        self.emp_b.save()
        r = self.client.get(reverse("reservas:reservar_publico", args=[self.suc_b.slug]))
        self.assertEqual(r.status_code, 404)
