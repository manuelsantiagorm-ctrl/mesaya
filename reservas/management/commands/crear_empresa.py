"""
Da de alta un restaurante cliente (empresa) con su dueño y, opcionalmente, su primera sucursal.

Ejemplo:
  python manage.py crear_empresa "Tacos Don Juan" --email dueno@tacos.mx --password "Clave-Segura-123" \
      --sucursal "Centro" --pais MX --tz America/Mexico_City --mesas 10 --plan pro
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reservas.models import Empresa, MiembroEmpresa, Pais, Sucursal


class Command(BaseCommand):
    help = "Crea una empresa (cliente de la plataforma) con su usuario dueño."

    def add_arguments(self, p):
        p.add_argument("nombre")
        p.add_argument("--email", required=True, help="Correo del dueño")
        p.add_argument("--password", help="Contraseña inicial (si el usuario no existe)")
        p.add_argument("--plan", default="basico", choices=[c[0] for c in Empresa.PLANES])
        p.add_argument("--color", default="#1F6FEB")
        p.add_argument("--dominio", default="")
        p.add_argument("--sucursal", help="Nombre de la primera sucursal")
        p.add_argument("--pais", default="MX")
        p.add_argument("--tz", default="America/Mexico_City")
        p.add_argument("--mesas", type=int, default=0, help="Mesas de 4 personas a crear")

    @transaction.atomic
    def handle(self, *a, **o):
        User = get_user_model()
        email = o["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            if not o.get("password"):
                raise CommandError("El usuario no existe: indica --password.")
            user = User.objects.create_user(username=email, email=email, password=o["password"])
        user.is_staff = True
        user.save(update_fields=["is_staff"])

        emp = Empresa.objects.create(
            nombre=o["nombre"], plan=o["plan"], color_primario=o["color"],
            dominio=o["dominio"] or None, email_contacto=email,
        )
        MiembroEmpresa.objects.create(empresa=emp, user=user, rol=MiembroEmpresa.OWNER)
        self.stdout.write(self.style.SUCCESS(f"Empresa '{emp.nombre}' creada (slug: {emp.slug}). Dueño: {email}"))

        if o.get("sucursal"):
            pais, _ = Pais.objects.get_or_create(iso2=o["pais"].upper(), defaults={"nombre": o["pais"].upper()})
            s = Sucursal.objects.create(empresa=emp, nombre=o["sucursal"], pais=pais, timezone=o["tz"])
            existentes = s.mesas.count()
            for n in range(existentes + 1, existentes + 1 + max(0, o["mesas"])):
                s.mesas.create(numero=n, capacidad=4)
            self.stdout.write(self.style.SUCCESS(
                f"Sucursal '{s.nombre}' creada con {s.mesas.count()} mesas. Reservas: /reservar/{s.slug}/"
            ))
