"""
Vigilante de piso: no-shows automáticos + reacomodo de mesas que siguen ocupadas.
Programarlo cada 5 minutos:  python manage.py vigilar_piso
"""
from django.core.management.base import BaseCommand

from reservas import piso
from reservas.models import Sucursal


class Command(BaseCommand):
    help = "Revisa el piso de todas las sucursales activas."

    def add_arguments(self, p):
        p.add_argument("--solo-alertar", action="store_true", help="No reacomoda ni avisa; solo informa")

    def handle(self, *a, **o):
        for s in Sucursal.objects.filter(activo=True).iterator():
            ns = piso.marcar_no_shows(s)
            r = piso.vigilar(s, auto=not o["solo_alertar"])
            if ns or r["alertas"]:
                self.stdout.write(f"{s.nombre}: {ns} no-show · {r['alertas']} alertas · "
                                  f"{r['reacomodadas']} reacomodadas · {r['avisadas']} avisos")
