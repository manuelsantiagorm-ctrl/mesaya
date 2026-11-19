"""
Envía recordatorios (correo + WhatsApp) de las reservas próximas.
Prográmalo cada 15 minutos (cron / Programador de tareas de Windows):

  */15 * * * *  cd /ruta/proyecto && python manage.py enviar_recordatorios
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from reservas.models import Reserva
from reservas.notificaciones import enviar_recordatorio


class Command(BaseCommand):
    help = "Envía el recordatorio de las reservas que inician dentro de las horas configuradas por cada empresa."

    def add_arguments(self, p):
        p.add_argument("--dry-run", action="store_true", help="Solo muestra cuántas se enviarían")

    def handle(self, *a, **o):
        ahora = timezone.now()
        qs = (
            Reserva.objects.filter(
                estado__in=[Reserva.PEND, Reserva.CONF], recordatorio_enviado_en__isnull=True,
                inicio_utc__gt=ahora, inicio_utc__lte=ahora + timedelta(hours=72),
                creada_por_staff=False,
            )
            .select_related("sucursal", "sucursal__empresa", "sucursal__pais", "cliente")
        )
        enviados = 0
        for r in qs:
            horas = r.sucursal.empresa.recordatorio_horas if r.sucursal.empresa_id else 24
            if not horas:
                continue
            # No recordar reservas hechas hace muy poco (ya recibieron la confirmación)
            if r.creado and (r.inicio_utc - r.creado) < timedelta(hours=horas):
                continue
            if r.inicio_utc - ahora <= timedelta(hours=horas):
                if o["dry_run"] or enviar_recordatorio(r):
                    enviados += 1
        self.stdout.write(self.style.SUCCESS(f"Recordatorios {'por enviar' if o['dry_run'] else 'enviados'}: {enviados}"))
