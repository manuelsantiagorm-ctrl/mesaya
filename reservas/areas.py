"""
Áreas de trabajo y puestos.

Cada persona del equipo tiene UN puesto (MiembroEmpresa.rol) y el puesto decide a qué áreas entra:

    Dueño / Gerente general  -> todas
    Gerente de sucursal      -> Recepción, Meseros, Cocina y Sucursal (de SUS sucursales)
    Recepción                -> Recepción
    Mesero                   -> Meseros
    Cocina                   -> Cocina

Toda pantalla del panel está en RUTAS con las áreas que la pueden usar. AreaMiddleware bloquea
cualquier otra cosa. Una ruta nueva que no se clasifique queda BLOQUEADA para el personal
(y la prueba test_areas.test_todas_las_rutas_clasificadas falla), así nadie se cuela por olvido.
"""
from django.utils.translation import gettext_lazy as _l

RECEPCION = "recepcion"
MESEROS = "meseros"
COCINA = "cocina"
SUCURSAL = "sucursal"
NEGOCIO = "negocio"

AREAS = {
    RECEPCION: {"nombre": _l("Recepción"), "icono": "bi-person-check", "color": "#2E7DD7", "url": "reservas:panel_hoy",
                "que_hace": _l("Recibe a los clientes, ve las reservas del día, sienta a la gente y maneja la lista de espera.")},
    MESEROS: {"nombre": _l("Meseros"), "icono": "bi-cup-hot", "color": "#2F9E62", "url": "reservas:meseros",
              "que_hace": _l("Ve sus mesas, toma órdenes, avisa cuando piden la cuenta y libera la mesa.")},
    COCINA: {"nombre": _l("Cocina"), "icono": "bi-fire", "color": "#E4572E", "url": "reservas:kds",
             "que_hace": _l("Solo ve las órdenes que llegan y las marca: preparando, lista, entregada.")},
    SUCURSAL: {"nombre": _l("Sucursal"), "icono": "bi-grid-3x3-gap", "color": "#7B5CD6", "url": "reservas:admin_sucursales",
               "que_hace": _l("Mesas, mapa, bloqueos, horarios y lo que aprendió la IA de la sucursal.")},
    NEGOCIO: {"nombre": _l("Mi negocio"), "icono": "bi-briefcase", "color": "#1E1B18", "url": "reservas:resumen_negocio",
              "que_hace": _l("Resumen de ventas, equipo, menú, sucursales nuevas y configuración de la marca.")},
}
ORDEN_AREAS = [RECEPCION, MESEROS, COCINA, SUCURSAL, NEGOCIO]

# Puesto -> áreas
ROL_AREAS = {
    "owner": set(ORDEN_AREAS),
    "admin": set(ORDEN_AREAS),
    "staff": {RECEPCION, MESEROS, COCINA, SUCURSAL},
    "recepcion": {RECEPCION},
    "mesero": {MESEROS},
    "cocina": {COCINA},
}

R, M, C, S, N = {RECEPCION}, {MESEROS}, {COCINA}, {SUCURSAL}, {NEGOCIO}

# Ruta (nombre en el namespace "reservas") -> áreas que pueden usarla
RUTAS = {
    # ---- Recepción
    "panel_hoy": R, "espera_agregar": R, "espera_accion": R, "panel_vigilar": R | S,
    "panel_reserva_accion": R | M,          # el mesero solo puede "cuenta" y "liberar" (se revisa en la vista)
    "admin_reservas": R | S, "admin_walkin_reserva": R, "admin_buscar_folio": R,
    "admin_cancelar_por_folio": R, "admin_checkin_por_folio": R, "admin_reactivar_por_folio": R,
    "admin_confirmar_llegada": R, "admin_finalizar_reserva": R | M, "admin_reasignar_reserva": R | S,
    "reserva_checkin": R, "staff_api_disponibilidad": R | S, "staff_disponibilidad_json": R | S,
    "admin_disponibilidad_mesa": R | S, "agenda_mesa": R | S, "admin_api_recepcion_pos": R | S,
    "admin_mesa_detalle": R | S,
    # ---- Meseros
    "meseros": M, "mesa_panel_order": M, "order_add_item": M, "order_submit": M, "order_item_quitar": M, "order_cobrar": M | R,
    "ticket_order": M | R, "orden_mesa_nueva": M, "orden_mesa_nueva_rapida": M, "menu_api_buscar": M,
    "api_orden_crear": M, "api_orden_detalle": M, "api_orden_item_update": M, "api_orden_item_split": M,
    "api_orden_item_remove": M, "api_orden_quitar_item": M, "api_orden_pos_enviar_cocina": M,
    "api_orden_pos_cobrar": M | R, "api_orden_pos_item_update": M,
    # ---- Cocina
    "kds": C, "kds_data": C, "kds_update_status": C,
    # ---- Sucursal (gerente)
    "admin_sucursales": S, "admin_sucursal_contenido": S, "admin_bloqueos": S, "admin_mapa_sucursal": S,
    "admin_editar_mesa": S, "admin_mesa_crear": S, "admin_api_mesa_update": S, "admin_api_mesa_pos": S,
    "admin_api_mesa_create": S, "admin_api_mesa_setpos": S, "api_list_mesas": R | S, "api_guardar_posiciones": S,
    "admin_api_bloqueo_create": S, "admin_api_bloqueo_list": S, "admin_api_bloqueo_delete": S,
    "ia_sucursal": S, "asistente_alta": S, "sucursal_reglas": S, "sucursal_widget": S,
    # ---- Mi negocio (dueño y gerente general)
    "resumen_negocio": N, "empresa_config": N, "empresa_equipo": N, "empresa_conversaciones": N,
    "chainadmin_sucursal_nueva": N, "chainadmin_sucursal_editar": N, "chainadmin_sucursal_eliminar": N,
    "chainadmin_menu_catalogo": N, "chainadmin_menu_categoria_nueva": N, "chainadmin_menu_categoria_editar": N,
    "chainadmin_menu_item_nuevo": N, "chainadmin_menu_item_editar": N, "chainadmin_menu_item_toggle": N,
    "chainadmin_menu_combo": N, "chainadmin_menu_combo_comp_del": N, "chainadmin_menu_api_buscar_items": N,
}

# Rutas que no son del panel: públicas, del comensal, de la plataforma (su vista lo revisa)
# o enlaces viejos que solo redirigen (el destino vuelve a pasar por aquí).
LIBRES = {
    "home", "register", "perfil", "mis_reservas", "seleccionar_sucursal", "reservar", "reserva_exito",
    "confirmar_reserva", "store_locator", "sucursales_grid", "sucursal_detalle", "reservar_slot", "reservar_auto",
    "api_slots_sucursal", "set_country", "healthz", "readyz", "reserva_detalle", "reserva_scan_entry",
    "reservar_publico", "api_slots_publico", "reserva_publica", "reserva_publica_cancelar", "reserva_ics",
    "reserva_qr", "aviso_privacidad", "aviso_privacidad_empresa", "planes", "solicitar_demo",
    "asistente_chat", "asistente_mensaje", "whatsapp_webhook", "staff_inicio",
    "plataforma", "plataforma_prospecto", "plataforma_pago", "soporte_entrar", "soporte_salir",
    # enlaces viejos (redirigen)
    "staff_sucursales", "admin_sucursal_nueva", "admin_sucursal_editar", "admin_mesas_disponibles",
    "chainadmin_admins", "chainadmin_admin_nuevo", "chainadmin_admin_editar", "chainadmin_admin_password",
    "chainadmin_admin_toggle", "chainadmin_admins_all", "chainadmin_admin_detail", "chainadmin_sucursales",
    "chain_global_dashboard", "chain_global_role_create", "chain_global_role_toggle",
    "chain_global_create_country_admin_user", "chainadmin_analytics", "chainadmin_analytics_data",
    "analytics-branches", "analytics-compare", "admin_dashboard", "chainadmin_dashboard_country",
    "chainadmin_country_admins_all", "chainadmin_country_admin_detail",
}


def areas_de(user):
    """Áreas a las que entra el usuario (se calcula una vez por petición)."""
    if not (user and user.is_authenticated):
        return set()
    cache = getattr(user, "_areas_cache", None)
    if cache is not None:
        return cache
    from . import tenancy
    from .models import MiembroEmpresa

    if user.is_superuser:
        out = set(ORDEN_AREAS) if tenancy.soporte_empresa_id(user) else set()
    else:
        out = set()
        for rol in MiembroEmpresa.objects.filter(user=user, activo=True, empresa__activa=True).values_list("rol", flat=True):
            out |= ROL_AREAS.get(rol, set())
        if not out and user.is_staff and tenancy.sucursales_for_user(user).exists():
            out = set(ROL_AREAS["staff"])  # cuentas viejas asignadas a una sucursal sin puesto
    user._areas_cache = out
    return out


def puede(user, area):
    return area in areas_de(user)


def inicio_de(user):
    """URL name de la pantalla con la que empieza su turno."""
    a = areas_de(user)
    for area in ORDEN_AREAS:
        if area in a:
            return AREAS[area]["url"]
    return None


def menu_de(user):
    a = areas_de(user)
    return [dict(AREAS[k], codigo=k) for k in ORDEN_AREAS if k in a]


# Cómo se ve cada puesto en la pantalla de Equipo (explicado para alguien que nunca usó el sistema)
PUESTOS = {
    "owner": {"icono": "bi-star-fill", "color": "#1E1B18", "desc": _l("Ve y controla todo: todas las sucursales, equipo, menú y dinero.")},
    "admin": {"icono": "bi-briefcase", "color": "#5A4FCF", "desc": _l("Igual que el dueño en todas las sucursales, pero no puede agregar dueños.")},
    "staff": {"icono": "bi-shop", "color": "#7B5CD6", "desc": _l("Maneja SUS sucursales: recepción, meseros, cocina, mesas y horarios.")},
    "recepcion": {"icono": "bi-person-check", "color": "#2E7DD7", "desc": _l("Recibe clientes, reservas del día y lista de espera. Nada más.")},
    "mesero": {"icono": "bi-cup-hot", "color": "#2F9E62", "desc": _l("Ve las mesas, toma órdenes y avisa cuando piden la cuenta. Nada más.")},
    "cocina": {"icono": "bi-fire", "color": "#E4572E", "desc": _l("Solo ve las órdenes que llegan a cocina. Nada más.")},
}
