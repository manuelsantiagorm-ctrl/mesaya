"""
Crea un restaurante de demostración con vida: 3 sucursales, mesas por zona, menú,
reservas de los últimos 30 días y de los próximos 7, lista de espera de hoy y
conversaciones del asistente IA. Ideal para enseñar el sistema a un prospecto.

  python manage.py crear_demo --password "Demo-2026!"            # crea demo@demo.mx como dueño
  python manage.py crear_demo --dueno tu@correo.com              # agrega además a un usuario existente
  python manage.py crear_demo --borrar                           # elimina la demo y la vuelve a crear
No envía correos ni WhatsApp.
"""
import random
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from reservas import aprendizaje, booking
from reservas.models import (
    Cliente, ConversacionIA, Empresa, ListaEspera, MiembroEmpresa, Pais, Reserva, Sucursal,
)
from reservas.models_menu import CatalogCategory, CatalogItem

SLUG = "demo"
R = random.Random()
NOMBRES = ["Mariana", "Luis", "Sofía", "Diego", "Valeria", "Jorge", "Fernanda", "Andrés", "Camila", "Ricardo",
           "Daniela", "Emilio", "Paola", "Héctor", "Lucía", "Rodrigo", "Ximena", "Arturo", "Regina", "Pablo",
           "Ana Paula", "Mauricio", "Renata", "Óscar", "Natalia", "Iván", "Alejandra", "Tomás", "Gabriela", "Santiago"]
APELLIDOS = ["García", "Hernández", "López", "Martínez", "Ortiz", "Ramírez", "Flores", "Torres", "Vargas", "Castillo"]
SUCURSALES = [
    ("Centro", "Av. Madero 32, Centro Histórico, CDMX", "06000", "Cocina mexicana", "4.7"),
    ("Polanco", "Av. Presidente Masaryk 210, Polanco, CDMX", "11560", "Mexicana contemporánea", "4.8"),
    ("Condesa", "Av. Tamaulipas 98, Condesa, CDMX", "06140", "Brunch y mariscos", "4.6"),
]
MESAS = [(2, "interior")] * 4 + [(4, "interior")] * 6 + [(4, "terraza")] * 4 + [(6, "terraza")] * 2 + [(8, "interior")]
MENU = {
    "Entradas": [("Guacamole con totopos", 145), ("Tostadas de atún", 189), ("Queso fundido", 155)],
    "Platos fuertes": [("Tacos de rib eye", 265), ("Enchiladas suizas", 195), ("Pescado a la talla", 310), ("Mole poblano", 235)],
    "Postres": [("Churros con chocolate", 110), ("Pastel de elote", 95)],
    "Bebidas": [("Agua de jamaica", 55), ("Margarita", 135), ("Café de olla", 50)],
}


class Command(BaseCommand):
    help = "Crea un restaurante de demostración con datos realistas."

    def add_arguments(self, p):
        p.add_argument("--password", default="Demo-2026!", help="Contraseña de demo@demo.mx y del equipo de demo")
        p.add_argument("--equipo", action="store_true",
                       help="Solo agrega (o repara) el equipo de demo: gerente, recepción, mesero y cocina")
        p.add_argument("--dueno", default="", help="Correo de un usuario existente para agregarlo como dueño")
        p.add_argument("--borrar", action="store_true", help="Elimina la demo anterior antes de crearla")
        p.add_argument("--semilla", type=int, default=7)
        p.add_argument("--dias", type=int, default=30, help="Días de historial a generar")
        p.add_argument("--en-vivo", action="store_true",
                       help="Solo regenera el escenario de 'ahora mismo' (úsalo justo antes de una presentación)")

    def handle(self, *a, **o):
        R.seed(o["semilla"])  # generador propio: no altera los folios aleatorios
        if o.get("en_vivo"):
            emp = Empresa.objects.filter(slug=SLUG).first()
            if not emp:
                self.stdout.write(self.style.ERROR("Primero crea la demo: python manage.py crear_demo"))
                return
            ahora = timezone.now()
            for s in Sucursal.objects.filter(empresa=emp):
                Reserva.objects.filter(sucursal=s, local_inicio__gte=ahora - timedelta(hours=6),
                                       local_inicio__lte=ahora + timedelta(hours=3)).delete()
                self._en_vivo(s)
                aprendizaje.aprender(s)
            self.stdout.write(self.style.SUCCESS("Escenario en vivo listo: abre /staff/hoy/"))
            return
        if o.get("equipo"):
            emp = Empresa.objects.filter(slug=SLUG).first()
            if not emp:
                self.stdout.write(self.style.ERROR("Primero crea la demo: python manage.py crear_demo"))
                return
            self._equipo(emp, list(Sucursal.objects.filter(empresa=emp).order_by("pk")), o["password"])
            return
        if o["borrar"]:
            self._borrar()
        if Empresa.objects.filter(slug=SLUG).exists():
            self.stdout.write(self.style.WARNING("La demo ya existe. Usa --borrar para recrearla."))
            return
        with transaction.atomic():
            emp = self._empresa(o)
            sucs = self._sucursales(emp)
            self._menu(emp)
        total = 0
        for s in sucs:
            total += self._reservas(s, o["dias"])
            self._espera(s)
        self._conversaciones(emp, sucs[0])
        self._equipo(emp, sucs, o["password"])
        for s in sucs:
            p = aprendizaje.aprender(s)
            p.usar_aprendizaje = False
            p.save(update_fields=["usar_aprendizaje"])
        self.stdout.write(self.style.SUCCESS(
            f"Demo lista: {emp.nombre} · {len(sucs)} sucursales · {total} reservas.\n"
            f"  Cliente:  /reservar/{sucs[0].slug}/   Asistente: /asistente/{emp.slug}/\n"
            f"  Personal: /staff/hoy/   Dueño: /staff/resumen/   IA: /staff/ia/   Ventas: /"
        ))

    # ------------------------------------------------------------------
    def _borrar(self):
        emp = Empresa.objects.filter(slug=SLUG).first()
        if not emp:
            return
        sucs = Sucursal.objects.filter(empresa=emp)
        Reserva.objects.filter(sucursal__in=sucs).delete()
        ListaEspera.objects.filter(sucursal__in=sucs).delete()
        Cliente.objects.filter(email__endswith="@demo.mx", user__isnull=True).delete()
        ConversacionIA.objects.filter(empresa=emp).delete()
        for s in sucs:
            s.mesas.all().delete()
        sucs.delete()
        CatalogItem.objects.filter(empresa=emp).delete()
        CatalogCategory.objects.filter(empresa=emp).delete()
        MiembroEmpresa.objects.filter(empresa=emp).delete()
        emp.delete()
        self.stdout.write("Demo anterior eliminada.")

    def _empresa(self, o):
        User = get_user_model()
        emp = Empresa.objects.create(
            nombre="La Terraza", slug=SLUG, plan=Empresa.PLAN_PRO, color_primario="#E4572E", color_secundario="#1E1B18",
            email_contacto="hola@demo.mx", telefono="55 5555 0000", agente_ia_activo=True, agente_ia_modo="reservar",
            agente_ia_instrucciones="Somos un restaurante familiar. Tenemos terraza pet-friendly y menú infantil.",
        )
        owner, creado = User.objects.get_or_create(username="demo@demo.mx", defaults={"email": "demo@demo.mx", "is_staff": True})
        if creado:
            owner.set_password(o["password"])
            owner.save()
        MiembroEmpresa.objects.get_or_create(empresa=emp, user=owner, defaults={"rol": MiembroEmpresa.OWNER})
        if o["dueno"]:
            u = User.objects.filter(email__iexact=o["dueno"]).first()
            if u and u.is_superuser:
                self.stdout.write(self.style.WARNING("El operador de la plataforma no puede ser dueño de un restaurante; se omitió."))
            elif u:
                MiembroEmpresa.objects.get_or_create(empresa=emp, user=u, defaults={"rol": MiembroEmpresa.OWNER})
                if not u.is_staff:
                    u.is_staff = True
                    u.save(update_fields=["is_staff"])
            else:
                self.stdout.write(self.style.WARNING(f"No existe el usuario {o['dueno']}; se omitió."))
        return emp

    def _equipo(self, emp, sucs, password):
        """Una persona por puesto para enseñar que cada quien solo ve su área."""
        User = get_user_model()
        gente = [("gerente@demo.mx", "Gabriela", "Gerente", MiembroEmpresa.STAFF),
                 ("recepcion@demo.mx", "Rocío", "Recepción", MiembroEmpresa.RECEPCION),
                 ("mesero@demo.mx", "Miguel", "Mesero", MiembroEmpresa.MESERO),
                 ("cocina@demo.mx", "Carlos", "Cocina", MiembroEmpresa.COCINA)]
        for email, nombre, apellido, rol in gente:
            u, creado = User.objects.get_or_create(username=email, defaults={
                "email": email, "first_name": nombre, "last_name": apellido, "is_staff": True})
            if creado:
                u.set_password(password)
                u.save()
            MiembroEmpresa.objects.update_or_create(empresa=emp, user=u, defaults={"rol": rol, "activo": True})
            if sucs:
                sucs[0].administradores.add(u)
        self.stdout.write(self.style.SUCCESS(
            "Equipo de demo (misma contraseña que demo@demo.mx): gerente@demo.mx · recepcion@demo.mx · "
            f"mesero@demo.mx · cocina@demo.mx — en {sucs[0].nombre if sucs else '—'}"))

    def _sucursales(self, emp):
        pais, _ = Pais.objects.get_or_create(iso2="MX", defaults={"nombre": "México"})
        out = []
        for i, (nom, dire, cp, cocina, rating) in enumerate(SUCURSALES):
            s = Sucursal.objects.create(
                empresa=emp, nombre=f"La Terraza {nom}", direccion=dire, codigo_postal=cp, cocina=cocina,
                rating=rating, reviews=R.randint(120, 900), recomendado=(i == 1), pais=pais,
                timezone="America/Mexico_City", hora_apertura=8, hora_cierre=23,
            )
            for n, (cap, zona) in enumerate(MESAS, start=1):
                s.mesas.create(numero=n, capacidad=cap, zona=zona, pos_x=8 + (n % 6) * 15, pos_y=10 + (n // 6) * 25)
            out.append(s)
        return out

    def _menu(self, emp):
        k = 0
        for orden, (cat, items) in enumerate(MENU.items()):
            c = CatalogCategory.objects.create(empresa=emp, nombre=cat, orden=orden)
            for nom, precio in items:
                k += 1
                CatalogItem.objects.create(empresa=emp, categoria=c, codigo=f"D{k:03d}", nombre=nom, precio=precio)

    def _cliente(self):
        n, a = R.choice(NOMBRES), R.choice(APELLIDOS)
        email = f"{n.split()[0].lower()}.{a.lower()}{R.randint(1, 60)}@demo.mx".replace("ó", "o").replace("í", "i").replace("é", "e").replace("á", "a")
        c, _ = Cliente.objects.get_or_create(email=email, user=None, defaults={
            "nombre": f"{n} {a}", "telefono": f"55{R.randint(10000000, 99999999)}",
        })
        return c

    # Duración "real" que tendrá cada mesa en la demo (para que la IA tenga algo que aprender)
    @staticmethod
    def _duracion_real(ini, party):
        w, h = ini.weekday(), ini.hour
        base = 50 if h < 12 else (62 if h < 17 else 82)
        if w == 4:
            base += 10
        if w in (5, 6):
            base += 22
        base += {2: 0, 3: 8, 4: 12, 5: 22, 6: 26, 8: 40}.get(party, 15)
        return max(25, int(R.gauss(base, 11)))

    @staticmethod
    def _lead():
        x = R.random()
        if x < 0.40:
            return timedelta(hours=R.randint(1, 20)), 0.03
        if x < 0.75:
            return timedelta(days=R.randint(1, 3), hours=R.randint(0, 12)), 0.05
        if x < 0.90:
            return timedelta(days=R.randint(4, 10)), 0.09
        return timedelta(days=R.randint(11, 30)), 0.19

    def _reservas(self, s, dias=30):
        tz = s.tz()
        hoy = timezone.now().astimezone(tz).date()
        ahora = timezone.now().astimezone(tz)
        horas = [time(9, 0), time(10, 30), time(13, 30), time(14, 0), time(14, 30), time(15, 0), time(15, 30),
                 time(19, 30), time(20, 0), time(20, 30), time(21, 0)]
        pesos = [3, 2, 6, 9, 9, 7, 4, 5, 7, 6, 3]
        origenes = ["web"] * 5 + ["ia"] * 3 + ["widget"] * 2 + ["staff", "walkin"]
        notas = ["", "", "", "Cumpleaños 🎂", "Silla para bebé", "Mesa en terraza por favor", "Aniversario", "Alergia a nueces"]
        n = 0
        for delta in range(-dias, 8):
            dia = hoy + timedelta(days=delta)
            base = 10 if dia.weekday() < 4 else 18
            if delta > 0:
                base = max(2, base // (delta + 1) + 2)
            for _ in range(R.randint(base - 3, base + 3)):
                h = R.choices(horas, weights=pesos)[0]
                ini = datetime.combine(dia, h).replace(tzinfo=tz)
                if delta == 0 and ini > ahora - timedelta(hours=6):
                    continue  # hoy en curso lo arma _en_vivo
                party = R.choices([2, 3, 4, 5, 6, 8], weights=[10, 3, 8, 2, 3, 1])[0]
                origen = R.choice(origenes)
                try:
                    r = booking.crear_reserva(
                        sucursal=s, inicio_local=ini, party=party, cliente=self._cliente(),
                        origen=origen, notas=R.choice(notas), creada_por_staff=True, notificar=False,
                    )
                except booking.ReservaError:
                    continue
                n += 1
                lead, p_ns = self._lead()
                if origen == "walkin":
                    lead, p_ns = timedelta(minutes=2), 0.0
                cambios = {"creado": min(ini - lead, timezone.now())}
                if ini < ahora - timedelta(hours=3):
                    x = R.random()
                    if x < p_ns:
                        cambios.update(estado=Reserva.NOSH, liberada_en=ini + timedelta(minutes=6))
                    elif x < p_ns + 0.07:
                        cambios.update(estado=Reserva.CANC, cancelada_en=ini - timedelta(hours=5))
                    else:
                        llegada = ini + timedelta(minutes=R.randint(-5, 12))
                        cambios.update(llego=True, arrived_at=llegada,
                                       liberada_en=llegada + timedelta(minutes=self._duracion_real(ini, party)))
                elif R.random() < 0.2:
                    cambios["estado"] = Reserva.PEND
                Reserva.objects.filter(pk=r.pk).update(**cambios)
        n += self._en_vivo(s)
        return n

    def _en_vivo(self, s):
        """Escenario 'ahora mismo': mesas comiendo, una excedida con reserva encima y llegadas próximas."""
        tz = s.tz()
        ahora = timezone.now().astimezone(tz).replace(second=0, microsecond=0)
        ahora = ahora - timedelta(minutes=ahora.minute % 5)
        mesas = list(s.mesas.order_by("numero"))
        if len(mesas) < 8:
            return 0
        n = 0

        def nueva(ini, party, mesa, **upd):
            nonlocal n
            try:
                r = booking.crear_reserva(sucursal=s, inicio_local=ini, party=party, cliente=self._cliente(),
                                          origen=R.choice(["web", "ia", "widget"]), creada_por_staff=True,
                                          notificar=False, mesa_preferida_id=mesa.pk)
            except booking.ReservaError:
                return None
            upd.setdefault("creado", ini - timedelta(days=R.randint(0, 3), hours=R.randint(1, 8)))
            Reserva.objects.filter(pk=r.pk).update(mesa=mesa, **upd)
            n += 1
            return r

        cuatro = [m for m in mesas if m.capacidad == 4]
        dos = [m for m in mesas if m.capacidad == 2]
        # 1) Llegadas próximas (una de ellas caerá sobre una mesa que sigue ocupada)
        objetivo = cuatro[0]
        nueva(ahora + timedelta(minutes=25), 4, objetivo)
        nueva(ahora + timedelta(minutes=40), 2, dos[1])
        nueva(ahora + timedelta(minutes=55), 4, cuatro[2])
        nueva(ahora + timedelta(minutes=70), 6, [m for m in mesas if m.capacidad >= 6][0])
        lejana = nueva(ahora + timedelta(minutes=45), 2, dos[2])
        if lejana:
            Reserva.objects.filter(pk=lejana.pk).update(creado=ahora - timedelta(days=18), origen="web")
        # 2) Mesas comiendo ahora (se crean como reservas pasadas y se fuerzan a su mesa)
        for mesa, hace, party, cuenta in [(objetivo, 115, 4, False), (dos[0], 50, 2, True),
                                          (cuatro[1], 35, 3, False), (cuatro[3], 70, 4, False)]:
            ini = ahora - timedelta(minutes=hace)
            try:
                r = booking.crear_reserva(sucursal=s, inicio_local=ini, party=party, cliente=self._cliente(),
                                          origen="web", creada_por_staff=True, notificar=False)
            except booking.ReservaError:
                continue
            Reserva.objects.filter(pk=r.pk).update(
                mesa=mesa, llego=True, arrived_at=ini + timedelta(minutes=3), estado=Reserva.CONF,
                cuenta_pedida_en=(ahora - timedelta(minutes=4)) if cuenta else None,
                creado=ini - timedelta(days=1))
            n += 1
        return n

    def _espera(self, s):
        for nombre, p, mins in [("Familia Ruiz", 6, 25), ("Karla M.", 2, 10), ("Grupo oficina", 8, 4)]:
            e = ListaEspera.objects.create(sucursal=s, nombre=nombre, personas=p, telefono="5512345678",
                                           espera_estimada_min=20)
            ListaEspera.objects.filter(pk=e.pk).update(creado=timezone.now() - timedelta(minutes=mins))

    def _conversaciones(self, emp, s):
        ejemplos = [
            ("whatsapp", "5511112222", "Mariana", [
                ("user", "Hola! tienen mesa para 4 mañana como a las 2?"),
                ("assistant", f"¡Hola Mariana! Sí, mañana tengo mesa para 4 en {s.nombre} a las 14:00 en terraza o a las 14:30 en interior. ¿Cuál prefieres?"),
                ("user", "terraza porfa"),
                ("assistant", "¡Listo! Tu mesa para 4 quedó reservada mañana a las 14:00 en terraza. Te mando el enlace para cambiarla o cancelarla."),
            ]),
            ("web", "web-demo-1", "Luis", [
                ("user", "¿Aceptan mascotas?"),
                ("assistant", "¡Claro! Nuestra terraza es pet-friendly 🐶. ¿Quieres que te aparte una mesa ahí?"),
            ]),
            ("whatsapp", "5533334444", "Grupo cumpleaños", [
                ("user", "Somos 14 personas el sábado en la noche"),
                ("assistant", "Para grupos de 14 te comunico con el equipo para preparar el acomodo. Te escriben en unos minutos."),
            ]),
        ]
        for canal, contacto, nombre, msgs in ejemplos:
            ConversacionIA.objects.create(
                empresa=emp, canal=canal, contacto=contacto, nombre=nombre,
                requiere_humano=(nombre == "Grupo cumpleaños"),
                mensajes=[{"role": r, "content": [{"type": "text", "text": t}]} for r, t in msgs],
            )
