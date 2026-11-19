"""
Recalcula lo que la IA aprendió de cada sucursal (duraciones reales, riesgo de no-show, demanda).
Programarlo una vez al día de madrugada, por ejemplo:  python manage.py aprender_sucursales
"""
from django.core.management.base import BaseCommand

from reservas import aprendizaje
from reservas.models import Sucursal


class Command(BaseCommand):
    help = "Aprendizaje diario por sucursal."

    def add_arguments(self, p):
        p.add_argument("--sucursal", type=int, help="Solo esta sucursal (id)")
        p.add_argument("--empresa", help="Solo las sucursales de esta empresa (slug)")

    def handle(self, *a, **o):
        qs = Sucursal.objects.filter(activo=True)
        if o.get("sucursal"):
            qs = qs.filter(pk=o["sucursal"])
        if o.get("empresa"):
            qs = qs.filter(empresa__slug=o["empresa"])
        for s in qs.iterator():
            p = aprendizaje.aprender(s)
            m = p.metricas
            self.stdout.write(f"{s.nombre}: {p.muestras} mesas · error fijo {m.get('error_fijo_min')} min → "
                              f"IA {m.get('error_ia_min')} min · {len(p.sugerencias)} sugerencias")
