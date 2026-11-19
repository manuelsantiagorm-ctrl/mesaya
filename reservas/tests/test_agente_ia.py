"""Pruebas del asistente de IA con un cliente falso (no llama a la API real)."""
import hashlib
import hmac
import json
from types import SimpleNamespace

from django.test import override_settings
from django.urls import reverse

from reservas.agente_ia import AgenteNoDisponible, AgenteReservas, conversacion_para
from reservas.models import ConversacionIA, Empresa, Reserva

from .base import BaseTenantTest


class _Bloque(dict):
    def model_dump(self, exclude_none=True):
        return dict(self)


class ClienteFalso:
    """Devuelve respuestas guionadas y guarda lo que recibió."""

    def __init__(self, guion):
        self.guion = list(guion)
        self.llamadas = []
        self.messages = self

    def create(self, **kw):
        self.llamadas.append(kw)
        bloques = [_Bloque(b) for b in self.guion.pop(0)]
        return SimpleNamespace(content=bloques, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def tool(nombre, args, i="t1"):
    return {"type": "tool_use", "id": i, "name": nombre, "input": args}


def texto(t):
    return {"type": "text", "text": t}


def resultado(falso, tool_id):
    """Lo que el sistema devolvió a la IA para una llamada de herramienta."""
    for m in falso.llamadas[-1]["messages"]:
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("tool_use_id") == tool_id:
                    return json.loads(b["content"])
    raise AssertionError("sin resultado para " + tool_id)


@override_settings(ANTHROPIC_API_KEY="sk-prueba", WHATSAPP_APP_SECRET="secreto", WHATSAPP_VERIFY_TOKEN="verifica")
class AgenteTests(BaseTenantTest):
    def setUp(self):
        self.emp_a.agente_ia_activo = True
        self.emp_a.save()
        self.conv = ConversacionIA.objects.create(empresa=self.emp_a, canal="whatsapp", contacto="525512345678")

    def test_consulta_y_reserva_con_las_reglas_del_sistema(self):
        fecha = self.manana().date().isoformat()
        falso = ClienteFalso([
            [tool("consultar_disponibilidad", {"sucursal": self.suc_a.slug, "fecha": fecha, "personas": 4, "hora_preferida": "14:00"})],
            [tool("crear_reserva", {"sucursal": self.suc_a.slug, "fecha": fecha, "hora": "14:00", "personas": 4, "nombre": "Ana"}, "t2")],
            [texto("¡Listo Ana! Tu mesa quedó para mañana a las 2:00 p.m.")],
        ])
        resp = AgenteReservas(self.conv, client=falso).responder("mesa para 4 mañana a las 2")
        self.assertIn("Listo", resp)
        r = Reserva.objects.get()
        self.assertEqual((r.origen, r.estado, r.num_personas, r.telefono_contacto), ("ia", "CONF", 4, "525512345678"))
        self.assertEqual(r.inicio_utc.astimezone(self.suc_a.tz()).hour, 14)
        # La IA recibió opciones reales (mesa de 4) del sistema
        res = resultado(falso, "t1")
        self.assertTrue(res["opciones"])
        self.assertEqual(res["opciones"][0]["hora"], "14:00")
        self.assertEqual(res["opciones"][0]["capacidad"], 4)
        self.conv.refresh_from_db()
        self.assertEqual(self.conv.tokens_entrada, 300)
        self.assertIn(r, self.conv.reservas.all())

    def test_no_puede_reservar_mesa_ocupada(self):
        fecha = self.manana().date().isoformat()
        falso = ClienteFalso(
            [[tool("crear_reserva", {"sucursal": self.suc_a.slug, "fecha": fecha, "hora": "14:00", "personas": 4, "nombre": f"C{i}"}, f"t{i}")],
             [texto("ok")]] for i in range(3)
        )
        falso.guion = [x for par in falso.guion for x in par]
        ag = AgenteReservas(self.conv, client=falso)
        for i in range(3):
            self.conv.contacto = f"52551234000{i}"
            ag.responder("reserva")
        self.assertEqual(Reserva.objects.count(), 2)  # solo hay 2 mesas de 4
        ultimo = resultado(falso, "t2")
        self.assertFalse(ultimo["ok"])
        self.assertIn("No hay mesas", ultimo["error"])

    def test_no_ve_sucursales_de_otra_empresa(self):
        falso = ClienteFalso([
            [tool("consultar_disponibilidad", {"sucursal": self.suc_b.slug, "fecha": self.manana().date().isoformat(), "personas": 2})],
            [texto("No encontré esa sucursal")],
        ])
        AgenteReservas(self.conv, client=falso).responder("en pizzas b")
        res = resultado(falso, "t1")
        self.assertFalse(res["ok"])
        self.assertNotIn(self.suc_b.slug, falso.llamadas[0]["system"])

    def test_modo_proponer_deja_pendiente(self):
        self.emp_a.agente_ia_modo = Empresa.IA_MODO_PROPONER
        self.emp_a.save()
        self.conv.empresa.refresh_from_db()
        falso = ClienteFalso([
            [tool("crear_reserva", {"sucursal": self.suc_a.slug, "fecha": self.manana().date().isoformat(), "hora": "13:00", "personas": 2, "nombre": "Leo"})],
            [texto("Tu solicitud quedó registrada")],
        ])
        AgenteReservas(self.conv, client=falso).responder("reserva")
        self.assertEqual(Reserva.objects.get().estado, Reserva.PEND)

    def test_solo_cancela_sus_reservas(self):
        from reservas.booking import crear_reserva
        from reservas.models import Cliente
        otro = Cliente.objects.create(nombre="Otro", telefono="5599990000")
        ajena = crear_reserva(sucursal=self.suc_a, inicio_local=self.manana(), party=2, cliente=otro,
                              telefono_contacto="525599990000", notificar=False)
        falso = ClienteFalso([[tool("cancelar_reserva", {"folio": ajena.folio})], [texto("No es tuya")]])
        AgenteReservas(self.conv, client=falso).responder(f"cancela {ajena.folio}")
        ajena.refresh_from_db()
        self.assertEqual(ajena.estado, Reserva.CONF)

    def test_apagado_por_el_dueno(self):
        self.emp_a.agente_ia_activo = False
        self.emp_a.save()
        self.conv.empresa.refresh_from_db()
        with self.assertRaises(AgenteNoDisponible):
            AgenteReservas(self.conv, client=ClienteFalso([])).responder("hola")
        r = self.client.get(reverse("reservas:asistente_chat", args=[self.emp_a.slug]))
        self.assertEqual(r.status_code, 404)

    def test_pedir_humano(self):
        falso = ClienteFalso([[tool("pedir_humano", {"motivo": "Evento de 40 personas"})], [texto("Te contactamos")]])
        AgenteReservas(self.conv, client=falso).responder("evento para 40")
        self.conv.refresh_from_db()
        self.assertTrue(self.conv.requiere_humano)

    def test_chat_web(self):
        r = self.client.get(reverse("reservas:asistente_chat", args=[self.emp_a.slug]))
        self.assertEqual(r.status_code, 200)
        from unittest import mock
        with mock.patch("reservas.views_agente.AgenteReservas.responder", return_value="¡Hola!"):
            r = self.client.post(reverse("reservas:asistente_mensaje", args=[self.emp_a.slug]),
                                 data=json.dumps({"mensaje": "hola"}), content_type="application/json")
        self.assertEqual(r.json(), {"ok": True, "respuesta": "¡Hola!"})
        self.assertEqual(ConversacionIA.objects.filter(canal="web").count(), 1)

    def _post_wa(self, cuerpo, firma=True):
        raw = json.dumps(cuerpo).encode()
        headers = {}
        if firma:
            headers["HTTP_X_HUB_SIGNATURE_256"] = "sha256=" + hmac.new(b"secreto", raw, hashlib.sha256).hexdigest()
        return self.client.post(reverse("reservas:whatsapp_webhook"), data=raw, content_type="application/json", **headers)

    def test_webhook_whatsapp(self):
        self.emp_a.whatsapp_phone_number_id = "111"
        self.emp_a.save()
        r = self.client.get(reverse("reservas:whatsapp_webhook"),
                            {"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "42"})
        self.assertEqual(r.content, b"42")
        cuerpo = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "111"},
            "contacts": [{"wa_id": "5215512345678", "profile": {"name": "Ana"}}],
            "messages": [{"id": "wamid.1", "from": "5215512345678", "type": "text", "text": {"body": "hola"}}],
        }}]}]}
        self.assertEqual(self._post_wa(cuerpo, firma=False).status_code, 403)
        from unittest import mock
        with mock.patch("reservas.views_agente.AgenteReservas.responder", return_value="¡Hola Ana!") as m, \
             mock.patch("reservas.views_agente.enviar_texto_whatsapp") as env:
            self.assertEqual(self._post_wa(cuerpo).status_code, 200)
            self._post_wa(cuerpo)  # reintento de Meta: no se contesta dos veces
        self.assertEqual(m.call_count, 1)
        env.assert_called_once_with("525512345678", "¡Hola Ana!", "111")
        conv = ConversacionIA.objects.get(canal="whatsapp", contacto="525512345678", empresa=self.emp_a)
        self.assertEqual(conv.nombre, "Ana")

    def test_panel_conversaciones_aislado(self):
        ConversacionIA.objects.create(empresa=self.emp_b, canal="web", contacto="web-b", nombre="Cliente de B")
        self.login(self.owner_a)
        r = self.client.get(reverse("reservas:empresa_conversaciones"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Cliente de B")
