"""
Servicios de dominio de SKYANDES.

Concentran las operaciones que involucran varias tablas y las reglas de
negocio que no pueden expresarse solo con restricciones de base de datos.

Concurrencia:
- Se usa transaction.atomic() y select_for_update() para bloquear filas.
- En PostgreSQL select_for_update() bloquea realmente las filas; en SQLite
  es equivalente a un no-op, por lo que las pruebas funcionales se ejecutan
  igual, pero la garantía de concurrencia real requiere PostgreSQL.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    MAX_BLOQUEO_MINUTOS,
    Asiento,
    Auditoria,
    CheckIn,
    Devolucion,
    Notificacion,
    Pago,
    Promocion,
    Reserva,
    ReservaPasajero,
    Ticket,
    Vuelo,
)


# ---------------------------------------------------------------------------
# Excepciones de dominio
# ---------------------------------------------------------------------------


class SkyAndesError(Exception):
    """Error de negocio controlado."""


class AsientoNoDisponible(SkyAndesError):
    pass


class ReservaNoModificable(SkyAndesError):
    pass


class ReservaExpirada(SkyAndesError):
    pass


class MontoIncorrecto(SkyAndesError):
    pass


class CheckInFueraDePlazo(SkyAndesError):
    pass


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def registrar_auditoria(
    *,
    usuario=None,
    accion: str,
    entidad: str,
    entidad_id: str | int = "",
    detalle: dict | None = None,
    ip: str | None = None,
) -> Auditoria:
    return Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        entidad=entidad,
        entidad_id=str(entidad_id or ""),
        detalle=detalle or {},
        ip=ip,
    )


def crear_notificacion(
    *,
    usuario,
    tipo: str,
    asunto: str,
    mensaje: str,
    canal: str = Notificacion.Canal.EMAIL,
    reserva=None,
    vuelo=None,
    estado: str = Notificacion.Estado.PENDIENTE,
) -> Notificacion:
    return Notificacion.objects.create(
        usuario=usuario,
        tipo=tipo,
        canal=canal,
        asunto=asunto,
        mensaje=mensaje,
        reserva=reserva,
        vuelo=vuelo,
        estado=estado,
    )


# ---------------------------------------------------------------------------
# Reservas e inventario de asientos
# ---------------------------------------------------------------------------


@transaction.atomic
def crear_reserva(
    *,
    usuario,
    vuelo: Vuelo,
    pasajeros,
    asientos=None,
    promocion: Promocion | None = None,
    impuestos: Decimal = Decimal("0.00"),
) -> Reserva:
    """
    Crea una reserva con uno o varios pasajeros y, opcionalmente, sus
    asientos. Deja la reserva en PENDIENTE_PAGO y bloquea los asientos
    por un máximo de 10 minutos (RN-03/RN-04).
    """
    vuelo = Vuelo.objects.select_for_update().get(pk=vuelo.pk)
    pasajeros = list(pasajeros)
    if not pasajeros:
        raise SkyAndesError("La reserva debe tener al menos un pasajero (RN-01).")

    if asientos is None:
        asientos = [None] * len(pasajeros)
    asientos = list(asientos)
    if len(asientos) != len(pasajeros):
        raise SkyAndesError("Debe indicar un asiento por cada pasajero.")

    descuento = Decimal("0.00")

    reserva = Reserva.objects.create(
        usuario=usuario,
        vuelo=vuelo,
        promocion=promocion,
        impuestos=impuestos,
        estado=Reserva.Estado.PENDIENTE_PAGO,
        fecha_expiracion_bloqueo=timezone.now()
        + timedelta(minutes=MAX_BLOQUEO_MINUTOS),
    )

    for pasajero, asiento in zip(pasajeros, asientos):
        tarifa = asiento.precio if asiento else vuelo.precio_base
        ReservaPasajero.objects.create(
            reserva=reserva,
            pasajero=pasajero,
            asiento=asiento,
            tarifa=tarifa,
        )

    reserva.recalcular_totales(guardar=False)
    if promocion and promocion.vigente:
        descuento = (
            reserva.subtotal * promocion.descuento_porcentaje / Decimal("100")
        ).quantize(Decimal("0.01"))
        reserva.descuento = descuento
        reserva.total = max(
            Decimal("0.00"),
            reserva.subtotal + reserva.impuestos - reserva.descuento,
        )
    reserva.save()

    if any(asientos):
        bloquear_asientos(reserva.pk, [a.pk for a in asientos if a])

    registrar_auditoria(
        usuario=usuario,
        accion=Auditoria.Accion.RESERVAR,
        entidad="Reserva",
        entidad_id=reserva.pk,
        detalle={"pnr": reserva.codigo_reserva, "total": str(reserva.total)},
    )
    return reserva


@transaction.atomic
def bloquear_asientos(
    reserva_id: int, asiento_ids: list[int], minutos: int = MAX_BLOQUEO_MINUTOS
) -> list[Asiento]:
    """
    Bloquea temporalmente los asientos de una reserva.

    - Valida que el asiento pertenezca al vuelo de la reserva.
    - No permite robar un bloqueo vigente de otra reserva.
    - Libera bloqueos vencidos antes de evaluar la disponibilidad.
    - Nunca permite un bloqueo superior a 10 minutos (RN-04).
    """
    if minutos > MAX_BLOQUEO_MINUTOS:
        raise SkyAndesError("RN-04: el bloqueo máximo es de 10 minutos.")

    reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
    if reserva.estado != Reserva.Estado.PENDIENTE_PAGO:
        raise ReservaNoModificable(
            "Solo se pueden bloquear asientos de reservas pendientes de pago."
        )

    ahora = timezone.now()
    expiracion = ahora + timedelta(minutes=max(1, minutos))

    ids = [int(pk) for pk in asiento_ids]
    if len(ids) != len(set(ids)):
        raise SkyAndesError("No se puede repetir el mismo asiento.")

    asientos = list(Asiento.objects.select_for_update().filter(pk__in=ids))
    if len(asientos) != len(ids):
        raise AsientoNoDisponible("Uno o más asientos no existen.")

    for asiento in asientos:
        if asiento.vuelo_id != reserva.vuelo_id:
            raise AsientoNoDisponible(
                f"El asiento {asiento} no pertenece al vuelo de la reserva."
            )
        if asiento.estado == Asiento.Estado.OCUPADO:
            raise AsientoNoDisponible(f"El asiento {asiento} ya está ocupado.")
        if asiento.estado == Asiento.Estado.INHABILITADO:
            raise AsientoNoDisponible(f"El asiento {asiento} está inhabilitado.")
        if (
            asiento.estado == Asiento.Estado.BLOQUEADO
            and asiento.bloqueado_hasta
            and asiento.bloqueado_hasta > ahora
            and asiento.bloqueado_por_id != reserva.pk
        ):
            raise AsientoNoDisponible(
                f"El asiento {asiento} está bloqueado por otra reserva."
            )

    for asiento in asientos:
        asiento.estado = Asiento.Estado.BLOQUEADO
        asiento.bloqueado_hasta = expiracion
        asiento.bloqueado_por = reserva
        asiento.save(
            update_fields=[
                "estado",
                "bloqueado_hasta",
                "bloqueado_por",
                "fecha_actualizacion",
            ]
        )

    reserva.fecha_expiracion_bloqueo = expiracion
    reserva.save(update_fields=["fecha_expiracion_bloqueo", "fecha_actualizacion"])
    return asientos


@transaction.atomic
def asignar_asiento(reserva_pasajero_id: int, asiento_id: int, minutos: int = 10):
    """Asigna (o cambia) el asiento de un pasajero y lo bloquea 10 minutos."""
    rp = (
        ReservaPasajero.objects.select_for_update()
        .select_related("reserva", "asiento")
        .get(pk=reserva_pasajero_id)
    )
    reserva = Reserva.objects.select_for_update().get(pk=rp.reserva_id)
    if reserva.estado != Reserva.Estado.PENDIENTE_PAGO:
        raise ReservaNoModificable("La reserva ya no está pendiente de pago.")

    asiento = Asiento.objects.select_for_update().get(pk=asiento_id)
    if asiento.vuelo_id != reserva.vuelo_id:
        raise AsientoNoDisponible("El asiento pertenece a otro vuelo.")
    if asiento.estado == Asiento.Estado.OCUPADO:
        raise AsientoNoDisponible("El asiento ya está ocupado.")
    if (
        asiento.estado == Asiento.Estado.BLOQUEADO
        and asiento.bloqueado_hasta
        and asiento.bloqueado_hasta > timezone.now()
        and asiento.bloqueado_por_id != reserva.pk
    ):
        raise AsientoNoDisponible("El asiento está bloqueado por otra reserva.")

    anterior = rp.asiento
    rp.asiento = asiento
    rp.tarifa = asiento.precio
    rp.activo = True
    rp.save(update_fields=["asiento", "tarifa", "activo", "fecha_actualizacion"])

    if anterior and anterior.pk != asiento.pk and anterior.estado == Asiento.Estado.BLOQUEADO:
        anterior.estado = Asiento.Estado.DISPONIBLE
        anterior.bloqueado_hasta = None
        anterior.bloqueado_por = None
        anterior.save(
            update_fields=[
                "estado",
                "bloqueado_hasta",
                "bloqueado_por",
                "fecha_actualizacion",
            ]
        )

    bloquear_asientos(reserva.pk, [asiento.pk], minutos=minutos)
    reserva.recalcular_totales()
    return rp


@transaction.atomic
def aplicar_promocion(reserva_id: int, promocion_id: int) -> Reserva:
    """Aplica una promoción vigente y recalcula el total de la reserva."""
    reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
    promocion = Promocion.objects.get(pk=promocion_id)
    if not promocion.vigente:
        raise SkyAndesError("La promoción no está vigente.")

    reserva.promocion = promocion
    reserva.recalcular_totales(guardar=False)
    reserva.descuento = (
        reserva.subtotal * promocion.descuento_porcentaje / Decimal("100")
    ).quantize(Decimal("0.01"))
    reserva.total = max(
        Decimal("0.00"), reserva.subtotal + reserva.impuestos - reserva.descuento
    )
    reserva.save(
        update_fields=[
            "promocion",
            "subtotal",
            "descuento",
            "total",
            "fecha_actualizacion",
        ]
    )
    return reserva


# ---------------------------------------------------------------------------
# Pagos (RN-05, RN-06)
# ---------------------------------------------------------------------------


@transaction.atomic
def procesar_pago(
    reserva_id: int,
    *,
    aprobado: bool,
    monto: Decimal | None = None,
    transaccion_id: str | None = None,
    respuesta_pasarela: dict | None = None,
    usuario=None,
    ip: str | None = None,
) -> Pago:
    """
    Registra el resultado de la pasarela y aplica la regla correspondiente:

    - Pago aprobado: reserva CONFIRMADA + asientos OCUPADOS + tickets emitidos.
    - Pago rechazado: reserva FALLIDA + asientos liberados.
    - Bloqueo expirado: reserva EXPIRADA + asientos liberados.

    El monto aprobado debe coincidir con el total de la reserva para evitar
    confirmaciones por montos manipulados desde el cliente.
    """
    reserva = (
        Reserva.objects.select_for_update()
        .select_related("vuelo", "usuario")
        .get(pk=reserva_id)
    )

    ahora = timezone.now()
    if (
        reserva.estado == Reserva.Estado.PENDIENTE_PAGO
        and reserva.fecha_expiracion_bloqueo
        and reserva.fecha_expiracion_bloqueo <= ahora
    ):
        reserva.estado = Reserva.Estado.EXPIRADA
        reserva.liberar_asientos()
        pago = Pago.objects.create(
            reserva=reserva,
            monto=monto if monto is not None else reserva.total,
            estado=Pago.Estado.EXPIRADO,
            transaccion_id=transaccion_id,
            fecha_pago=ahora,
            respuesta_pasarela=respuesta_pasarela or {"motivo": "bloqueo expirado"},
        )
        registrar_auditoria(
            usuario=usuario or reserva.usuario,
            accion=Auditoria.Accion.PAGAR,
            entidad="Reserva",
            entidad_id=reserva.pk,
            detalle={"resultado": "EXPIRADO", "pnr": reserva.codigo_reserva},
            ip=ip,
        )
        return pago

    if reserva.estado != Reserva.Estado.PENDIENTE_PAGO:
        raise ReservaNoModificable(
            f"La reserva está en estado {reserva.estado} y no admite pagos."
        )

    monto = reserva.total if monto is None else Decimal(monto)
    if aprobado and monto != reserva.total:
        raise MontoIncorrecto(
            f"El monto aprobado ({monto}) no coincide con el total "
            f"de la reserva ({reserva.total})."
        )

    pago = Pago.objects.create(
        reserva=reserva,
        monto=monto,
        estado=Pago.Estado.APROBADO if aprobado else Pago.Estado.RECHAZADO,
        transaccion_id=transaccion_id,
        fecha_pago=ahora,
        respuesta_pasarela=respuesta_pasarela or {},
    )

    if aprobado:
        # Verificar que los asientos sigan disponibles/bloqueados por esta reserva.
        rps = list(
            reserva.pasajeros.filter(activo=True)
            .select_related("asiento", "pasajero")
        )
        asientos = [
            rp.asiento for rp in rps if rp.asiento_id is not None
        ]
        if asientos:
            bloqueados = list(
                Asiento.objects.select_for_update().filter(
                    pk__in=[a.pk for a in asientos]
                )
            )
            for asiento in bloqueados:
                if asiento.estado == Asiento.Estado.OCUPADO:
                    raise AsientoNoDisponible(
                        f"El asiento {asiento} fue ocupado por otra reserva."
                    )
                if (
                    asiento.estado == Asiento.Estado.BLOQUEADO
                    and asiento.bloqueado_por_id not in (None, reserva.pk)
                    and asiento.bloqueado_hasta
                    and asiento.bloqueado_hasta > ahora
                ):
                    raise AsientoNoDisponible(
                        f"El asiento {asiento} está bloqueado por otra reserva."
                    )

        reserva.confirmar()

        Asiento.objects.filter(
            pk__in=[a.pk for a in asientos]
        ).update(
            estado=Asiento.Estado.OCUPADO,
            bloqueado_hasta=None,
            bloqueado_por=None,
            fecha_actualizacion=ahora,
        )

        for rp in rps:
            Ticket.objects.get_or_create(
                reserva_pasajero=rp,
                defaults={"estado": Ticket.Estado.EMITIDO},
            )

        crear_notificacion(
            usuario=reserva.usuario,
            tipo=Notificacion.Tipo.CONFIRMACION_RESERVA,
            asunto=f"Reserva {reserva.codigo_reserva} confirmada",
            mensaje=(
                f"Su pago fue aprobado. La reserva {reserva.codigo_reserva} "
                f"para el vuelo {reserva.vuelo.numero_vuelo} está confirmada."
            ),
            reserva=reserva,
            vuelo=reserva.vuelo,
        )
        crear_notificacion(
            usuario=reserva.usuario,
            tipo=Notificacion.Tipo.CONFIRMACION_RESERVA,
            asunto="Pago aprobado",
            mensaje=f"Pago aprobado por ${reserva.total}.",
            canal=Notificacion.Canal.POPUP,
            reserva=reserva,
            vuelo=reserva.vuelo,
            estado=Notificacion.Estado.ENVIADA,
        )
        resultado = "APROBADO"
    else:
        reserva.estado = Reserva.Estado.FALLIDA
        reserva.save(
            update_fields=["estado", "fecha_actualizacion"]
        )
        reserva.liberar_asientos()
        crear_notificacion(
            usuario=reserva.usuario,
            tipo=Notificacion.Tipo.PAGO,
            asunto=f"Pago rechazado para la reserva {reserva.codigo_reserva}",
            mensaje=(
                "El pago fue rechazado o no se completó. Los asientos fueron "
                "liberados y la reserva quedó como fallida."
            ),
            reserva=reserva,
            vuelo=reserva.vuelo,
        )
        resultado = "RECHAZADO"

    registrar_auditoria(
        usuario=usuario or reserva.usuario,
        accion=Auditoria.Accion.PAGAR,
        entidad="Pago",
        entidad_id=pago.pk,
        detalle={
            "resultado": resultado,
            "pnr": reserva.codigo_reserva,
            "monto": str(monto),
            "transaccion_id": transaccion_id,
        },
        ip=ip,
    )
    return pago


@transaction.atomic
def liberar_bloqueos_expirados() -> dict:
    """
    Tarea periódica (cron / comando) que libera asientos vencidos y expira
    reservas pendientes. Devuelve contadores para monitoreo.
    """
    ahora = timezone.now()

    reservas_vencidas = list(
        Reserva.objects.select_for_update().filter(
            estado=Reserva.Estado.PENDIENTE_PAGO,
            fecha_expiracion_bloqueo__isnull=False,
            fecha_expiracion_bloqueo__lte=ahora,
        )
    )
    for reserva in reservas_vencidas:
        reserva.estado = Reserva.Estado.EXPIRADA
        reserva.save(update_fields=["estado", "fecha_actualizacion"])
        reserva.liberar_asientos()

    asientos_liberados = Asiento.objects.filter(
        estado=Asiento.Estado.BLOQUEADO,
        bloqueado_hasta__lte=ahora,
    ).update(
        estado=Asiento.Estado.DISPONIBLE,
        bloqueado_hasta=None,
        bloqueado_por=None,
        fecha_actualizacion=ahora,
    )

    return {
        "reservas_expiradas": len(reservas_vencidas),
        "asientos_liberados": asientos_liberados,
    }


# ---------------------------------------------------------------------------
# Check-in (RF-08)
# ---------------------------------------------------------------------------


@transaction.atomic
def registrar_check_in(
    reserva_pasajero_id: int,
    *,
    acepta_politicas: bool = True,
    usuario=None,
    ip: str | None = None,
) -> CheckIn:
    """
    Realiza el check-in validando el plazo de 48 a 2 horas antes de la salida
    y genera el identificador QR del pase de abordar.
    """
    rp = (
        ReservaPasajero.objects.select_for_update()
        .select_related("reserva", "reserva__vuelo", "pasajero")
        .get(pk=reserva_pasajero_id)
    )
    if rp.reserva.estado != Reserva.Estado.CONFIRMADA:
        raise ReservaNoModificable("Solo se puede hacer check-in de reservas confirmadas.")

    ticket, _ = Ticket.objects.get_or_create(
        reserva_pasajero=rp,
        defaults={"estado": Ticket.Estado.EMITIDO},
    )
    if hasattr(ticket, "check_in"):
        return ticket.check_in

    check_in = CheckIn(
        ticket=ticket,
        acepta_politicas=acepta_politicas,
    )
    try:
        check_in.save()
    except Exception as exc:  # ValidationError de la regla de plazo
        raise CheckInFueraDePlazo(str(exc)) from exc

    registrar_auditoria(
        usuario=usuario or rp.reserva.usuario,
        accion=Auditoria.Accion.CHECK_IN,
        entidad="CheckIn",
        entidad_id=check_in.pk,
        detalle={
            "ticket": ticket.codigo_ticket,
            "pnr": rp.reserva.codigo_reserva,
            "qr": check_in.codigo_qr,
        },
        ip=ip,
    )
    return check_in


# ---------------------------------------------------------------------------
# Cambios de vuelo y notificaciones (RN-08, RN-10)
# ---------------------------------------------------------------------------


@transaction.atomic
def cambiar_estado_vuelo(
    vuelo_id: int,
    nuevo_estado: str,
    *,
    usuario=None,
    motivo: str = "",
    ip: str | None = None,
) -> Vuelo:
    """
    Cambia el estado de un vuelo y notifica a los pasajeros afectados por
    correo y pop-up. También deja registro de auditoría.
    """
    if nuevo_estado not in Vuelo.Estado.values:
        raise SkyAndesError(f"Estado de vuelo inválido: {nuevo_estado}")

    vuelo = Vuelo.objects.select_for_update().get(pk=vuelo_id)
    anterior = vuelo.estado
    vuelo.estado = nuevo_estado
    vuelo.save(update_fields=["estado", "fecha_actualizacion"])

    tipos = {
        Vuelo.Estado.RETRASADO: Notificacion.Tipo.RETRASO,
        Vuelo.Estado.REPROGRAMADO: Notificacion.Tipo.REPROGRAMACION,
        Vuelo.Estado.CANCELADO: Notificacion.Tipo.CANCELACION,
    }
    notificaciones = 0
    tipo = tipos.get(nuevo_estado)
    if tipo:
        reservas = (
            Reserva.objects.filter(
                vuelo=vuelo, estado=Reserva.Estado.CONFIRMADA
            )
            .select_related("usuario")
            .distinct()
        )
        for reserva in reservas:
            for canal in (Notificacion.Canal.EMAIL, Notificacion.Canal.POPUP):
                crear_notificacion(
                    usuario=reserva.usuario,
                    tipo=tipo,
                    canal=canal,
                    asunto=f"Vuelo {vuelo.numero_vuelo}: {vuelo.get_estado_display()}",
                    mensaje=(
                        f"El vuelo {vuelo.numero_vuelo} ({vuelo.origen} → "
                        f"{vuelo.destino}) cambió de {anterior} a {nuevo_estado}. "
                        f"{motivo}".strip()
                    ),
                    reserva=reserva,
                    vuelo=vuelo,
                )
                notificaciones += 1

    registrar_auditoria(
        usuario=usuario,
        accion=Auditoria.Accion.ACTUALIZAR,
        entidad="Vuelo",
        entidad_id=vuelo.pk,
        detalle={
            "estado_anterior": anterior,
            "estado_nuevo": nuevo_estado,
            "notificaciones": notificaciones,
            "motivo": motivo,
        },
        ip=ip,
    )
    return vuelo


# ---------------------------------------------------------------------------
# Devoluciones (RF-10)
# ---------------------------------------------------------------------------


@transaction.atomic
def solicitar_devolucion(
    *,
    reserva_id: int,
    monto: Decimal,
    motivo: str,
    tipo: str = Devolucion.Tipo.REEMBOLSO,
    pago_id: int | None = None,
    usuario=None,
    comprobante: str = "",
) -> Devolucion:
    reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
    pago = Pago.objects.filter(pk=pago_id).first() if pago_id else None

    devolucion = Devolucion(
        reserva=reserva,
        pago=pago,
        usuario_solicita=usuario or reserva.usuario,
        tipo=tipo,
        monto=Decimal(monto),
        motivo=motivo,
        comprobante=comprobante,
    )
    devolucion.full_clean()
    devolucion.save()

    if tipo == Devolucion.Tipo.CUPON and not devolucion.cupon_codigo:
        devolucion.cupon_codigo = f"SKY-{reserva.codigo_reserva}-{devolucion.pk}"
        devolucion.save(update_fields=["cupon_codigo", "fecha_actualizacion"])

    crear_notificacion(
        usuario=reserva.usuario,
        tipo=Notificacion.Tipo.DEVOLUCION,
        asunto=f"Devolución solicitada para {reserva.codigo_reserva}",
        mensaje=f"Se registró una solicitud de devolución por ${devolucion.monto}.",
        reserva=reserva,
        vuelo=reserva.vuelo,
    )
    registrar_auditoria(
        usuario=usuario or reserva.usuario,
        accion=Auditoria.Accion.DEVOLVER,
        entidad="Devolucion",
        entidad_id=devolucion.pk,
        detalle={
            "pnr": reserva.codigo_reserva,
            "monto": str(devolucion.monto),
            "tipo": tipo,
        },
    )
    return devolucion
