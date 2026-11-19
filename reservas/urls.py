# reservas/urls.py
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required

from . import views
from .views import seleccionar_sucursal

# Store locator / APIs públicas
from .views_chainadmin_menu import (
    MenuCatalogListView,
    CategoryCreateView, CategoryUpdateView,
    MenuItemCreateView, MenuItemUpdateView,
    combo_edit_components, combo_delete_component,
    menuitem_toggle_active, api_buscar_items,
)
from . import views_orders

# POS (órdenes en modal del mapa) — usa SIEMPRE este alias
from . import views_ordenes as ordenes

# Catálogo (ChainAdmin)
from .views_chainadmin_menu import (
    MenuCatalogListView,
    CategoryCreateView, CategoryUpdateView,
    MenuItemCreateView, MenuItemUpdateView,
    combo_edit_components, combo_delete_component,
    menuitem_toggle_active, api_buscar_items,
)
from .views_chainadmin_menu import MenuCatalogListView
from . import views_ordenes

# Staff: crear orden rápida (legacy opcional)
from .views_staff_orders import crear_orden_mesa

# Legacy Orders / KDS / Ticket (mantener)
from .views_orders import (
    mesa_panel_order, add_item, submit_to_kitchen, cobrar_cerrar,
    kds_list, ticket_order, kds_data,
)

# ⚠️ IMPORTA AQUÍ EL NUEVO kds_update_status DEL STAFF
from .views_staff_orders import kds_update_status


# ChainAdmin: Admins de sucursal

# ChainAdmin: Sucursales (CRUD)
from .views_chainadmin import (
    ChainAdminSucursalCreateView,
    ChainAdminSucursalUpdateView,
    ChainAdminSucursalDeleteView,
)

from .views_mesas_api import api_mesas_sucursal  # API mesas para mapa

# Chain Global (roles por país)

# Analytics

# APIs varias

# Country selector (cookie/sesión)
from .views_country import set_country

# Staff: listado sucursales

# Mapa staff protegido + APIs AJAX del mapa
from .views_admin_mapa import AdminMapaSucursalView
from .views_mapa_api import api_list_mesas, api_guardar_posiciones


app_name = "reservas"

from . import views_legado, views_publico, views_panel, views_areas, views_ia, views_ventas, views_empresa, views_agente

urlpatterns = [
    # ===== Público / cliente =====
    path("", views.home, name="home"),
    path("register/", views_legado.a_registro, name="register"),
    path("perfil/", views.perfil, name="perfil"),
    path("mis_reservas/", views.mis_reservas, name="mis_reservas"),
    path("seleccionar_sucursal/", seleccionar_sucursal, name="seleccionar_sucursal"),
    path("reservar/<int:mesa_id>/", views_legado.a_reservar_publico_mesa, name="reservar"),

    # Disponibilidad (cliente)

    # Flujo de reserva cliente
    path("reserva/exito/<int:reserva_id>/", views_legado.a_mis_reservas, name="reserva_exito"),
    path("reserva/<int:reserva_id>/confirmar/", views_legado.a_mis_reservas, name="confirmar_reserva"),

    # ===== Store locator (mapa público) =====
    path("sucursales/", views_legado.a_buscar, name="store_locator"),
    path("sucursales/grid/", views_legado.a_buscar, name="sucursales_grid"),

    # ===== Staff (prefijo /staff/) =====
    path("staff/sucursales/", views.admin_sucursales, name="admin_sucursales"),
    path("staff/sucursales/lista/", views_legado.a_sucursales_staff, name="staff_sucursales"),
    path("staff/sucursales/nueva/", views_legado.a_sucursal_nueva, name="admin_sucursal_nueva"),
    path("staff/sucursales/<int:pk>/editar/", views_legado.a_sucursal_editar, name="admin_sucursal_editar"),
    path("staff/sucursales/<int:sucursal_id>/contenido/", views.admin_sucursal_contenido, name="admin_sucursal_contenido"),
    path("staff/sucursal/<int:sucursal_id>/bloqueos/", views.admin_bloqueos, name="admin_bloqueos"),

    # Mapa y mesas (vista protegida)
    path("staff/sucursal/<int:sucursal_id>/mapa/", AdminMapaSucursalView.as_view(), name="admin_mapa_sucursal"),
    path("staff/mesa/<int:mesa_id>/", views.admin_mesa_detalle, name="admin_mesa_detalle"),
    path("staff/mesa/<int:mesa_id>/editar/", views.admin_mesa_editar, name="admin_editar_mesa"),
    path("staff/sucursal/<int:sucursal_id>/mesa/crear/", views.admin_mesa_crear, name="admin_mesa_crear"),

    # API de mesas (mapa)
    path("staff/api/mesa/<int:mesa_id>/update/", views.admin_api_mesa_update, name="admin_api_mesa_update"),
    path("staff/api/mesa/<int:mesa_id>/pos/", views.admin_api_mesa_pos, name="admin_api_mesa_pos"),
    path("staff/api/mesa/create/", views.admin_api_mesa_create, name="admin_api_mesa_create"),
    path("staff/mesas/<int:mesa_id>/setpos/", views.admin_api_mesa_setpos, name="admin_api_mesa_setpos"),
    path("staff/api/sucursales/<int:sucursal_id>/mesas/", api_list_mesas, name="api_list_mesas"),
    path("staff/api/sucursales/<int:sucursal_id>/posiciones/guardar/", api_guardar_posiciones, name="api_guardar_posiciones"),
    path("staff/sucursal/<int:sucursal_id>/api/recepcion/pos/", views.admin_api_recepcion_pos, name="admin_api_recepcion_pos"),

    # Bloqueos
    path("staff/api/bloqueo/create/", views.admin_api_bloqueo_create, name="admin_api_bloqueo_create"),
    path("staff/api/bloqueo/list/", views.admin_api_bloqueo_list, name="admin_api_bloqueo_list"),
    path("staff/api/bloqueo/delete/", staff_member_required(views.admin_api_bloqueo_delete), name="admin_api_bloqueo_delete"),

    # Disponibilidad staff
    path("staff/disponibilidad/mesa/<int:mesa_id>/", views.admin_disponibilidad_mesa, name="admin_disponibilidad_mesa"),
    path("staff/agenda/mesa/<int:mesa_id>/", views.agenda_mesa, name="agenda_mesa"),
    path("staff/api/disponibilidad/", views.staff_api_disponibilidad, name="staff_api_disponibilidad"),
    path("staff/api/disponibilidad/json/", views.staff_disponibilidad_json, name="staff_disponibilidad_json"),

    # Reservas staff
    path("staff/reservas/", views.admin_reservas, name="admin_reservas"),
    path("staff/reservas/<int:reserva_id>/finalizar/", views.admin_finalizar_reserva, name="admin_finalizar_reserva"),
    path("staff/reservas/<int:reserva_id>/reasignar/", views.admin_reasignar_reserva, name="admin_reasignar_reserva"),
    path("staff/reserva/<int:reserva_id>/confirmar-llegada/", views.admin_confirmar_llegada, name="admin_confirmar_llegada"),

    # Mesas disponibles
    path("staff/sucursal/<int:sucursal_id>/mesas/", views_legado.a_mapa, name="admin_mesas_disponibles"),

    # Detalle sucursal pública
    path("s/<slug:slug>/", views_legado.a_reservar_publico_slug, name="sucursal_detalle"),

    # Flujo reserva cliente (slots/auto)
    path("sucursal/<int:sucursal_id>/reservar-slot/", views_legado.a_reservar_publico_sucursal, name="reservar_slot"),
    path("sucursal/<int:sucursal_id>/reservar-auto/", views_legado.a_reservar_publico_sucursal, name="reservar_auto"),

    # APIs públicas varias
    path("api/sucursal/<int:sucursal_id>/slots/", views.api_slots_sucursal, name="api_slots_sucursal"),

    # Selector de país
    path("set-country/", set_country, name="set_country"),

    # Health checks
    path("healthz/", views.healthz, name="healthz"),
    path("readyz/", views.readyz, name="readyz"),

    # ===== ChainAdmin — Administradores =====
    path("chainadmin/admins/", views_legado.a_equipo, name="chainadmin_admins"),
    path("chainadmin/admins/nuevo/", views_legado.a_equipo, name="chainadmin_admin_nuevo"),
    path("chainadmin/admins/<int:user_id>/editar/", views_legado.a_equipo, name="chainadmin_admin_editar"),
    path("chainadmin/admins/<int:user_id>/password/", views_legado.a_equipo, name="chainadmin_admin_password"),
    path("chainadmin/admins/<int:user_id>/toggle/", views_legado.a_equipo, name="chainadmin_admin_toggle"),
    path("chainadmin/admins/all/", views_legado.a_equipo, name="chainadmin_admins_all"),
    path("chainadmin/admins/<int:user_id>/", views_legado.a_equipo, name="chainadmin_admin_detail"),

    # ===== ChainAdmin — Sucursales =====
    path("chainadmin/sucursales/", views_legado.a_sucursales_staff, name="chainadmin_sucursales"),
    path("chainadmin/sucursales/nueva/", ChainAdminSucursalCreateView.as_view(), name="chainadmin_sucursal_nueva"),
    path("chainadmin/sucursales/<int:pk>/editar/", ChainAdminSucursalUpdateView.as_view(), name="chainadmin_sucursal_editar"),
    path("chainadmin/sucursales/<int:pk>/eliminar/", ChainAdminSucursalDeleteView.as_view(), name="chainadmin_sucursal_eliminar"),

    # ===== Chain Global / Roles por país =====
    path("admin/global/", views_legado.a_plataforma, name="chain_global_dashboard"),
    path("admin/global/roles/create/", views_legado.a_plataforma, name="chain_global_role_create"),
    path("admin/global/roles/<int:pk>/toggle/", views_legado.a_plataforma, name="chain_global_role_toggle"),
    path("admin/global/roles/create-user/", views_legado.a_plataforma, name="chain_global_create_country_admin_user"),

    # ===== Analytics =====
    path("chainadmin/analytics/", views_legado.a_resumen, name="chainadmin_analytics"),
    path("chainadmin/analytics/data/", views_legado.a_resumen, name="chainadmin_analytics_data"),
    path("chainadmin/analytics/sucursales/", views_legado.a_resumen, name="analytics-branches"),
    path("chainadmin/analytics/compare/", views_legado.a_resumen, name="analytics-compare"),

    # ===== Dashboard Staff =====
    path("admin/dashboard/", views_legado.a_hoy, name="admin_dashboard"),
    path("admin/acciones/cancelar/", views.admin_cancelar_por_folio, name="admin_cancelar_por_folio"),
    path("admin/acciones/checkin/",  views.admin_checkin_por_folio,  name="admin_checkin_por_folio"),
    path("admin/acciones/reactivar/", views.admin_reactivar_por_folio, name="admin_reactivar_por_folio"),
    path("staff/walkin/", views.admin_walkin_reserva, name="admin_walkin_reserva"),
    path("reserva/<int:pk>/", views.reserva_detalle, name="reserva_detalle"),
    path("r/<str:folio>/", views.reserva_scan_entry, name="reserva_scan_entry"),
    path("r/<str:folio>/checkin/", views.reserva_checkin, name="reserva_checkin"),
    path("chainadmin/dashboard/", views_legado.a_resumen, name="chainadmin_dashboard_country"),

    # ===== Legacy Orders / KDS / Ticket =====
    path("admin/mesas/<int:mesa_id>/orden/", mesa_panel_order, name="mesa_panel_order"),
    path("admin/orders/<int:order_id>/add-item/", add_item, name="order_add_item"),
    path("admin/orders/<int:order_id>/submit/", submit_to_kitchen, name="order_submit"),
    path("admin/orders/<int:order_id>/quitar/", views_orders.order_item_quitar, name="order_item_quitar"),
    path("admin/orders/<int:order_id>/cobrar/", cobrar_cerrar, name="order_cobrar"),
    path("admin/kds/", kds_list, name="kds"),
    path("admin/kds/<int:order_id>/status/", kds_update_status, name="kds_update_status"),
    path("admin/orders/<int:order_id>/ticket/", ticket_order, name="ticket_order"),

    # ===== POS nuevo – modal del mapa =====
    path("orden/nueva/", ordenes.orden_mesa_nueva, name="orden_mesa_nueva"),

    # Buscador del modal
    path("api/menu/buscar/", ordenes.api_menu_buscar, name="menu_api_buscar"),

    # CRUD de renglones de la orden (POS)
    path("api/orden/crear/", ordenes.api_orden_crear, name="api_orden_crear"),
    path("api/orden/<int:orden_id>/", ordenes.api_orden_detalle, name="api_orden_detalle"),
    path("api/orden/item/update/", ordenes.api_orden_item_update, name="api_orden_item_update"),
    path("api/orden/item/split/",  ordenes.api_orden_item_split,  name="api_orden_item_split"),
    path("api/orden/item/remove/", ordenes.api_orden_item_remove, name="api_orden_item_remove"),

    # Enviar orden POS a cocina (nuevo endpoint que sincroniza con KDS)
    path(
        "api/orden-pos/<int:orden_id>/enviar/",
        ordenes.api_orden_pos_enviar_cocina,
        name="api_orden_pos_enviar_cocina",
    ),

    # alias opcional por compatibilidad con tu JS viejo
    path("api/orden/item/quitar/", ordenes.api_orden_item_remove, name="api_orden_quitar_item"),

    # (Opcional) crear orden rápida legacy
    path("staff/ordenes/nueva/", staff_member_required(crear_orden_mesa), name="orden_mesa_nueva_rapida"),
    
    path("staff/buscar-folio/", views.admin_buscar_folio, name="admin_buscar_folio"),

    # --- Catálogo (ChainAdmin) ---
    path("chainadmin/menu/", MenuCatalogListView.as_view(), name="chainadmin_menu_catalogo"),

    # Categorías
    path("chainadmin/menu/categoria/nueva/", CategoryCreateView.as_view(),
         name="chainadmin_menu_categoria_nueva"),
    path("chainadmin/menu/categoria/<int:pk>/editar/", CategoryUpdateView.as_view(),
         name="chainadmin_menu_categoria_editar"),

    # Ítems
    path("chainadmin/menu/item/nuevo/", MenuItemCreateView.as_view(),
         name="chainadmin_menu_item_nuevo"),
    path("chainadmin/menu/item/<int:pk>/editar/", MenuItemUpdateView.as_view(),
         name="chainadmin_menu_item_editar"),
    path("chainadmin/menu/item/<int:pk>/toggle/", menuitem_toggle_active,
         name="chainadmin_menu_item_toggle"),

    # Combos
    path("chainadmin/menu/combo/<int:pk>/", combo_edit_components,
         name="chainadmin_menu_combo"),
    path("chainadmin/menu/combo/<int:pk>/comp/<int:comp_id>/del/", combo_delete_component,
         name="chainadmin_menu_combo_comp_del"),

    # API de búsqueda (para formularios del catálogo)
    path("chainadmin/menu/api/buscar-items/", api_buscar_items,
         name="chainadmin_menu_api_buscar_items"),
    
    # JSON para el KDS
    path("admin/kds/data/", kds_data, name="kds_data"),
    
     # Cobrar y cerrar desde POS (puente a Order/ticket)
    path(
        "api/orden-pos/<int:orden_id>/cobrar/",
        ordenes.api_orden_pos_cobrar,
        name="api_orden_pos_cobrar",
    ),

    path(
        "api/orden-pos/<int:order_id>/item/update/",
        views_orders.api_orden_pos_item_update,
        name="api_orden_pos_item_update",
    ),
    path(
    "staff/ordenes/<int:order_id>/item-update/",
    views_orders.api_orden_pos_item_update,
    name="api_orden_pos_item_update",
    ),


    # ===============================
    # Flujo público del comensal (sin cuenta obligatoria)
    # ===============================
    path("reservar/<slug:slug>/", views_publico.reservar, name="reservar_publico"),
    path("api/publico/<slug:slug>/horarios/", views_publico.api_slots, name="api_slots_publico"),
    path("mi-reserva/<str:token>/", views_publico.reserva_publica, name="reserva_publica"),
    path("mi-reserva/<str:token>/cancelar/", views_publico.reserva_publica_cancelar, name="reserva_publica_cancelar"),
    path("mi-reserva/<str:token>/calendario.ics", views_publico.reserva_ics, name="reserva_ics"),
    path("mi-reserva/<str:token>/qr.svg", views_publico.reserva_qr, name="reserva_qr"),
    path("privacidad/", views_publico.aviso_privacidad, name="aviso_privacidad"),
    path("privacidad/<slug:slug>/", views_publico.aviso_privacidad, name="aviso_privacidad_empresa"),

    # Admins de país (referentes)
    path("chainadmin/admins-pais/", views_legado.a_equipo, name="chainadmin_country_admins_all"),
    path("chainadmin/admins-pais/<int:user_id>/", views_legado.a_equipo, name="chainadmin_country_admin_detail"),

    # Configuración de la empresa (marca, aviso de privacidad, WhatsApp) y reglas por sucursal
    # Panel operativo y ventas
    path("staff/", views_areas.staff_inicio, name="staff_inicio"),
    path("staff/meseros/", views_areas.meseros, name="meseros"),
    path("staff/hoy/", views_panel.panel_hoy, name="panel_hoy"),
    path("staff/hoy/reserva/<int:pk>/<str:accion>/", views_panel.panel_reserva_accion, name="panel_reserva_accion"),
    path("staff/hoy/espera/", views_panel.espera_agregar, name="espera_agregar"),
    path("staff/hoy/vigilar/", views_panel.panel_vigilar, name="panel_vigilar"),
    path("staff/hoy/espera/<int:pk>/<str:accion>/", views_panel.espera_accion, name="espera_accion"),
    path("staff/resumen/", views_panel.resumen_negocio, name="resumen_negocio"),
    path("staff/ia/", views_ia.ia_sucursal, name="ia_sucursal"),
    path("staff/ia/configurar/", views_ia.asistente_alta, name="asistente_alta"),
    path("planes/", views_ventas.landing, name="planes"),
    path("demo/solicitar/", views_ventas.solicitar_demo, name="solicitar_demo"),
    path("plataforma/", views_ventas.plataforma, name="plataforma"),
    path("plataforma/prospecto/<int:pk>/", views_ventas.plataforma_prospecto, name="plataforma_prospecto"),
    path("plataforma/empresa/<int:pk>/pago/", views_ventas.plataforma_pago, name="plataforma_pago"),
    path("plataforma/empresa/<int:pk>/soporte/", views_ventas.soporte_entrar, name="soporte_entrar"),
    path("plataforma/soporte/salir/", views_ventas.soporte_salir, name="soporte_salir"),
    path("staff/empresa/", views_empresa.empresa_config, name="empresa_config"),
    path("staff/empresa/equipo/", views_empresa.empresa_equipo, name="empresa_equipo"),
    path("staff/sucursal/<int:sucursal_id>/reglas/", views_empresa.sucursal_reglas, name="sucursal_reglas"),
    path("staff/sucursal/<int:sucursal_id>/widget/", views_empresa.sucursal_widget, name="sucursal_widget"),

    # Asistente de IA
    path("asistente/<slug:slug>/", views_agente.chat_web, name="asistente_chat"),
    path("api/asistente/<slug:slug>/mensaje/", views_agente.chat_web_mensaje, name="asistente_mensaje"),
    path("webhooks/whatsapp/", views_agente.whatsapp_webhook, name="whatsapp_webhook"),
    path("staff/empresa/conversaciones/", views_agente.conversaciones, name="empresa_conversaciones"),
]

    
