from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Aerolinea,
    Asiento,
    Auditoria,
    CheckIn,
    Devolucion,
    Notificacion,
    Pago,
    Pasajero,
    Promocion,
    PromocionVuelo,
    Reserva,
    ReservaPasajero,
    Rol,
    Ticket,
    Usuario,
    Vuelo,
)


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ("nombre", "descripcion", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre",)
    filter_horizontal = ("permisos",)


@admin.register(Usuario)
class UsuarioAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "nombre",
        "rol",
        "estado",
        "is_active",
    )
    list_filter = ("rol", "estado", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name", "rut")
    ordering = ("username",)

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Datos SkyAndes",
            {
                "fields": (
                    "rol",
                    "rut",
                    "telefono",
                    "estado",
                )
            },
        ),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            "Datos SkyAndes",
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "rol",
                    "rut",
                    "telefono",
                    "estado",
                )
            },
        ),
    )

    @admin.display(description="nombre")
    def nombre(self, obj):
        return obj.get_full_name() or obj.username


@admin.register(Pasajero)
class PasajeroAdmin(admin.ModelAdmin):
    list_display = (
        "nombre_completo",
        "rut",
        "pasaporte",
        "email",
        "telefono",
        "usuario",
    )
    search_fields = ("nombre_completo", "rut", "pasaporte", "email")
    list_select_related = ("usuario",)


@admin.register(Aerolinea)
class AerolineaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo_iata", "pais", "activo")
    list_filter = ("activo", "pais")
    search_fields = ("nombre", "codigo_iata")


class AsientoInline(admin.TabularInline):
    model = Asiento
    extra = 0
    fields = ("fila", "numero", "clase", "precio", "estado")


@admin.register(Vuelo)
class VueloAdmin(admin.ModelAdmin):
    list_display = (
        "numero_vuelo",
        "aerolinea",
        "origen",
        "destino",
        "fecha_salida",
        "fecha_llegada",
        "precio_base",
        "estado",
        "activo",
    )
    list_filter = ("estado", "activo", "aerolinea")
    search_fields = ("numero_vuelo", "origen", "destino")
    date_hierarchy = "fecha_salida"
    inlines = [AsientoInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("aerolinea")


@admin.register(Asiento)
class AsientoAdmin(admin.ModelAdmin):
    list_display = ("vuelo", "fila", "numero", "clase", "precio", "estado", "bloqueado_hasta")
    list_filter = ("estado", "clase")
    search_fields = ("vuelo__numero_vuelo", "fila", "numero")
    list_select_related = ("vuelo",)
    autocomplete_fields = ("vuelo",)


class ReservaPasajeroInline(admin.TabularInline):
    model = ReservaPasajero
    extra = 0
    fields = (
        "pasajero",
        "asiento",
        "tarifa",
        "equipaje_bodega",
        "maletas_adicionales",
        "cargo_equipaje",
        "activo",
    )
    autocomplete_fields = ("pasajero", "asiento")


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = (
        "codigo_reserva",
        "usuario",
        "vuelo",
        "estado",
        "total",
        "fecha_creacion",
        "fecha_expiracion_bloqueo",
    )
    list_filter = ("estado", "vuelo__aerolinea")
    search_fields = ("codigo_reserva", "usuario__email", "usuario__username")
    date_hierarchy = "fecha_creacion"
    readonly_fields = ("codigo_reserva", "subtotal", "total")
    inlines = [ReservaPasajeroInline]
    list_select_related = ("usuario", "vuelo")


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "reserva",
        "monto",
        "moneda",
        "metodo",
        "estado",
        "fecha_pago",
        "transaccion_id",
    )
    list_filter = ("estado", "metodo", "moneda")
    search_fields = ("reserva__codigo_reserva", "transaccion_id")
    readonly_fields = ("fecha_creacion", "fecha_actualizacion")


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("codigo_ticket", "reserva_pasajero", "estado", "fecha_emision")
    list_filter = ("estado",)
    search_fields = ("codigo_ticket", "reserva_pasajero__reserva__codigo_reserva")


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = (
        "ticket",
        "fecha_checkin",
        "codigo_qr",
        "acepta_politicas",
        "estado",
    )
    list_filter = ("estado", "acepta_politicas")
    search_fields = ("codigo_qr", "ticket__codigo_ticket")
    readonly_fields = ("codigo_qr",)


@admin.register(Devolucion)
class DevolucionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "reserva",
        "tipo",
        "monto",
        "estado",
        "fecha_creacion",
        "cupon_codigo",
    )
    list_filter = ("estado", "tipo")
    search_fields = ("reserva__codigo_reserva", "cupon_codigo")


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "usuario",
        "tipo",
        "canal",
        "estado",
        "fecha_creacion",
        "fecha_envio",
    )
    list_filter = ("tipo", "canal", "estado")
    search_fields = ("usuario__email", "asunto", "mensaje")
    date_hierarchy = "fecha_creacion"


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "usuario",
        "accion",
        "entidad",
        "entidad_id",
        "ip",
        "fecha_creacion",
    )
    list_filter = ("accion", "entidad")
    search_fields = ("usuario__username", "entidad", "entidad_id")
    date_hierarchy = "fecha_creacion"
    readonly_fields = (
        "usuario",
        "accion",
        "entidad",
        "entidad_id",
        "detalle",
        "ip",
        "fecha_creacion",
        "fecha_actualizacion",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PromocionVueloInline(admin.TabularInline):
    model = PromocionVuelo
    extra = 0


@admin.register(Promocion)
class PromocionAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "titulo",
        "descuento_porcentaje",
        "fecha_inicio",
        "fecha_fin",
        "estado",
    )
    list_filter = ("estado",)
    search_fields = ("codigo", "titulo")
    inlines = [PromocionVueloInline]
