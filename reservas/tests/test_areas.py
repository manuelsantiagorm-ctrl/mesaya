"""Áreas de trabajo: cada puesto entra solo a lo suyo."""
from datetime import timedelta

from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from reservas import areas, booking
from reservas.models import Cliente, Mesa, MiembroEmpresa, Reserva
from reservas.models_menu import CatalogCategory, CatalogItem
from reservas.models_orders import Order, OrderItem

from .base import BaseTenantTest


def _nombres(resolver=None, ns=""):
    resolver = resolver or get_resolver()
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            yield from _nombres(p, p.namespace or ns)
        elif isinstance(p, URLPattern) and ns == "reservas" and p.name:
            yield p.name, p


class AreasTests(BaseTenantTest):
    def setUp(self):
        self.gente = {}
        for rol in ("recepcion", "mesero", "cocina", "staff", "admin"):
            u = self._user(f"p_{rol}", staff=True)
            MiembroEmpresa.objects.create(empresa=self.emp_a, user=u, rol=rol)
            if rol in MiembroEmpresa.ROLES_POR_SUCURSAL:
                self.suc_a.administradores.add(u)
            self.gente[rol] = u
        self.gente["owner"] = self.owner_a
        cli, _n = Cliente.objects.get_or_create(user=self.cliente)
        cli.nombre = "Lucía Privada"
        cli.save()
        ini = (timezone.now() + timedelta(days=1)).astimezone(self.suc_a.tz()).replace(hour=14, minute=0, second=0, microsecond=0)
        self.res = booking.crear_reserva(sucursal=self.suc_a, inicio_local=ini, party=2, cliente=cli,
                                         creada_por_staff=True, notificar=False)
        self.mesa = Mesa.objects.filter(sucursal=self.suc_a).first()

    def test_todas_las_rutas_clasificadas(self):
        sin = sorted(n for n, _p in _nombres() if n not in areas.RUTAS and n not in areas.LIBRES)
        self.assertEqual(sin, [], "Rutas sin área: agrégalas a RUTAS o LIBRES en reservas/areas.py")

    def _url(self, name, p):
        kw = {}
        for k in p.pattern.converters:
            kw[k] = {"sucursal_id": self.suc_a.pk, "mesa_id": self.mesa.pk, "reserva_id": self.res.pk,
                     "accion": "cancelar", "order_id": 999999, "orden_id": 999999}.get(k, self.res.pk)
        return reverse(f"reservas:{name}", kwargs=kw)

    def test_matriz_de_puestos(self):
        rutas = dict(_nombres())
        errores = []
        for rol, user in self.gente.items():
            self.login(user)
            mis = areas.ROL_AREAS[rol]
            for name, permitidas in areas.RUTAS.items():
                if mis & permitidas:
                    continue
                try:
                    url = self._url(name, rutas[name])
                except Exception:
                    continue
                r = self.client.get(url)
                ok = r.status_code == 403 or (r.status_code == 302 and r.url == reverse("reservas:staff_inicio"))
                r2 = self.client.post(url, {"x": 1})
                ok = ok and r2.status_code == 403
                if not ok:
                    errores.append(f"{rol} entró a {name} ({r.status_code}/{r2.status_code})")
        self.assertEqual(errores, [], "\n".join(errores))

    def test_cada_quien_llega_a_su_area(self):
        esperado = {"recepcion": "reservas:panel_hoy", "mesero": "reservas:meseros", "cocina": "reservas:kds"}
        for rol, destino in esperado.items():
            self.login(self.gente[rol])
            r = self.client.get(reverse("reservas:staff_inicio"))
            self.assertRedirects(r, reverse(destino), fetch_redirect_response=False)
            self.assertEqual(self.client.get(reverse(destino)).status_code, 200, rol)
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:staff_inicio"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cocina")

    def test_menu_solo_muestra_su_area(self):
        self.login(self.gente["cocina"])
        r = self.client.get(reverse("reservas:kds"))
        self.assertNotContains(r, reverse("reservas:panel_hoy"))
        self.assertNotContains(r, reverse("reservas:empresa_equipo"))
        self.assertNotContains(r, reverse("reservas:meseros"))

    def test_cocina_no_ve_reservas_ni_clientes(self):
        self.login(self.gente["cocina"])
        for url in (reverse("reservas:reserva_detalle", args=[self.res.pk]), reverse("reservas:panel_hoy"),
                    reverse("reservas:admin_reservas")):
            r = self.client.get(url, follow=True)
            self.assertNotContains(r, "Lucía Privada", status_code=r.status_code)

    def test_mesero_solo_cuenta_y_liberar(self):
        self.res.llego = True
        self.res.save()
        self.login(self.gente["mesero"])
        r = self.client.post(reverse("reservas:panel_reserva_accion", args=[self.res.pk, "cancelar"]))
        self.assertEqual(r.status_code, 403)
        self.assertNotEqual(Reserva.objects.get(pk=self.res.pk).estado, Reserva.CANC)
        r = self.client.post(reverse("reservas:panel_reserva_accion", args=[self.res.pk, "cuenta"]), {"next": "meseros"})
        self.assertRedirects(r, reverse("reservas:meseros"), fetch_redirect_response=False)
        self.assertIsNotNone(Reserva.objects.get(pk=self.res.pk).cuenta_pedida_en)

    def test_orden_desde_el_menu_con_precio_del_menu(self):
        cat = CatalogCategory.objects.create(empresa=self.emp_a, nombre="Tacos")
        item = CatalogItem.objects.create(empresa=self.emp_a, categoria=cat, codigo="T1", nombre="Taco al pastor", precio="25.00")
        cat_b = CatalogCategory.objects.create(empresa=self.emp_b, nombre="Pizzas")
        item_b = CatalogItem.objects.create(empresa=self.emp_b, categoria=cat_b, codigo="P1", nombre="Pizza", precio="1.00")
        self.login(self.gente["mesero"])
        r = self.client.get(reverse("reservas:mesa_panel_order", args=[self.mesa.pk]))
        self.assertContains(r, "Taco al pastor")
        self.assertNotContains(r, "Pizza")
        orden = Order.objects.get(mesa=self.mesa)
        self.client.post(reverse("reservas:order_add_item", args=[orden.pk]), {"item_id": item.pk, "precio": "0.01"})
        self.assertEqual(str(OrderItem.objects.get(order=orden).precio_unitario), "25.00")
        r = self.client.post(reverse("reservas:order_add_item", args=[orden.pk]), {"item_id": item_b.pk})
        self.assertFalse(r.json()["ok"])
        it = OrderItem.objects.get(order=orden)
        self.client.post(reverse("reservas:order_item_quitar", args=[orden.pk]), {"item_id": it.pk})
        self.assertTrue(OrderItem.objects.get(pk=it.pk).cancelado)
        self.assertEqual(self.client.get(reverse("reservas:meseros")).status_code, 200)

    def test_equipo_puestos(self):
        self.login(self.owner_a)
        url = reverse("reservas:empresa_equipo")
        self.assertEqual(self.client.get(url).status_code, 200)
        # mesero sin sucursal: no se puede
        r = self.client.post(url, {"nuevo": 1, "nombre": "Pepe", "email": "pepe@x.mx", "password": "Clave-Segura-2026!", "rol": "mesero"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(MiembroEmpresa.objects.filter(user__email="pepe@x.mx").exists())
        self.client.post(url, {"nuevo": 1, "nombre": "Pepe", "email": "pepe@x.mx", "password": "Clave-Segura-2026!",
                               "rol": "mesero", "sucursales": [self.suc_a.pk]})
        m = MiembroEmpresa.objects.get(user__email="pepe@x.mx")
        self.assertEqual(m.rol, "mesero")
        self.assertIn(self.suc_a, m.user.sucursales_que_administra.all())
        # cambiar a cocina
        self.client.post(url, {"editar": m.pk, f"m{m.pk}-rol": "cocina", f"m{m.pk}-sucursales": [self.suc_a.pk]})
        m.refresh_from_db()
        self.assertEqual(m.rol, "cocina")
        # no se puede meter una sucursal de otra empresa
        self.client.post(url, {"editar": m.pk, f"m{m.pk}-rol": "cocina", f"m{m.pk}-sucursales": [self.suc_b.pk]})
        self.assertNotIn(self.suc_b, m.user.sucursales_que_administra.all())
        # el gerente general no puede crear dueños
        self.login(self.gente["admin"])
        self.client.post(url, {"nuevo": 1, "nombre": "X", "email": "x@x.mx", "password": "Clave-Segura-2026!", "rol": "owner"})
        self.assertFalse(MiembroEmpresa.objects.filter(user__email="x@x.mx", rol="owner").exists())
        # recepción no entra a Equipo
        self.login(self.gente["recepcion"])
        r = self.client.get(url)
        self.assertRedirects(r, reverse("reservas:staff_inicio"), fetch_redirect_response=False)

    def test_admin_django_solo_operador(self):
        self.login(self.owner_a)
        r = self.client.get("/admin/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r.url)
