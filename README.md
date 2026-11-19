# Sistema de Reservaciones para Restaurantes (multi-empresa)

Plataforma web para que **varios restaurantes y cadenas** reciban reservaciones en línea, administren su salón y
operen recepción y cocina. Cada restaurante es una **empresa** con su propia marca, sucursales, equipo y datos aislados.

## Qué incluye

| Para el comensal | Para el restaurante | Para ti (plataforma) |
| --- | --- | --- |
| Reservar sin crear cuenta (`/reservar/<sucursal>/`) | Mapa del salón, zonas y bloqueos de mesa | Alta de empresas en `/admin/` o con `crear_empresa` |
| Horarios reales disponibles y alternativas si está lleno | Asignación automática de la mejor mesa | Marca blanca y dominio propio por empresa |
| Confirmación por correo y WhatsApp | Recepción: reservas del día, walk-ins, check-in por QR | Datos aislados entre empresas |
| Enlace privado para ver/cancelar, calendario (.ics) y QR | POS por mesa y pantalla de cocina (KDS) | Planes: básico / pro / cadena |
| Aviso de privacidad y consentimiento (LFPDPPP) | Equipo y roles (dueño, administrador, personal) | |
| | Reglas por sucursal (horario, duración, máximos) | |
| | Widget para su web, Instagram o Google | |
| | Resumen: reservas, cancelaciones, no-shows | |

## Instalación local

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # y llena los valores (Linux/Mac: cp)
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

`.env` **nunca** se sube a git. Todas las contraseñas y llaves se leen de ahí.

## Dar de alta un restaurante (empresa)

```bash
python manage.py crear_empresa "Tacos Don Juan" --email dueno@tacos.mx --password "Clave-Segura-123" \
    --sucursal "Centro" --pais MX --tz America/Mexico_City --mesas 10 --plan pro
```

El dueño entra con su correo, activa la verificación en dos pasos y configura en **Mi negocio**:
marca (logo y colores), equipo, menú, reglas por sucursal y el enlace de reservas.

Para que los comensales vean solo ese restaurante: comparte `/reservar/<slug-sucursal>/`, usa `?e=<slug-empresa>`
o configura un dominio propio en la empresa (campo *dominio*).

## Roles

- **Superusuario**: administra la plataforma (`/admin/`). Es el único que entra al admin de Django.
- **Dueño / Administrador** de una empresa: todas las sucursales de su empresa.
- **Admin de país**: sucursales de ese país dentro de su empresa.
- **Personal**: solo las sucursales asignadas.

Toda la lógica de permisos vive en `reservas/tenancy.py`.

## Recordatorios y WhatsApp

1. En Meta for Developers crea una app de WhatsApp Business y copia `WHATSAPP_TOKEN` y `WHATSAPP_PHONE_NUMBER_ID` al `.env`.
2. Aprueba dos plantillas (confirmación y recordatorio) con 5 variables: nombre, sucursal, fecha, hora y enlace.
   Pon sus nombres en `WHATSAPP_TEMPLATE_CONFIRMACION` y `WHATSAPP_TEMPLATE_RECORDATORIO`.
3. La empresa activa “Enviar confirmación y recordatorio por WhatsApp” en su configuración.
4. Programa los recordatorios cada 15 minutos:
   - Linux (cron): `*/15 * * * * cd /ruta && venv/bin/python manage.py enviar_recordatorios`
   - Windows: Programador de tareas → `python manage.py enviar_recordatorios`

Sin token configurado, los WhatsApp se escriben en el log (útil para la demo).

## Asistente de IA para reservaciones

Atiende a los clientes por chat web (`/asistente/<slug-empresa>/`) y por WhatsApp. Entiende mensajes como
"mesa para 4 mañana a las 2 en terraza", **evalúa qué mesas y horarios están libres** y reserva o propone.

- La IA conversa; el sistema decide: sus herramientas usan `reservas/booking.py` (mismas reglas, mismo bloqueo
  contra doble reserva). No puede dar una mesa ocupada ni ver otra empresa.
- El dueño lo **prende o apaga** en *Mi negocio → Configuración y marca → Asistente de IA*, elige si reserva
  directo o solo propone (queda pendiente para que el personal confirme) y le da indicaciones (tono, reglas de la casa).
- *Mi negocio → Asistente IA* muestra todas las conversaciones y las que piden a una persona.

Configuración (`.env`):
```
ANTHROPIC_API_KEY=sk-ant-...            # https://console.anthropic.com
AGENTE_IA_MODELO=claude-haiku-5-5       # o claude-sonnet-5-5 (más capaz, más caro)
WHATSAPP_VERIFY_TOKEN=una-frase-secreta
WHATSAPP_APP_SECRET=...                 # de la app de Meta (valida la firma de cada mensaje)
```
En Meta, configura el webhook `https://TU-DOMINIO/webhooks/whatsapp/` con el mismo `WHATSAPP_VERIFY_TOKEN`
y suscríbete a `messages`. Si cada restaurante tiene su propio número, pon su *phone number id* en la empresa
(admin); si comparten el de la plataforma, usa `WHATSAPP_EMPRESA_POR_DEFECTO=<slug>`.

## Pruebas

```bash
python manage.py test reservas
```

Cubren aislamiento entre empresas, reglas de reserva, flujo público, cancelación, recordatorios y las pantallas de staff.

## Producción

- `DEBUG=False`, `SECRET_KEY` larga y única, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` con https.
- PostgreSQL con `DB_SSLMODE=require`, Redis opcional (`REDIS_URL`).
- `python manage.py collectstatic` y servir con `gunicorn ihop_system.wsgi` detrás de Nginx (o con `docker compose up`).
- Respaldos diarios de la base de datos fuera del repositorio.

## Estructura

- `reservas/tenancy.py` — quién puede ver qué (multi-empresa)
- `reservas/booking.py` — creación de reservas, disponibilidad y bloqueo contra doble reserva
- `reservas/notificaciones.py` — correo y WhatsApp
- `reservas/views_publico.py` — flujo del comensal sin cuenta
- `reservas/views_empresa.py` — panel del dueño (marca, equipo, reglas, widget)
