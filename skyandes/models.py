"""
Modelo de datos definitivo de SKYANDES.

Diseño corregido a partir del diagrama de clases y del documento GRUPO 1.pdf.
Se prioriza la tercera forma normal (3FN), la integridad referencial y las
reglas de negocio RN-01 a RN-10 del MVP.

Convenciones:
- Todos los importes usan Decimal (nunca float).
- Las tablas usan nombres en singular y en español, igual que el diagrama.
- Los usuarios extienden AbstractUser para integrarse con el sistema de
  autenticación y permisos de Django (RBAC).
- No se almacena ningún dato sensible de tarjetas (PAN, CVV, pista).
"""

import secrets
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser, Permission
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

# ---------------------------------------------------------------------------
# Constantes y funciones auxiliares
# ---------------------------------------------------------------------------

MAX_BLOQUEO_MINUTOS = 10  # RN-04


def generar_codigo_pnr() -> str:
    """Genera un código de reserva (PNR) de 6 caracteres alfanuméricos."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin caracteres ambiguos
    return "".join(secrets.choice(alfabeto) for _ in range(6))


def generar_codigo_ticket() -> str:
    """Genera un número de ticket electrónico de 13 dígitos."""
    return "".join(secrets.choice("0123456789") for _ in range(13))


def generar_codigo_qr() -> str:
    """Identificador único que se codifica en el QR del pase de abordar."""
    return f"SKY-{uuid.uuid4().hex}"


class ModeloBase(models.Model):
    """Campos de auditoría temporal comunes."""

    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)
    fecha_actualizacion = models.DateTimeField("fecha de actualización", auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# A. Autenticación y usuarios (RF-01, RF-02, RN-02, RN-09)
# ---------------------------------------------------------------------------


class Rol(ModeloBase):
    """Rol de acceso. Los permisos finos se enlazan con auth.Permission."""

    class Nombre(models.TextChoices):
        PASAJERO = "PASAJERO", "Pasajero"
        VENDEDOR = "VENDEDOR", "Vendedor / Agente de atención"
        ADMINISTRADOR = "ADMINISTRADOR", "Administrador"

    nombre = models.CharField(
        "nombre", max_length=30, unique=True, choices=Nombre.choices
    )
    descripcion = models.CharField("descripción", max_length=255, blank=True)
    permisos = models.ManyToManyField(
        Permission,
        verbose_name="permisos",
        blank=True,
        related_name="roles_skyandes",
        help_text="Permisos Django asociados al rol (RBAC).",
    )
    activo = models.BooleanField("activo", default=True)

    class Meta:
        db_table = "rol"
        verbose_name = "rol"
        verbose_name_plural = "roles"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return self.get_nombre_display()


class Usuario(AbstractUser, ModeloBase):
    """
    Usuario del sistema. Un solo modelo cubre pasajeros, vendedores y
    administradores; la diferencia de funciones se resuelve con el rol y
    sus permisos (RN-09), evitando tablas duplicadas.
    """

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        INACTIVO = "INACTIVO", "Inactivo"
        BLOQUEADO = "BLOQUEADO", "Bloqueado"

    email = models.EmailField("correo electrónico", unique=True)
    rol = models.ForeignKey(
        Rol,
        verbose_name="rol",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
        help_text="Se deja nulo solo para superusuarios técnicos.",
    )
    rut = models.CharField(
        "RUN",
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]$",
                message="Ingrese un RUN válido, por ejemplo 12.345.678-9.",
            )
        ],
    )
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    estado = models.CharField(
        "estado", max_length=15, choices=Estado.choices, default=Estado.ACTIVO
    )

    REQUIRED_FIELDS = ["email", "first_name", "last_name"]

    class Meta:
        db_table = "usuario"
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["username"]

    def __str__(self) -> str:
        return f"{self.get_full_name() or self.username} ({self.username})"

    # -- Helpers de rol / permisos -----------------------------------------
    def tiene_rol(self, *nombres: str) -> bool:
        return bool(self.rol_id and self.rol.nombre in nombres)

    @property
    def es_pasajero(self) -> bool:
        return self.tiene_rol(Rol.Nombre.PASAJERO)

    @property
    def es_vendedor(self) -> bool:
        return self.tiene_rol(Rol.Nombre.VENDEDOR)

    @property
    def es_administrador(self) -> bool:
        return self.is_superuser or self.tiene_rol(Rol.Nombre.ADMINISTRADOR)

    def tiene_permiso(self, codename: str) -> bool:
        """RBAC: superusuario o permiso asignado explícitamente al rol."""
        if self.is_superuser:
            return True
        return bool(
            self.rol_id
            and self.rol.permisos.filter(codename=codename).exists()
        )

    @property
    def puede_iniciar_sesion(self) -> bool:
        return self.is_active and self.estado == self.Estado.ACTIVO


class Pasajero(ModeloBase):
    """
    Pasajero identificado (RN-01, RN-02).
    Puede existir sin cuenta de usuario (venta en mostrador); si la tiene,
    se enlaza 1:1 con Usuario. Los identificadores son únicos.
    """

    usuario = models.OneToOneField(
        Usuario,
        verbose_name="usuario",
        on_delete=models.SET_NULL,
        related_name="pasajero",
        null=True,
        blank=True,
    )
    nombre_completo = models.CharField("nombre completo", max_length=150)
    rut = models.CharField(
        "RUN",
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^\d{1,2}\.?\d{3}\.?\d{3}-?[\dkK]$",
                message="Ingrese un RUN válido, por ejemplo 12.345.678-9.",
            )
        ],
    )
    pasaporte = models.CharField(
        "pasaporte", max_length=30, unique=True, null=True, blank=True
    )
    email = models.EmailField("correo electrónico", unique=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    fecha_nacimiento = models.DateField("fecha de nacimiento", null=True, blank=True)
    nacionalidad = models.CharField("nacionalidad", max_length=60, blank=True)

    class Meta:
        db_table = "pasajero"
        verbose_name = "pasajero"
        verbose_name_plural = "pasajeros"
        ordering = ["nombre_completo"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(rut__isnull=False) & ~Q(rut=""))
                    | (Q(pasaporte__isnull=False) & ~Q(pasaporte=""))
                ),
                name="pasajero_identificacion_obligatoria",
            )
        ]

    def __str__(self) -> str:
        return self.nombre_completo

    def clean(self) -> None:
        super().clean()
        if not (self.rut or self.pasaporte):
            raise ValidationError(
                "El pasajero debe tener RUN o pasaporte (RN-01/RN-02)."
            )


# ---------------------------------------------------------------------------
# B. Gestión de vuelos (RF-03, RF-04, RN-07, RN-08, RN-10)
# ---------------------------------------------------------------------------


class Aerolinea(ModeloBase):
    nombre = models.CharField("nombre", max_length=100, unique=True)
    codigo_iata = models.CharField(
        "código IATA",
        max_length=3,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Z0-9]{2,3}$",
                message="El código IATA debe tener 2 o 3 caracteres alfanuméricos.",
            )
        ],
    )
    pais = models.CharField("país", max_length=60, blank=True)
    logo_url = models.URLField("URL del logo", blank=True)
    activo = models.BooleanField("activa", default=True)

    class Meta:
        db_table = "aerolinea"
        verbose_name = "aerolínea"
        verbose_name_plural = "aerolíneas"
        ordering = ["nombre"]

    def __str__(self) -> str:
        return f"{self.nombre} ({self.codigo_iata})"


class Vuelo(ModeloBase):
    """
    Itinerario de vuelo. El borrado es lógico (campo activo) cuando existen
    reservas confirmadas (RN-07). Los cambios de estado deben pasar por
    skyandes.services.cambiar_estado_vuelo para notificar (RN-08/RN-10).
    """

    class Estado(models.TextChoices):
        PROGRAMADO = "PROGRAMADO", "Programado"
        RETRASADO = "RETRASADO", "Retrasado"
        REPROGRAMADO = "REPROGRAMADO", "Reprogramado"
        EN_VUELO = "EN_VUELO", "En vuelo"
        ATERRIZADO = "ATERRIZADO", "Aterrizado"
        CANCELADO = "CANCELADO", "Cancelado"

    aerolinea = models.ForeignKey(
        Aerolinea,
        verbose_name="aerolínea",
        on_delete=models.PROTECT,
        related_name="vuelos",
    )
    numero_vuelo = models.CharField("número de vuelo", max_length=10)
    origen = models.CharField("origen", max_length=80)
    destino = models.CharField("destino", max_length=80)
    fecha_salida = models.DateTimeField("fecha y hora de salida")
    fecha_llegada = models.DateTimeField("fecha y hora de llegada")
    precio_base = models.DecimalField(
        "precio base",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    estado = models.CharField(
        "estado", max_length=15, choices=Estado.choices, default=Estado.PROGRAMADO
    )
    activo = models.BooleanField(
        "activo",
        default=True,
        help_text="Borrado lógico. Un vuelo inactivo no se muestra al público.",
    )
    observaciones = models.TextField("observaciones", blank=True)

    class Meta:
        db_table = "vuelo"
        verbose_name = "vuelo"
        verbose_name_plural = "vuelos"
        ordering = ["fecha_salida", "numero_vuelo"]
        constraints = [
            models.UniqueConstraint(
                fields=["aerolinea", "numero_vuelo", "fecha_salida"],
                name="vuelo_unico_por_aerolinea_fecha",
            ),
            models.CheckConstraint(
                condition=Q(fecha_llegada__gt=F("fecha_salida")),
                name="vuelo_llegada_posterior_a_salida",
            ),
            models.CheckConstraint(
                condition=~Q(origen=F("destino")),
                name="vuelo_origen_distinto_destino",
            ),
            models.CheckConstraint(
                condition=Q(precio_base__gte=Decimal("0.00")),
                name="vuelo_precio_no_negativo",
            ),
        ]
        indexes = [
            models.Index(fields=["origen", "destino", "fecha_salida"]),
            models.Index(fields=["estado", "activo"]),
        ]

    def __str__(self) -> str:
        return f"{self.numero_vuelo} {self.origen}→{self.destino}"

    @property
    def tiene_reservas_confirmadas(self) -> bool:
        return self.reservas.filter(estado=Reserva.Estado.CONFIRMADA).exists()

    def puede_eliminarse_fisicamente(self) -> bool:
        return not self.tiene_reservas_confirmadas

    def desactivar(self) -> None:
        """Borrado lógico exigido por RN-07."""
        self.activo = False
        if self.estado != self.Estado.CANCELADO:
            self.estado = self.Estado.CANCELADO
        self.save(update_fields=["activo", "estado", "fecha_actualizacion"])

    def delete(self, *args, **kwargs):
        if self.tiene_reservas_confirmadas:
            raise ProtectedError(
                "RN-07: no se puede eliminar físicamente un vuelo con reservas "
                "confirmadas. Use desactivar() o cambie su estado a CANCELADO.",
                self.reservas.filter(estado=Reserva.Estado.CONFIRMADA),
            )
        return super().delete(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if self.fecha_salida and self.fecha_llegada:
            if self.fecha_llegada <= self.fecha_salida:
                raise ValidationError(
                    {"fecha_llegada": "Debe ser posterior a la fecha de salida."}
                )
        if self.origen and self.destino and self.origen.lower() == self.destino.lower():
            raise ValidationError(
                {"destino": "El destino debe ser distinto del origen."}
            )


# ---------------------------------------------------------------------------
# D. Inventario de asientos (RF-05, RN-03, RN-04, RN-06)
# ---------------------------------------------------------------------------


class Asiento(ModeloBase):
    class Clase(models.TextChoices):
        ECONOMICA = "ECONOMICA", "Económica"
        EJECUTIVA = "EJECUTIVA", "Ejecutiva"
        PRIMERA = "PRIMERA", "Primera"

    class Estado(models.TextChoices):
        DISPONIBLE = "DISPONIBLE", "Disponible"
        BLOQUEADO = "BLOQUEADO", "Bloqueado temporalmente"
        OCUPADO = "OCUPADO", "Ocupado"
        INHABILITADO = "INHABILITADO", "Inhabilitado"

    vuelo = models.ForeignKey(
        Vuelo, verbose_name="vuelo", on_delete=models.CASCADE, related_name="asientos"
    )
    fila = models.CharField("fila", max_length=3)
    numero = models.CharField("número / letra", max_length=3)
    clase = models.CharField(
        "clase", max_length=15, choices=Clase.choices, default=Clase.ECONOMICA
    )
    precio = models.DecimalField(
        "precio",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    estado = models.CharField(
        "estado", max_length=15, choices=Estado.choices, default=Estado.DISPONIBLE
    )
    bloqueado_hasta = models.DateTimeField(
        "bloqueado hasta",
        null=True,
        blank=True,
        help_text="Máximo 10 minutos desde el inicio del bloqueo (RN-04).",
    )
    bloqueado_por = models.ForeignKey(
        "Reserva",
        verbose_name="bloqueado por reserva",
        on_delete=models.SET_NULL,
        related_name="asientos_bloqueados",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "asiento"
        verbose_name = "asiento"
        verbose_name_plural = "asientos"
        ordering = ["vuelo", "fila", "numero"]
        constraints = [
            models.UniqueConstraint(
                fields=["vuelo", "fila", "numero"],
                name="asiento_unico_por_vuelo",
            ),
            models.CheckConstraint(
                condition=Q(precio__gte=Decimal("0.00")),
                name="asiento_precio_no_negativo",
            ),
        ]
        indexes = [models.Index(fields=["vuelo", "estado"])]

    def __str__(self) -> str:
        return f"{self.vuelo.numero_vuelo} {self.fila}{self.numero}"

    @property
    def esta_disponible(self) -> bool:
        if self.estado == self.Estado.DISPONIBLE:
            return True
        if self.estado == self.Estado.BLOQUEADO:
            return bool(self.bloqueado_hasta and self.bloqueado_hasta <= timezone.now())
        return False

    @property
    def bloqueo_vigente(self) -> bool:
        return bool(
            self.estado == self.Estado.BLOQUEADO
            and self.bloqueado_hasta
            and self.bloqueado_hasta > timezone.now()
        )


# ---------------------------------------------------------------------------
# C. Reservas (RF-04, RF-05, RN-01, RN-05, RN-06)
# ---------------------------------------------------------------------------


class Reserva(ModeloBase):
    """
    Reserva / PNR. Una reserva puede tener varios pasajeros mediante
    ReservaPasajero (corrección del diagrama, que solo permitía uno).
    """

    class Estado(models.TextChoices):
        PENDIENTE_PAGO = "PENDIENTE_PAGO", "Pendiente de pago"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        FALLIDA = "FALLIDA", "Fallida"
        EXPIRADA = "EXPIRADA", "Expirada por tiempo"
        CANCELADA = "CANCELADA", "Cancelada"
        REEMBOLSADA = "REEMBOLSADA", "Reembolsada"

    codigo_reserva = models.CharField(
        "código de reserva (PNR)", max_length=8, unique=True, blank=True
    )
    usuario = models.ForeignKey(
        Usuario,
        verbose_name="usuario que reserva",
        on_delete=models.PROTECT,
        related_name="reservas",
    )
    vuelo = models.ForeignKey(
        Vuelo, verbose_name="vuelo", on_delete=models.PROTECT, related_name="reservas"
    )
    promocion = models.ForeignKey(
        "Promocion",
        verbose_name="promoción aplicada",
        on_delete=models.SET_NULL,
        related_name="reservas",
        null=True,
        blank=True,
    )
    estado = models.CharField(
        "estado",
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE_PAGO,
    )
    subtotal = models.DecimalField(
        "subtotal", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    impuestos = models.DecimalField(
        "impuestos", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    descuento = models.DecimalField(
        "descuento", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        "total", max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    fecha_confirmacion = models.DateTimeField("fecha de confirmación", null=True, blank=True)
    fecha_expiracion_bloqueo = models.DateTimeField(
        "expiración del bloqueo", null=True, blank=True
    )
    observaciones = models.TextField("observaciones", blank=True)

    class Meta:
        db_table = "reserva"
        verbose_name = "reserva"
        verbose_name_plural = "reservas"
        ordering = ["-fecha_creacion"]
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal__gte=Decimal("0.00")),
                name="reserva_subtotal_no_negativo",
            ),
            models.CheckConstraint(
                condition=Q(total__gte=Decimal("0.00")),
                name="reserva_total_no_negativo",
            ),
        ]
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["vuelo", "estado"]),
        ]

    def __str__(self) -> str:
        return f"PNR {self.codigo_reserva}"

    def save(self, *args, **kwargs):
        if not self.codigo_reserva:
            for _ in range(20):
                codigo = generar_codigo_pnr()
                if not Reserva.objects.filter(codigo_reserva=codigo).exists():
                    self.codigo_reserva = codigo
                    break
            else:  # pragma: no cover - improbable
                raise ValidationError("No fue posible generar un PNR único.")
        super().save(*args, **kwargs)

    @property
    def bloqueo_vigente(self) -> bool:
        return bool(
            self.fecha_expiracion_bloqueo
            and self.fecha_expiracion_bloqueo > timezone.now()
            and self.estado == self.Estado.PENDIENTE_PAGO
        )

    def recalcular_totales(self, guardar: bool = True) -> Decimal:
        subtotal = sum(
            (rp.tarifa + rp.cargo_equipaje for rp in self.pasajeros.all()),
            Decimal("0.00"),
        )
        self.subtotal = subtotal
        self.total = max(
            Decimal("0.00"), subtotal + self.impuestos - self.descuento
        )
        if guardar:
            self.save(update_fields=["subtotal", "total", "fecha_actualizacion"])
        return self.total

    def liberar_asientos(self) -> int:
        """Devuelve los asientos de esta reserva al inventario (RN-06)."""
        self.pasajeros.filter(asiento__isnull=False).update(
            activo=False, fecha_actualizacion=timezone.now()
        )
        ids = set(self.asientos_bloqueados.values_list("pk", flat=True))
        ids.update(
            self.pasajeros.exclude(asiento__isnull=True).values_list(
                "asiento_id", flat=True
            )
        )
        actualizados = Asiento.objects.filter(
            pk__in=ids, estado=Asiento.Estado.BLOQUEADO
        ).update(
            estado=Asiento.Estado.DISPONIBLE,
            bloqueado_hasta=None,
            bloqueado_por=None,
            fecha_actualizacion=timezone.now(),
        )
        self.fecha_expiracion_bloqueo = None
        self.save(update_fields=["fecha_expiracion_bloqueo", "fecha_actualizacion"])
        return actualizados

    def confirmar(self) -> None:
        self.estado = self.Estado.CONFIRMADA
        self.fecha_confirmacion = timezone.now()
        self.fecha_expiracion_bloqueo = None
        self.save(
            update_fields=[
                "estado",
                "fecha_confirmacion",
                "fecha_expiracion_bloqueo",
                "fecha_actualizacion",
            ]
        )


class ReservaPasajero(ModeloBase):
    """
    Tabla intermedia reserva-pasajero-asiento.
    Sustituye a reserva.id_pasajero y a reserva_asiento del diagrama:
    una reserva puede tener N pasajeros y cada pasajero ocupa un asiento.
    """

    reserva = models.ForeignKey(
        Reserva,
        verbose_name="reserva",
        on_delete=models.CASCADE,
        related_name="pasajeros",
    )
    pasajero = models.ForeignKey(
        Pasajero,
        verbose_name="pasajero",
        on_delete=models.PROTECT,
        related_name="reservas",
    )
    asiento = models.ForeignKey(
        Asiento,
        verbose_name="asiento",
        on_delete=models.SET_NULL,
        related_name="asignaciones",
        null=True,
        blank=True,
    )
    tarifa = models.DecimalField(
        "tarifa",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    equipaje_bodega = models.BooleanField(
        "incluye equipaje de bodega", default=False
    )
    maletas_adicionales = models.PositiveSmallIntegerField(
        "maletas adicionales", default=0
    )
    cargo_equipaje = models.DecimalField(
        "cargo por equipaje",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    activo = models.BooleanField(
        "activo",
        default=True,
        help_text="Se desactiva al cancelar la reserva para liberar el asiento.",
    )

    class Meta:
        db_table = "reserva_pasajero"
        verbose_name = "pasajero de reserva"
        verbose_name_plural = "pasajeros de reserva"
        ordering = ["reserva", "pasajero"]
        constraints = [
            models.UniqueConstraint(
                fields=["reserva", "pasajero"],
                name="reserva_pasajero_unico",
            ),
            models.UniqueConstraint(
                fields=["asiento"],
                condition=Q(activo=True, asiento__isnull=False),
                name="asiento_asignado_una_sola_vez",
            ),
            models.CheckConstraint(
                condition=Q(tarifa__gte=Decimal("0.00")),
                name="reserva_pasajero_tarifa_no_negativa",
            ),
            models.CheckConstraint(
                condition=Q(cargo_equipaje__gte=Decimal("0.00")),
                name="reserva_pasajero_cargo_equipaje_no_negativo",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reserva.codigo_reserva} - {self.pasajero.nombre_completo}"

    def clean(self) -> None:
        super().clean()
        if self.asiento_id and self.reserva_id:
            if self.asiento.vuelo_id != self.reserva.vuelo_id:
                raise ValidationError(
                    {"asiento": "El asiento pertenece a otro vuelo."}
                )

    @property
    def total_linea(self) -> Decimal:
        return self.tarifa + self.cargo_equipaje


# ---------------------------------------------------------------------------
# E. Pagos (RF-06, RN-05, RN-06)
# ---------------------------------------------------------------------------


class Pago(ModeloBase):
    """
    Transacción con la pasarela. Solo se guardan identificadores y la
    respuesta no sensible. Nunca se almacenan PAN, CVV ni datos de banda.
    """

    class Metodo(models.TextChoices):
        WEBPAY = "WEBPAY", "Webpay"
        TARJETA_CREDITO = "TARJETA_CREDITO", "Tarjeta de crédito"
        TARJETA_DEBITO = "TARJETA_DEBITO", "Tarjeta de débito"
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        EXPIRADO = "EXPIRADO", "Expirado"
        REEMBOLSADO = "REEMBOLSADO", "Reembolsado"
        ANULADO = "ANULADO", "Anulado"

    reserva = models.ForeignKey(
        Reserva, verbose_name="reserva", on_delete=models.PROTECT, related_name="pagos"
    )
    monto = models.DecimalField(
        "monto",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    moneda = models.CharField("moneda", max_length=3, default="CLP")
    metodo = models.CharField(
        "método", max_length=20, choices=Metodo.choices, default=Metodo.WEBPAY
    )
    estado = models.CharField(
        "estado", max_length=15, choices=Estado.choices, default=Estado.PENDIENTE
    )
    transaccion_id = models.CharField(
        "identificador de transacción externa",
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )
    fecha_pago = models.DateTimeField("fecha de procesamiento", null=True, blank=True)
    respuesta_pasarela = models.JSONField(
        "respuesta de la pasarela",
        default=dict,
        blank=True,
        help_text="Respuesta no sensible (código, mensaje, estado). No incluir "
        "número de tarjeta, CVV ni datos bancarios.",
    )

    class Meta:
        db_table = "pago"
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["-fecha_creacion"]
        constraints = [
            models.CheckConstraint(
                condition=Q(monto__gte=Decimal("0.00")),
                name="pago_monto_no_negativo",
            ),
            models.UniqueConstraint(
                fields=["reserva"],
                condition=Q(estado="APROBADO"),
                name="pago_aprobado_unico_por_reserva",
            ),
        ]
        indexes = [models.Index(fields=["estado", "fecha_pago"])]

    def __str__(self) -> str:
        return f"Pago {self.pk} - {self.reserva.codigo_reserva} - {self.estado}"

    def marcar_aprobado(self, transaccion_id: str | None = None) -> None:
        self.estado = self.Estado.APROBADO
        self.fecha_pago = timezone.now()
        if transaccion_id:
            self.transaccion_id = transaccion_id
        self.save(
            update_fields=[
                "estado",
                "fecha_pago",
                "transaccion_id",
                "fecha_actualizacion",
            ]
        )

    def marcar_rechazado(self, transaccion_id: str | None = None) -> None:
        self.estado = self.Estado.RECHAZADO
        self.fecha_pago = timezone.now()
        if transaccion_id:
            self.transaccion_id = transaccion_id
        self.save(
            update_fields=[
                "estado",
                "fecha_pago",
                "transaccion_id",
                "fecha_actualizacion",
            ]
        )


# ---------------------------------------------------------------------------
# F. Tickets y check-in (RF-08)
# ---------------------------------------------------------------------------


class Ticket(ModeloBase):
    class Estado(models.TextChoices):
        EMITIDO = "EMITIDO", "Emitido"
        USADO = "USADO", "Usado"
        ANULADO = "ANULADO", "Anulado"

    reserva_pasajero = models.OneToOneField(
        ReservaPasajero,
        verbose_name="pasajero de reserva",
        on_delete=models.CASCADE,
        related_name="ticket",
    )
    codigo_ticket = models.CharField(
        "código de ticket electrónico",
        max_length=13,
        unique=True,
        blank=True,
    )
    estado = models.CharField(
        "estado", max_length=10, choices=Estado.choices, default=Estado.EMITIDO
    )
    fecha_emision = models.DateTimeField("fecha de emisión", auto_now_add=True)

    class Meta:
        db_table = "ticket"
        verbose_name = "ticket electrónico"
        verbose_name_plural = "tickets electrónicos"
        ordering = ["-fecha_emision"]

    def __str__(self) -> str:
        return f"{self.codigo_ticket} - {self.reserva_pasajero.pasajero}"

    def save(self, *args, **kwargs):
        if not self.codigo_ticket:
            for _ in range(20):
                codigo = generar_codigo_ticket()
                if not Ticket.objects.filter(codigo_ticket=codigo).exists():
                    self.codigo_ticket = codigo
                    break
            else:  # pragma: no cover - improbable
                raise ValidationError("No fue posible generar un ticket único.")
        super().save(*args, **kwargs)


class CheckIn(ModeloBase):
    """
    Check-in online. Regla: solo entre 48 y 2 horas antes de la salida.
    El QR se guarda como identificador único (no como imagen binaria).
    """

    class Estado(models.TextChoices):
        REALIZADO = "REALIZADO", "Realizado"
        ANULADO = "ANULADO", "Anulado"

    ticket = models.OneToOneField(
        Ticket,
        verbose_name="ticket",
        on_delete=models.CASCADE,
        related_name="check_in",
    )
    fecha_checkin = models.DateTimeField("fecha de check-in", default=timezone.now)
    codigo_qr = models.CharField(
        "código QR",
        max_length=64,
        unique=True,
        default=generar_codigo_qr,
        editable=False,
    )
    acepta_politicas = models.BooleanField(
        "acepta políticas y mercancías peligrosas", default=False
    )
    estado = models.CharField(
        "estado", max_length=10, choices=Estado.choices, default=Estado.REALIZADO
    )

    class Meta:
        db_table = "check_in"
        verbose_name = "check-in"
        verbose_name_plural = "check-ins"
        ordering = ["-fecha_checkin"]

    def __str__(self) -> str:
        return f"Check-in {self.ticket.codigo_ticket}"

    def clean(self) -> None:
        super().clean()
        if not self.acepta_politicas:
            raise ValidationError(
                {"acepta_politicas": "Debe aceptar las políticas para hacer check-in."}
            )
        if not self.ticket_id:
            return
        vuelo = self.ticket.reserva_pasajero.reserva.vuelo
        apertura = vuelo.fecha_salida - timedelta(hours=48)
        cierre = vuelo.fecha_salida - timedelta(hours=2)
        ahora = timezone.now()
        if not (apertura <= ahora <= cierre):
            raise ValidationError(
                "El check-in solo está disponible entre 48 y 2 horas antes de "
                "la salida del vuelo."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# G. Devoluciones (RF-10)
# ---------------------------------------------------------------------------


class Devolucion(ModeloBase):
    class Tipo(models.TextChoices):
        REEMBOLSO = "REEMBOLSO", "Reembolso"
        CUPON = "CUPON", "Cupón de crédito"

    class Estado(models.TextChoices):
        SOLICITADA = "SOLICITADA", "Solicitada"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        PROCESADA = "PROCESADA", "Procesada"

    reserva = models.ForeignKey(
        Reserva,
        verbose_name="reserva",
        on_delete=models.PROTECT,
        related_name="devoluciones",
    )
    pago = models.ForeignKey(
        Pago,
        verbose_name="pago",
        on_delete=models.PROTECT,
        related_name="devoluciones",
        null=True,
        blank=True,
    )
    usuario_solicita = models.ForeignKey(
        Usuario,
        verbose_name="usuario que solicita",
        on_delete=models.SET_NULL,
        related_name="devoluciones_solicitadas",
        null=True,
        blank=True,
    )
    tipo = models.CharField(
        "tipo", max_length=10, choices=Tipo.choices, default=Tipo.REEMBOLSO
    )
    monto = models.DecimalField(
        "monto",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    motivo = models.TextField("motivo")
    estado = models.CharField(
        "estado",
        max_length=15,
        choices=Estado.choices,
        default=Estado.SOLICITADA,
    )
    comprobante = models.CharField(
        "comprobante", max_length=255, blank=True, help_text="Ruta o URL del comprobante."
    )
    cupon_codigo = models.CharField(
        "código de cupón", max_length=30, unique=True, null=True, blank=True
    )
    fecha_resolucion = models.DateTimeField("fecha de resolución", null=True, blank=True)

    class Meta:
        db_table = "devolucion"
        verbose_name = "devolución"
        verbose_name_plural = "devoluciones"
        ordering = ["-fecha_creacion"]
        constraints = [
            models.CheckConstraint(
                condition=Q(monto__gte=Decimal("0.00")),
                name="devolucion_monto_no_negativo",
            )
        ]
        indexes = [models.Index(fields=["estado", "tipo"])]

    def __str__(self) -> str:
        return f"Devolución {self.pk} - {self.reserva.codigo_reserva}"

    def clean(self) -> None:
        super().clean()
        if self.pago_id and self.monto > self.pago.monto:
            raise ValidationError(
                {"monto": "El monto no puede superar el monto del pago asociado."}
            )


# ---------------------------------------------------------------------------
# H. Notificaciones (RF-09, RN-10)
# ---------------------------------------------------------------------------


class Notificacion(ModeloBase):
    class Tipo(models.TextChoices):
        CONFIRMACION_RESERVA = "CONFIRMACION_RESERVA", "Confirmación de reserva"
        PAGO = "PAGO", "Resultado de pago"
        CAMBIO_VUELO = "CAMBIO_VUELO", "Cambio de vuelo"
        REPROGRAMACION = "REPROGRAMACION", "Reprogramación"
        RETRASO = "RETRASO", "Retraso"
        CANCELACION = "CANCELACION", "Cancelación"
        RECORDATORIO_CHECKIN = "RECORDATORIO_CHECKIN", "Recordatorio de check-in"
        DEVOLUCION = "DEVOLUCION", "Devolución"
        GENERAL = "GENERAL", "General"

    class Canal(models.TextChoices):
        EMAIL = "EMAIL", "Correo electrónico"
        POPUP = "POPUP", "Notificación emergente (pop-up)"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ENVIADA = "ENVIADA", "Enviada"
        FALLIDA = "FALLIDA", "Fallida"
        LEIDA = "LEIDA", "Leída"

    usuario = models.ForeignKey(
        Usuario,
        verbose_name="destinatario",
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )
    reserva = models.ForeignKey(
        Reserva,
        verbose_name="reserva",
        on_delete=models.SET_NULL,
        related_name="notificaciones",
        null=True,
        blank=True,
    )
    vuelo = models.ForeignKey(
        Vuelo,
        verbose_name="vuelo",
        on_delete=models.SET_NULL,
        related_name="notificaciones",
        null=True,
        blank=True,
    )
    tipo = models.CharField("tipo", max_length=25, choices=Tipo.choices)
    canal = models.CharField(
        "canal", max_length=10, choices=Canal.choices, default=Canal.EMAIL
    )
    estado = models.CharField(
        "estado de envío",
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    asunto = models.CharField("asunto", max_length=200)
    mensaje = models.TextField("mensaje")
    fecha_envio = models.DateTimeField("fecha de envío", null=True, blank=True)
    fecha_lectura = models.DateTimeField("fecha de lectura", null=True, blank=True)

    class Meta:
        db_table = "notificacion"
        verbose_name = "notificación"
        verbose_name_plural = "notificaciones"
        ordering = ["-fecha_creacion"]
        indexes = [
            models.Index(fields=["usuario", "estado"]),
            models.Index(fields=["canal", "estado"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} → {self.usuario}"

    def marcar_enviada(self) -> None:
        self.estado = self.Estado.ENVIADA
        self.fecha_envio = timezone.now()
        self.save(update_fields=["estado", "fecha_envio", "fecha_actualizacion"])


# ---------------------------------------------------------------------------
# I. Auditoría (RN-07, RN-08, RN-09)
# ---------------------------------------------------------------------------


class Auditoria(ModeloBase):
    class Accion(models.TextChoices):
        CREAR = "CREAR", "Crear"
        ACTUALIZAR = "ACTUALIZAR", "Actualizar"
        ELIMINAR = "ELIMINAR", "Eliminar"
        INICIAR_SESION = "INICIAR_SESION", "Iniciar sesión"
        CERRAR_SESION = "CERRAR_SESION", "Cerrar sesión"
        RESERVAR = "RESERVAR", "Reservar"
        PAGAR = "PAGAR", "Pagar"
        CHECK_IN = "CHECK_IN", "Check-in"
        REUBICAR = "REUBICAR", "Reubicar pasajero"
        DEVOLVER = "DEVOLVER", "Devolver"
        CANCELAR = "CANCELAR", "Cancelar"

    usuario = models.ForeignKey(
        Usuario,
        verbose_name="usuario responsable",
        on_delete=models.SET_NULL,
        related_name="auditorias",
        null=True,
        blank=True,
    )
    accion = models.CharField("acción", max_length=20, choices=Accion.choices)
    entidad = models.CharField("entidad afectada", max_length=50)
    entidad_id = models.CharField("ID de la entidad", max_length=50, blank=True)
    detalle = models.JSONField("detalle", default=dict, blank=True)
    ip = models.GenericIPAddressField("dirección IP", null=True, blank=True)

    class Meta:
        db_table = "auditoria"
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-fecha_creacion"]
        indexes = [
            models.Index(fields=["entidad", "entidad_id"]),
            models.Index(fields=["usuario", "fecha_creacion"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_accion_display()} {self.entidad}#{self.entidad_id}"


# ---------------------------------------------------------------------------
# J. Promociones
# ---------------------------------------------------------------------------


class Promocion(ModeloBase):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        ACTIVA = "ACTIVA", "Activa"
        INACTIVA = "INACTIVA", "Inactiva"
        VENCIDA = "VENCIDA", "Vencida"

    codigo = models.CharField("código", max_length=30, unique=True)
    titulo = models.CharField("título", max_length=150)
    descripcion = models.TextField("descripción", blank=True)
    descuento_porcentaje = models.DecimalField(
        "descuento (%)",
        max_digits=5,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    fecha_inicio = models.DateTimeField("fecha de inicio")
    fecha_fin = models.DateTimeField("fecha de fin")
    estado = models.CharField(
        "estado", max_length=10, choices=Estado.choices, default=Estado.BORRADOR
    )
    vuelos = models.ManyToManyField(
        Vuelo,
        verbose_name="vuelos asociados",
        through="PromocionVuelo",
        related_name="promociones",
        blank=True,
    )

    class Meta:
        db_table = "promocion"
        verbose_name = "promoción"
        verbose_name_plural = "promociones"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.CheckConstraint(
                condition=Q(fecha_fin__gt=F("fecha_inicio")),
                name="promocion_fin_posterior_a_inicio",
            ),
            models.CheckConstraint(
                condition=Q(descuento_porcentaje__gte=Decimal("0.00"))
                & Q(descuento_porcentaje__lte=Decimal("100.00")),
                name="promocion_descuento_entre_0_y_100",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.codigo} - {self.titulo}"

    @property
    def vigente(self) -> bool:
        ahora = timezone.now()
        return (
            self.estado == self.Estado.ACTIVA
            and self.fecha_inicio <= ahora <= self.fecha_fin
        )

    def clean(self) -> None:
        super().clean()
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin <= self.fecha_inicio:
            raise ValidationError(
                {"fecha_fin": "Debe ser posterior a la fecha de inicio."}
            )


class PromocionVuelo(ModeloBase):
    """Tabla intermedia N:M entre promociones y vuelos."""

    promocion = models.ForeignKey(
        Promocion, verbose_name="promoción", on_delete=models.CASCADE
    )
    vuelo = models.ForeignKey(
        Vuelo, verbose_name="vuelo", on_delete=models.CASCADE
    )

    class Meta:
        db_table = "promocion_vuelo"
        verbose_name = "promoción por vuelo"
        verbose_name_plural = "promociones por vuelo"
        constraints = [
            models.UniqueConstraint(
                fields=["promocion", "vuelo"],
                name="promocion_vuelo_unico",
            )
        ]

    def __str__(self) -> str:
        return f"{self.promocion.codigo} → {self.vuelo.numero_vuelo}"
