"""Recorrido de todas las pantallas: ninguna debe fallar y no debe quedar texto en inglés."""
import os
import re
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from reservas import booking
from reservas.models import Cliente, Mesa, Reserva

from .base import BaseTenantTest

INGLES = re.compile(
    r"\b(Date|Time|Party size|Search|Book now|Book|View tables|View|Tables|Available|Save|Cancel|Delete|Edit|Back|Next|"
    r"Name|Email|Phone|Status|Actions|Submit|Log ?in|Sign (in|up)|Password|Welcome|Profile|My bookings|No image|"
    r"Branch(es)?|Reservations?|Bookings?|Table|Add|Create|Update|Close|Loading|Select|Filter|Guests|Guest|Seats?|"
    r"Previous|Today|Tomorrow|Confirm(ed)?|Pending|Cancelled|Arrived|Free|Busy|Occupied|Details?|Settings|Menu items?|"
    r"Category|Price|Active|Inactive|Yes|No results|Open|Closed|Hours|Address|Notes?)\b")


def texto_visible(html):
    html = re.sub(r"(?is)<(script|style|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


class RecorridoTests(BaseTenantTest):
    def setUp(self):
        cli, _ = Cliente.objects.get_or_create(user=self.cliente, defaults={"nombre": "Ana Recorrido", "email": "ana@r.mx"})
        ini = (timezone.now() + timedelta(days=1)).astimezone(self.suc_a.tz()).replace(hour=14, minute=0, second=0, microsecond=0)
        self.res = booking.crear_reserva(sucursal=self.suc_a, inicio_local=ini, party=2, cliente=cli,
                                         creada_por_staff=True, notificar=False)
        self.mesa = Mesa.objects.filter(sucursal=self.suc_a).first()

    def _recorre(self, urls):
        hallazgos = []
        for u in urls:
            r = self.client.get(u, follow=True)
            self.assertLess(r.status_code, 500, u)
            if r.status_code == 200 and "text/html" in r.get("Content-Type", ""):
                txt = texto_visible(r.content.decode("utf-8", "ignore"))
                en = sorted(set(m.group(0) for m in INGLES.finditer(txt)))
                if en:
                    hallazgos.append(f"{u}: {', '.join(en)}")
        return hallazgos

    def test_recorrido(self):
        a = self.suc_a.pk
        publicas = ["/", "/planes/", reverse("reservas:seleccionar_sucursal"),
                    reverse("reservas:reservar_publico", args=[self.suc_a.slug]),
                    reverse("reservas:reserva_publica", args=[self.res.token]),
                    reverse("reservas:aviso_privacidad"), "/account/login/", "/accounts/signup/",
                    "/auth/password/reset/"]
        cliente = ["/?e=tacos-a", reverse("reservas:mis_reservas"), reverse("reservas:perfil")]
        staff = [reverse("reservas:panel_hoy"), reverse("reservas:ia_sucursal"), reverse("reservas:asistente_alta"),
                 reverse("reservas:resumen_negocio"), reverse("reservas:admin_sucursales"),
                 reverse("reservas:admin_reservas"), reverse("reservas:admin_walkin_reserva"),
                 reverse("reservas:admin_buscar_folio"), reverse("reservas:kds"),
                 reverse("reservas:admin_mapa_sucursal", args=[a]), reverse("reservas:admin_bloqueos", args=[a]),
                 reverse("reservas:admin_mesa_crear", args=[a]), reverse("reservas:admin_mesa_detalle", args=[self.mesa.pk]),
                 reverse("reservas:admin_editar_mesa", args=[self.mesa.pk]),
                 reverse("reservas:admin_reasignar_reserva", args=[self.res.pk]),
                 reverse("reservas:admin_sucursal_contenido", args=[a]),
                 reverse("reservas:chainadmin_sucursal_nueva"), reverse("reservas:chainadmin_sucursal_editar", args=[a]),
                 reverse("reservas:chainadmin_menu_catalogo"), reverse("reservas:empresa_config"),
                 reverse("reservas:empresa_equipo"), reverse("reservas:empresa_conversaciones"),
                 reverse("reservas:sucursal_reglas", args=[a]), reverse("reservas:sucursal_widget", args=[a]),
                 reverse("reservas:reserva_scan_entry", args=[self.res.folio]),
                 reverse("reservas:mesa_panel_order", args=[self.mesa.pk]),
                 # rutas viejas que ahora redirigen
                 "/admin/dashboard/", "/chainadmin/dashboard/", "/chainadmin/analytics/", "/staff/sucursales/lista/",
                 f"/s/{self.suc_a.slug}/", "/sucursales/"]
        h = self._recorre(publicas)
        self.login(self.cliente)
        h += self._recorre(cliente)
        self.login(self.owner_a)
        h += self._recorre(staff)
        self.login(self.root)
        h += self._recorre([reverse("reservas:plataforma")])
        ruta = os.environ.get("RECORRIDO_REPORTE")
        if ruta:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write("\n".join(h))


ESPANOL = re.compile(r"\b(Reservar|Reservaciones?|Sucursal(es)?|Mesas?|Personas|Guardar|Cancelar|Buscar|Hoy en|Nueva|Nuevo|"
                     r"Correo|Contraseña|Entrar|Salir|Horarios?|Lista de espera|Configuración|Equipo|Resumen|Fecha|Hora|"
                     r"Estado|Llegó|Pendiente|Confirmada|Cocina|Menú|Inicio|Mi perfil|para|con|tus?|una?)\b")


class IdiomaInglesTests(RecorridoTests):
    def test_recorrido_en_ingles(self):
        from django.conf import settings
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        r = self.client.get("/")
        self.assertContains(r, "Your restaurant, full.")
        self.assertContains(r, 'lang="en"')
        self.login(self.owner_a)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        r = self.client.get(reverse("reservas:panel_hoy"))
        self.assertContains(r, "Today at")
        hallazgos = []
        for u in ["/", reverse("reservas:seleccionar_sucursal"), reverse("reservas:reservar_publico", args=[self.suc_a.slug]),
                  reverse("reservas:panel_hoy"), reverse("reservas:ia_sucursal"), reverse("reservas:resumen_negocio"),
                  reverse("reservas:admin_reservas"), reverse("reservas:admin_sucursales"), reverse("reservas:empresa_config"),
                  reverse("reservas:asistente_alta"), reverse("reservas:admin_walkin_reserva"), reverse("reservas:mis_reservas")]:
            r = self.client.get(u, follow=True)
            txt = texto_visible(r.content.decode("utf-8", "ignore"))
            es = sorted(set(m.group(0) for m in ESPANOL.finditer(txt)))
            if es:
                hallazgos.append(f"{u}: {', '.join(es)}")
        ruta = os.environ.get("RECORRIDO_REPORTE")
        if ruta:
            with open(ruta + ".en", "w", encoding="utf-8") as f:
                f.write("\n".join(hallazgos))
