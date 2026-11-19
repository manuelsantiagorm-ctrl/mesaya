"""
Matriz de aislamiento entre empresas.

Recorre TODAS las rutas de la app con los ids de la empresa A (sucursal, mesa, reserva, empresa,
folio, token...) y las llama por GET y POST como: dueño de otra empresa, comensal, anónimo y el
operador de la plataforma SIN modo soporte. Ninguno debe ver datos de A ni poder cambiarlos.
"""
import itertools
from datetime import timedelta

from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone

from reservas import booking
from reservas.models import AccesoSoporte, Cliente, Mesa, Reserva

from .base import BaseTenantTest

SECRETO_NOMBRE = "Ana Secreta Zúñiga"
SECRETO_TEL = "5559876543"
SECRETO_MAIL = "ana.secreta@privado.mx"

# Rutas que por diseño son públicas con el folio/token (el comensal recibe ese enlace)
PUBLICAS_CON_TOKEN = {"reserva_publica", "reserva_publica_cancelar", "reserva_ics", "reserva_scan_entry"}


def _patrones(resolver=None, prefijo="", ns=""):
    resolver = resolver or get_resolver()
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            sub_ns = p.namespace or ns
            yield from _patrones(p, prefijo + str(p.pattern), sub_ns)
        elif isinstance(p, URLPattern):
            yield ns, p.name, prefijo + str(p.pattern), p


class AislamientoTests(BaseTenantTest):
    def setUp(self):
        cli, _n = Cliente.objects.get_or_create(user=self.cliente)
        cli.nombre, cli.email, cli.telefono = SECRETO_NOMBRE, SECRETO_MAIL, SECRETO_TEL
        cli.save()
        ini = (timezone.now() + timedelta(days=1)).astimezone(self.suc_a.tz()).replace(hour=14, minute=0, second=0, microsecond=0)
        self.res = booking.crear_reserva(sucursal=self.suc_a, inicio_local=ini, party=2, cliente=cli,
                                         creada_por_staff=True, notificar=False)
        self.mesa = Mesa.objects.filter(sucursal=self.suc_a).first()

    # ---------- utilidades ----------
    def _ids(self):
        return [self.suc_a.pk, self.mesa.pk, self.res.pk, self.emp_a.pk, self.cliente.pk]

    def _valores(self, k, tipo):
        if k == "sucursal_id":
            return [self.suc_a.pk]
        if k == "mesa_id":
            return [self.mesa.pk]
        if k == "reserva_id":
            return [self.res.pk]
        if k == "user_id":
            return [self.staff_a.pk, self.cliente.pk]
        if k == "slug":
            return [self.suc_a.slug, self.emp_a.slug]
        if k == "token":
            return [str(self.res.token)]
        if k == "folio":
            return [self.res.folio]
        if k == "accion":
            return ["cancelar", "confirmar", "llego", "sentar", "cuenta", "liberar", "no_show"]
        if tipo == "IntConverter":  # pk genérico: probamos todos los ids de A
            return self._ids()
        return [self.res.folio]

    def _urls(self):
        """Todas las rutas de 'reservas' con parámetros rellenados con datos de A."""
        out = []
        for ns, name, _ruta, p in _patrones():
            if ns != "reservas" or not name:
                continue
            conv = p.pattern.converters
            if not conv:
                out.append((name, reverse(f"reservas:{name}")))
                continue
            opciones = [[(k, v) for v in self._valores(k, type(c).__name__)] for k, c in conv.items()]
            for combo in itertools.product(*opciones):
                try:
                    out.append((name, reverse(f"reservas:{name}", kwargs=dict(combo))))
                except Exception:
                    pass
        return out

    def _estado_a(self):
        r = Reserva.objects.get(pk=self.res.pk)
        return (r.estado, r.mesa_id, r.fecha, r.llego, r.party_size if hasattr(r, "party_size") else None,
                Mesa.objects.filter(sucursal=self.suc_a).count(),
                tuple(Mesa.objects.filter(sucursal=self.suc_a).values_list("capacidad", flat=True).order_by("pk")),
                self.suc_a.__class__.objects.get(pk=self.suc_a.pk).nombre,
                self.emp_a.__class__.objects.get(pk=self.emp_a.pk).nombre)

    def _sin_fuga(self, quien):
        fugas = []
        antes = self._estado_a()
        for name, url in self._urls():
            if name in PUBLICAS_CON_TOKEN:
                continue
            for metodo in ("get", "post"):
                r = getattr(self.client, metodo)(url, {"estado": "CANC", "nombre": "HACKEADO", "capacidad": 99,
                                                       "mesa_id": self.mesa.pk, "accion": "cancelar"})
                self.assertNotIn(r.status_code, (500, 502), f"{quien} {metodo} {url}")  # 503 = asistente sin clave de IA en pruebas
                body = r.content.decode("utf-8", "ignore") if r.status_code == 200 else ""
                for s in (SECRETO_NOMBRE, SECRETO_TEL, SECRETO_MAIL, self.res.folio):
                    if s in body:
                        fugas.append(f"{quien} {metodo.upper()} {url} -> {s}")
        self.assertEqual(fugas, [], "\n".join(fugas))
        self.assertEqual(self._estado_a(), antes, f"{quien} modificó datos de la empresa A")

    # ---------- matriz ----------
    def test_dueno_de_otra_empresa(self):
        self.login(self.owner_b)
        self._sin_fuga("owner_b")

    def test_comensal(self):
        # el comensal SÍ es dueño de esta reserva: debe poder verla en "mis reservas", nada más.
        self.login(self.cliente)
        r = self.client.get(reverse("reservas:mis_reservas"))
        self.assertContains(r, self.res.folio)
        otro = self._user("otro_comensal")
        self.login(otro)
        self._sin_fuga("otro_comensal")

    def test_anonimo(self):
        self._sin_fuga("anonimo")

    def test_operador_sin_soporte_no_ve_restaurantes(self):
        self.login(self.root)
        self._sin_fuga("operador")
        r = self.client.get(reverse("reservas:plataforma"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, SECRETO_NOMBRE)

    def test_operador_no_ve_comensales_en_admin(self):
        self.login(self.root)
        r = self.client.get("/admin/auth/user/")
        if r.status_code == 200:
            b = r.content.decode()
            i = b.find("cliente@test.mx")
            self.assertEqual(i, -1, b[max(0, i - 400):i + 100])
        for modelo in ("reserva", "cliente", "sucursal", "mesa", "conversacionia"):
            self.assertIn(self.client.get(f"/admin/reservas/{modelo}/").status_code, (302, 403, 404))

    # ---------- modo soporte ----------
    def test_modo_soporte_auditado(self):
        self.login(self.root)
        url = reverse("reservas:soporte_entrar", args=[self.emp_a.pk])
        # sin motivo: no entra
        self.client.post(url, {"motivo": ""})
        self.assertFalse(AccesoSoporte.objects.exists())
        r = self.client.post(url, {"motivo": "El dueño pidió ayuda con horarios"})
        self.assertRedirects(r, reverse("reservas:panel_hoy"), fetch_redirect_response=False)
        acc = AccesoSoporte.objects.get()
        self.assertEqual(acc.empresa, self.emp_a)
        r = self.client.get(reverse("reservas:admin_reservas"))
        self.assertContains(r, SECRETO_NOMBRE)
        self.assertContains(r, "Modo soporte")
        # en soporte de A no ve B
        r = self.client.get(reverse("reservas:admin_mapa_sucursal", args=[self.suc_b.pk]), follow=True)
        self.assertNotEqual(r.status_code, 500)
        self.assertNotIn(self.suc_b.pk, list(__import__("reservas.tenancy", fromlist=["x"]).sucursal_ids_for_user(r.wsgi_request.user)))
        # el dueño ve el acceso en su bitácora
        self.client.post(reverse("reservas:soporte_salir"))
        self.assertIsNotNone(AccesoSoporte.objects.get().cerrado_en)
        r = self.client.get(reverse("reservas:admin_reservas"))
        self.assertNotContains(r, SECRETO_NOMBRE, status_code=r.status_code)
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:empresa_config"))
        self.assertContains(r, "El dueño pidió ayuda con horarios")

    def test_soporte_expira(self):
        self.login(self.root)
        self.client.post(reverse("reservas:soporte_entrar", args=[self.emp_a.pk]), {"motivo": "revisión de una falla"})
        AccesoSoporte.objects.update(expira=timezone.now() - timedelta(minutes=1))
        r = self.client.get(reverse("reservas:admin_reservas"))
        self.assertNotContains(r, SECRETO_NOMBRE, status_code=r.status_code)

    def test_soporte_solo_para_el_operador(self):
        self.login(self.owner_b)
        r = self.client.post(reverse("reservas:soporte_entrar", args=[self.emp_a.pk]), {"motivo": "quiero ver a la competencia"})
        self.assertIn(r.status_code, (302, 403, 404))
        self.assertFalse(AccesoSoporte.objects.exists())
        # aunque alguien plante el id en la sesión, el middleware lo ignora si no es suyo
        self.login(self.root)
        self.client.post(reverse("reservas:soporte_entrar", args=[self.emp_a.pk]), {"motivo": "acceso legítimo"})
        acc = AccesoSoporte.objects.get()
        self.login(self.owner_b)
        s = self.client.session
        s["acceso_soporte_id"] = acc.pk
        s.save()
        r = self.client.get(reverse("reservas:admin_reservas"))
        self.assertNotContains(r, SECRETO_NOMBRE)
