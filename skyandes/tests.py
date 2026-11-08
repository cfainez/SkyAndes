"""
Pruebas automatizadas de las reglas de negocio y del modelo de datos.

Ejecutar con:
    python manage.py test skyandes -v 2
"""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

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
    Reserva,
    ReservaPasajero,
    Rol,
    Ticket,
    Usuario,
    Vuelo,
)
from .services import (
    AsientoNoDisponible,
    CheckInFueraDePlazo,
    MontoIncorrecto,
    SkyAndesError,
    bloquear_asientos,
    cambiar_estado_vuelo,
    crear_reserva,
    liberar_bloqueos_expirados,
    procesar_pago,
    registrar_check_in,
    solicitar_devolucion,
)


class SkyAndesBaseTestCase(TestCase):
    """Datos comunes para las pruebas del MVP."""

    @classmethod
    def setUpTestData(cls):
        cls.rol_pasajero = Rol.objects.create(nombre=Rol.Nombre.PASAJERO)
        cls.rol_vendedor = Rol.objects.create(nombre=Rol.Nombre.VENDEDOR)
        cls.rol_admin = Rol.objects.create(nombre=Rol.Nombre.ADMINISTRADOR)

        cls.usuario = Usuario.objects.create_user(
            username="pasajero1",
            email="pasajero1@skyandes.cl",
            password="ClaveSegura123",
            first_name="Ana",
            last_name="Pérez",
            rol=cls.rol_pasajero,
            rut="11111111-1",
        )
        cls.vendedor = Usuario.objects.create_user(
            username="vendedor1",
            email="vendedor1@skyandes.cl",
            password="ClaveSegura123",
            first_name="Vendedor",
            last_name="Uno",
            rol=cls.rol_vendedor,
        )
        cls.admin = Usuario.objects.create_user(
            username="admin1",
            email="admin1@skyandes.cl",
            password="ClaveSegura123",
            first_name="Admin",
            last_name="Uno",
            rol=cls.rol_admin,
            is_staff=True,
        )

        cls.aerolinea = Aerolinea.objects.create(
            nombre="SkyAndes", codigo_iata="SKY", pais="Chile"
        )
        ahora = timezone.now()
        cls.vuelo = Vuelo.objects.create(
            aerolinea=cls.aerolinea,
            numero_vuelo="SK100",
            origen="Santiago",
            destino="Antofagasta",
            fecha_salida=ahora + timedelta(hours=24),
            fecha_llegada=ahora + timedelta(hours=26),
            precio_base=Decimal("50000.00"),
        )
        cls.asiento1 = Asiento.objects.create(
            vuelo=cls.vuelo, fila="1", numero="A", precio=Decimal("50000.00")
        )
        cls.asiento2 = Asiento.objects.create(
            vuelo=cls.vuelo, fila="1", numero="B", precio=Decimal("50000.00")
        )
        cls.asiento3 = Asiento.objects.create(
            vuelo=cls.vuelo, fila="1", numero="C", precio=Decimal("50000.00")
        )

        cls.pasajero1 = Pasajero.objects.create(
            usuario=cls.usuario,
            nombre_completo="Ana Pérez",
            rut="12345678-9",
            email="ana.perez@correo.cl",
        )
        cls.pasajero2 = Pasajero.objects.create(
            nombre_completo="Luis Soto",
            rut="9876543-2",
            email="luis.soto@correo.cl",
        )

    # -- Helpers ---------------------------------------------------------
    def crear_reserva(self, pasajeros=None, asientos=None, vuelo=None, promocion=None):
        return crear_reserva(
            usuario=self.usuario,
            vuelo=vuelo or self.vuelo,
            pasajeros=[self.pasajero1] if pasajeros is None else pasajeros,
            asientos=asientos,
            promocion=promocion,
        )

    def pagar(self, reserva, aprobado=True):
        return procesar_pago(
            reserva.pk,
            aprobado=aprobado,
            monto=reserva.total,
            transaccion_id=f"TX-{reserva.codigo_reserva}-{timezone.now().timestamp()}",
            respuesta_pasarela={"estado": "APROBADO" if aprobado else "RECHAZADO"},
            usuario=self.usuario,
        )


class AutenticacionYUsuariosTests(SkyAndesBaseTestCase):
    def test_rol_y_acceso_por_rol(self):
        self.assertTrue(self.usuario.es_pasajero)
        self.assertFalse(self.usuario.es_vendedor)
        self.assertTrue(self.vendedor.es_vendedor)
        self.assertTrue(self.admin.es_administrador)
        self.assertTrue(self.usuario.puede_iniciar_sesion)

    def test_usuario_inactivo_no_puede_iniciar_sesion(self):
        self.usuario.estado = Usuario.Estado.BLOQUEADO
        self.usuario.save()
        self.assertFalse(self.usuario.puede_iniciar_sesion)

    def test_email_de_usuario_es_unico(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create_user(
                username="otro",
                email="pasajero1@skyandes.cl",
                password="x",
            )


class PasajeroTests(SkyAndesBaseTestCase):
    def test_run_duplicado_se_rechaza(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Pasajero.objects.create(
                nombre_completo="Duplicado",
                rut=self.pasajero1.rut,
                email="otro@correo.cl",
            )

    def test_email_duplicado_se_rechaza(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Pasajero.objects.create(
                nombre_completo="Duplicado",
                rut="22222222-2",
                email=self.pasajero1.email,
            )

    def test_pasajero_requiere_identificacion(self):
        pasajero = Pasajero(
            nombre_completo="Sin documento",
            email="sin.documento@correo.cl",
        )
        with self.assertRaises(ValidationError):
            pasajero.full_clean()


class VueloYAsientoTests(SkyAndesBaseTestCase):
    def test_consulta_de_vuelos(self):
        encontrados = Vuelo.objects.filter(
            origen="Santiago", destino="Antofagasta", activo=True
        )
        self.assertIn(self.vuelo, encontrados)

    def test_vuelo_valida_fechas(self):
        vuelo = Vuelo(
            aerolinea=self.aerolinea,
            numero_vuelo="SK200",
            origen="Santiago",
            destino="Iquique",
            fecha_salida=timezone.now() + timedelta(days=1),
            fecha_llegada=timezone.now(),
            precio_base=Decimal("10000"),
        )
        with self.assertRaises(ValidationError):
            vuelo.full_clean()

    def test_asiento_unico_por_vuelo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Asiento.objects.create(
                vuelo=self.vuelo, fila="1", numero="A", precio=Decimal("1")
            )


class ReservaTests(SkyAndesBaseTestCase):
    def test_reserva_con_varios_pasajeros(self):
        reserva = self.crear_reserva(
            pasajeros=[self.pasajero1, self.pasajero2],
            asientos=[self.asiento1, self.asiento2],
        )
        self.assertEqual(reserva.pasajeros.count(), 2)
        self.assertEqual(reserva.total, Decimal("100000.00"))
        self.assertEqual(reserva.estado, Reserva.Estado.PENDIENTE_PAGO)
        self.assertTrue(reserva.codigo_reserva)
        self.assertTrue(reserva.bloqueo_vigente)

        for asiento in (self.asiento1, self.asiento2):
            asiento.refresh_from_db()
            self.assertEqual(asiento.estado, Asiento.Estado.BLOQUEADO)
            self.assertIsNotNone(asiento.bloqueado_hasta)

    def test_reserva_sin_pasajeros_se_rechaza(self):
        with self.assertRaises(SkyAndesError):
            self.crear_reserva(pasajeros=[])

    def test_asiento_asignado_una_sola_vez(self):
        reserva1 = self.crear_reserva(asientos=[self.asiento1])
        self.assertIsNotNone(reserva1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.crear_reserva(asientos=[self.asiento1])


class BloqueoAsientosTests(SkyAndesBaseTestCase):
    def test_bloqueo_no_puede_superar_10_minutos(self):
        reserva = self.crear_reserva()
        with self.assertRaises(SkyAndesError):
            bloquear_asientos(
                reserva.pk, [self.asiento1.pk], minutos=11
            )

    def test_no_se_puede_bloquear_asiento_de_otra_reserva(self):
        reserva1 = self.crear_reserva(asientos=[self.asiento1])
        reserva2 = self.crear_reserva(pasajeros=[self.pasajero2])
        with self.assertRaises(AsientoNoDisponible):
            bloquear_asientos(reserva2.pk, [self.asiento1.pk])
        self.assertIsNotNone(reserva1)

    def test_expiracion_del_bloqueo_libera_asientos(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        vencido = timezone.now() - timedelta(minutes=1)
        Reserva.objects.filter(pk=reserva.pk).update(
            fecha_expiracion_bloqueo=vencido
        )
        Asiento.objects.filter(pk=self.asiento1.pk).update(
            bloqueado_hasta=vencido
        )

        resultado = liberar_bloqueos_expirados()

        reserva.refresh_from_db()
        self.asiento1.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.Estado.EXPIRADA)
        self.assertEqual(self.asiento1.estado, Asiento.Estado.DISPONIBLE)
        self.assertEqual(resultado["reservas_expiradas"], 1)
        self.assertFalse(
            ReservaPasajero.objects.get(reserva=reserva).activo
        )


class PagoTests(SkyAndesBaseTestCase):
    def test_pago_aprobado_confirma_reserva_y_emite_tickets(self):
        reserva = self.crear_reserva(
            pasajeros=[self.pasajero1, self.pasajero2],
            asientos=[self.asiento1, self.asiento2],
        )
        pago = self.pagar(reserva, aprobado=True)

        reserva.refresh_from_db()
        self.asiento1.refresh_from_db()
        self.asiento2.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.Estado.CONFIRMADA)
        self.assertIsNotNone(reserva.fecha_confirmacion)
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)
        self.assertEqual(self.asiento1.estado, Asiento.Estado.OCUPADO)
        self.assertEqual(Ticket.objects.filter(reserva_pasajero__reserva=reserva).count(), 2)
        self.assertGreaterEqual(
            Notificacion.objects.filter(reserva=reserva).count(), 2
        )
        self.assertTrue(
            Auditoria.objects.filter(entidad="Pago", entidad_id=str(pago.pk)).exists()
        )

    def test_pago_rechazado_libera_asientos(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        pago = self.pagar(reserva, aprobado=False)

        reserva.refresh_from_db()
        self.asiento1.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.Estado.FALLIDA)
        self.assertEqual(pago.estado, Pago.Estado.RECHAZADO)
        self.assertEqual(self.asiento1.estado, Asiento.Estado.DISPONIBLE)
        self.assertTrue(
            Notificacion.objects.filter(
                reserva=reserva, tipo=Notificacion.Tipo.PAGO
            ).exists()
        )

    def test_pago_con_monto_incorrecto_no_confirma(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        with self.assertRaises(MontoIncorrecto):
            procesar_pago(
                reserva.pk,
                aprobado=True,
                monto=Decimal("1.00"),
                transaccion_id="TX-MALO",
            )
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, Reserva.Estado.PENDIENTE_PAGO)
        self.assertFalse(Pago.objects.filter(reserva=reserva).exists())


class CheckInTests(SkyAndesBaseTestCase):
    def test_check_in_genera_qr(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        self.pagar(reserva, aprobado=True)
        rp = reserva.pasajeros.get()

        check_in = registrar_check_in(rp.pk, acepta_politicas=True, usuario=self.usuario)

        self.assertIsInstance(check_in, CheckIn)
        self.assertTrue(check_in.codigo_qr.startswith("SKY-"))
        self.assertTrue(check_in.acepta_politicas)
        self.assertEqual(check_in.ticket.reserva_pasajero, rp)

    def test_check_in_fuera_de_plazo(self):
        ahora = timezone.now()
        vuelo_lejano = Vuelo.objects.create(
            aerolinea=self.aerolinea,
            numero_vuelo="SK900",
            origen="Santiago",
            destino="Punta Arenas",
            fecha_salida=ahora + timedelta(days=5),
            fecha_llegada=ahora + timedelta(days=5, hours=3),
            precio_base=Decimal("70000.00"),
        )
        asiento = Asiento.objects.create(
            vuelo=vuelo_lejano, fila="2", numero="A", precio=Decimal("70000.00")
        )
        reserva = self.crear_reserva(asientos=[asiento], vuelo=vuelo_lejano)
        self.pagar(reserva, aprobado=True)
        rp = reserva.pasajeros.get()

        with self.assertRaises(CheckInFueraDePlazo):
            registrar_check_in(rp.pk, acepta_politicas=True)


class DevolucionYNotificacionTests(SkyAndesBaseTestCase):
    def test_registro_de_devolucion(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        pago = self.pagar(reserva, aprobado=True)

        devolucion = solicitar_devolucion(
            reserva_id=reserva.pk,
            monto=Decimal("10000.00"),
            motivo="Cambio de planes",
            pago_id=pago.pk,
            usuario=self.usuario,
        )
        self.assertEqual(devolucion.estado, Devolucion.Estado.SOLICITADA)
        self.assertEqual(devolucion.reserva, reserva)
        self.assertTrue(
            Notificacion.objects.filter(
                reserva=reserva, tipo=Notificacion.Tipo.DEVOLUCION
            ).exists()
        )

    def test_devolucion_no_supera_monto_del_pago(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        pago = self.pagar(reserva, aprobado=True)
        with self.assertRaises(ValidationError):
            solicitar_devolucion(
                reserva_id=reserva.pk,
                monto=Decimal("999999.00"),
                motivo="Monto inválido",
                pago_id=pago.pk,
                usuario=self.usuario,
            )

    def test_cambio_de_vuelo_genera_notificaciones(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        self.pagar(reserva, aprobado=True)
        Notificacion.objects.all().delete()

        cambiar_estado_vuelo(
            self.vuelo.pk,
            Vuelo.Estado.CANCELADO,
            usuario=self.admin,
            motivo="Condiciones climáticas",
        )

        self.assertEqual(
            Notificacion.objects.filter(
                reserva=reserva, tipo=Notificacion.Tipo.CANCELACION
            ).count(),
            2,
        )
        self.assertTrue(
            Auditoria.objects.filter(
                entidad="Vuelo", entidad_id=str(self.vuelo.pk)
            ).exists()
        )


class EliminacionVueloTests(SkyAndesBaseTestCase):
    def test_vuelo_con_reserva_confirmada_no_se_elimina(self):
        reserva = self.crear_reserva(asientos=[self.asiento1])
        self.pagar(reserva, aprobado=True)

        with self.assertRaises(ProtectedError):
            self.vuelo.delete()

        self.vuelo.refresh_from_db()
        self.vuelo.desactivar()
        self.vuelo.refresh_from_db()
        self.assertFalse(self.vuelo.activo)
        self.assertEqual(self.vuelo.estado, Vuelo.Estado.CANCELADO)

    def test_vuelo_sin_reservas_se_puede_eliminar(self):
        ahora = timezone.now()
        vuelo = Vuelo.objects.create(
            aerolinea=self.aerolinea,
            numero_vuelo="SK901",
            origen="Santiago",
            destino="Concepción",
            fecha_salida=ahora + timedelta(days=10),
            fecha_llegada=ahora + timedelta(days=10, hours=1),
            precio_base=Decimal("30000.00"),
        )
        vuelo.delete()
        self.assertFalse(Vuelo.objects.filter(pk=vuelo.pk).exists())


class PromocionTests(SkyAndesBaseTestCase):
    def test_promocion_vigente_y_descuento(self):
        ahora = timezone.now()
        promocion = Promocion.objects.create(
            codigo="VERANO2026",
            titulo="Verano",
            descuento_porcentaje=Decimal("10.00"),
            fecha_inicio=ahora - timedelta(days=1),
            fecha_fin=ahora + timedelta(days=10),
            estado=Promocion.Estado.ACTIVA,
        )
        promocion.vuelos.add(self.vuelo)
        self.assertTrue(promocion.vigente)
        self.assertEqual(promocion.vuelos.count(), 1)

        reserva = self.crear_reserva(
            asientos=[self.asiento1], promocion=promocion
        )
        self.assertEqual(reserva.descuento, Decimal("5000.00"))
        self.assertEqual(reserva.total, Decimal("45000.00"))
