# SKYANDES — Modelo de datos y reglas de negocio (Django)

Implementación del modelo de datos del MVP de SKYANDES, corregido y ampliado a
partir del diagrama de clases y del documento `GRUPO 1.pdf`.

- App Django: `skyandes`
- Modelo de usuario personalizado: `AUTH_USER_MODEL = "skyandes.Usuario"`
- Base de datos recomendada: PostgreSQL (SQLite disponible para desarrollo/pruebas)
- Python 3.14 / Django 6.1.3

---

## 1. Instalación

> **Recomendado para el equipo:** PostgreSQL 17 en Docker Compose.
> La guía paso a paso (instalación de Docker, contenedor, migraciones,
> pruebas y despliegue en Azure) está en
> [`docs/BASE_DE_DATOS_LOCAL.md`](docs/BASE_DE_DATOS_LOCAL.md).
> SQLite queda solo como respaldo si no se crea `.env`.

```powershell
cd C:\Users\faine\OneDrive\Desktop\SkyAndes\WebSkyandes

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt

# Opcional: variables de entorno
Copy-Item .env.example .env
```

Si no existe `.env`, el proyecto funciona con SQLite y correo por consola.

### Migraciones y pruebas

```powershell
python manage.py check
python manage.py makemigrations skyandes
python manage.py migrate
python manage.py test skyandes -v 2
```

### Base de datos PostgreSQL

Para desarrollo local se recomienda el contenedor de
[`docker-compose.yml`](docker-compose.yml):

```bash
docker compose up -d db
```

En `.env`:

```dotenv
DB_ENGINE=postgresql
DB_NAME=skyandes
DB_USER=skyandes
DB_PASSWORD=...
DB_HOST=127.0.0.1
DB_PORT=5432
DB_SSLMODE=disable
```

En Azure Database for PostgreSQL usar `DB_SSLMODE=require` y el host del
servidor flexible.

Crear la base y el usuario (ejemplo):

```sql
CREATE USER skyandes WITH PASSWORD '...';
CREATE DATABASE skyandes OWNER skyandes;
```

Luego `python manage.py migrate`.

### Liberar bloqueos vencidos

El bloqueo de asientos dura como máximo 10 minutos (RN-04). Para liberar los
asientos vencidos y expirar las reservas pendientes:

```powershell
python manage.py liberar_bloqueos
```

Puede programarse cada minuto con el Programador de tareas de Windows o `cron`.

### Administración

```powershell
python manage.py createsuperuser
python manage.py runserver
```

Panel: <http://127.0.0.1:8000/admin/>

---

## 2. Comparación con el diagrama de clases original

| Nº | Diagrama original | Problema detectado | Solución implementada |
|----|-------------------|--------------------|------------------------|
| 1 | `reserva.id_pasajero` (un pasajero por reserva) | Impide reservas familiares/grupales; contradice RF-04 | `ReservaPasajero` (N:M) con reserva + pasajero + asiento + tarifa + equipaje |
| 2 | `reserva_asiento` separada de la reserva | Duplicaba la relación y no garantizaba un asiento por pasajero | Se integra en `ReservaPasajero.asiento`; restricción única de asiento activo |
| 3 | `asiento` sin campos de bloqueo | No permite cumplir RN-03/RN-04 (bloqueo 10 min) | Campos `estado`, `bloqueado_hasta`, `bloqueado_por` + servicio transaccional |
| 4 | `check_in` sin QR ni política | No cumple RF-08 (pase de abordar con QR) | `codigo_qr` único, `acepta_politicas`, validación 48 h–2 h |
| 5 | `pago` con atributos mínimos | No registra estado, moneda, transacción ni respuesta de pasarela | `Pago` con estado, moneda, método, `transaccion_id`, `respuesta_pasarela` |
| 6 | `devolucion` incompleta | No distingue reembolso de cupón ni estados | `Devolucion` con tipo, estado, cupón y comprobante |
| 7 | `notificacion` sin canal ni estado | No cumple RF-09 (correo + pop-up) | `Notificacion` con canal `EMAIL`/`POPUP`, estado y fechas |
| 8 | `auditoria` sin acciones definidas | No cubre RN-07/RN-08/RN-09 | `Auditoria` con catálogo de acciones, entidad, detalle JSON e IP |
| 9 | `usuario` y roles sin RBAC | El rol no tenía permisos asociados | `Usuario(AbstractUser)` + `Rol` + `auth.Permission` (M2M) |
| 10 | Sin borrado lógico ni protección de vuelos | RN-07 exige no eliminar vuelos con reservas confirmadas | `Vuelo.activo`, `delete()` con `ProtectedError`, `desactivar()` |
| 11 | Sin control de concurrencia | Dos usuarios podían tomar el mismo asiento | `transaction.atomic()` + `select_for_update()` en los servicios |
| 12 | Sin promociones por vuelo | Descuentos sin alcance definido | `Promocion` + `PromocionVuelo` (N:M) |

### Entidades implementadas (16)

Autenticación: `Rol`, `Usuario`, `Pasajero`.

Operación: `Aerolinea`, `Vuelo`, `Asiento`, `Reserva`, `ReservaPasajero`.

Venta: `Pago`, `Promocion`, `PromocionVuelo`, `Devolucion`.

Postventa: `Ticket`, `CheckIn`, `Notificacion`, `Auditoria`.

Base abstracta: `ModeloBase` (fechas de creación y actualización).

### Relaciones principales

```
Rol 1 ── N Usuario 1 ── 0..1 Pasajero
Usuario 1 ── N Reserva N ── 1 Vuelo N ── 1 Aerolinea
Reserva 1 ── N ReservaPasajero N ── 1 Pasajero
ReservaPasajero N ── 0..1 Asiento N ── 1 Vuelo
Reserva 1 ── N Pago
ReservaPasajero 1 ── 1 Ticket 1 ── 0..1 CheckIn
Reserva 1 ── N Devolucion / Notificacion
Vuelo N ── N Promocion (through PromocionVuelo)
```

---

## 3. Reglas de negocio cubiertas

| Regla | Implementación |
|-------|----------------|
| RN-01 Pasajero identificado | `Pasajero` exige RUN o pasaporte (validación + CheckConstraint) |
| RN-02 Identificadores únicos | `rut`, `pasaporte`, `email` únicos en `Pasajero`; `email` único en `Usuario` |
| RN-03 Asiento disponible | `Asiento.esta_disponible`; el servicio rechaza asientos ocupados o inhabilitados |
| RN-04 Bloqueo máximo 10 min | `MAX_BLOQUEO_MINUTOS`, `bloquear_asientos()` y comando `liberar_bloqueos` |
| RN-05 Pago aprobado confirma reserva | `procesar_pago()` valida monto y confirma de forma atómica |
| RN-06 Pago rechazado libera asientos | `procesar_pago()` marca `FALLIDA` y libera inventario |
| RN-07 Vuelo con reservas no se elimina | `Vuelo.delete()` lanza `ProtectedError`; `desactivar()` para borrado lógico |
| RN-08 Cambios de vuelo se notifican | `cambiar_estado_vuelo()` genera notificaciones y auditoría |
| RN-09 Acciones auditadas | `registrar_auditoria()` en reserva, pago, check-in, devolución y vuelos |
| RN-10 Notificación al pasajero | Canales `EMAIL` y `POPUP` (WhatsApp fuera del MVP) |
| Check-in 48 h–2 h | `CheckIn.clean()` rechaza fuera de ventana |
| Datos sensibles | No se almacenan PAN, CVV ni datos de banda; solo respuesta no sensible |

---

## 4. Servicios de dominio (`skyandes/services.py`)

| Función | Responsabilidad |
|---------|-----------------|
| `crear_reserva` | Reserva con N pasajeros, tarifas, bloqueo y auditoría |
| `bloquear_asientos` | Bloqueo transaccional de hasta 10 minutos |
| `asignar_asiento` | Cambia el asiento de un pasajero y ajusta tarifa |
| `aplicar_promocion` | Valida vigencia y recalcula descuento/total |
| `procesar_pago` | Aprueba/rechaza, confirma o libera y emite tickets |
| `liberar_bloqueos_expirados` | Tarea periódica de limpieza |
| `registrar_check_in` | Valida plazo y genera el QR |
| `cambiar_estado_vuelo` | Notifica a reservas confirmadas y audita |
| `solicitar_devolucion` | Reembolso o cupón con comprobante y notificación |

Los importes usan `Decimal`; nunca `float`.

---

## 5. Notas de validación

- `python manage.py check`: sin errores.
- `python manage.py test skyandes`: **26 pruebas OK** (SQLite).
- Las pruebas se ejecutaron en **SQLite**, no en PostgreSQL.
- `select_for_update()` no bloquea filas en SQLite; la garantía real de
  concurrencia requiere PostgreSQL. No se ejecutaron pruebas de concurrencia
  reales sobre PostgreSQL.
- Antes de ejecutar por primera vez, `makemigrations` ya está aplicado en
  `skyandes/migrations/0001_initial.py`.

---

## 6. Estructura

```
WebSkyandes/
├─ manage.py
├─ requirements.txt
├─ .env.example
├─ README_FRONTEND_PROGRAMADOR_3.md
├─ AGENTS.md
├─ proyecto/
│  ├─ settings.py
│  ├─ urls.py
│  └─ views.py
└─ skyandes/
   ├─ models.py
   ├─ services.py
   ├─ admin.py
   ├─ tests.py
   ├─ migrations/0001_initial.py
   └─ management/commands/liberar_bloqueos.py
```
