# AGENTS.md — Contexto del proyecto SKYANDES

> **Si eres un agente de IA, lee este archivo antes de modificar el proyecto.**
> Este documento resume el objetivo, la arquitectura, el estado actual, las
> reglas de negocio y las restricciones del código. No reemplaza al código:
> cuando haya contradicción, la fuente de verdad es el código y las migraciones.

---

## 1. Resumen del proyecto

SKYANDES es una plataforma web de gestión operacional para una aerolínea. El
alcance actual es un **MVP** con:

- Registro e inicio de sesión con roles (Pasajero, Vendedor, Administrador).
- Búsqueda y gestión de vuelos.
- Reservas con **uno o varios pasajeros**.
- Selección de asientos con **bloqueo temporal de 10 minutos**.
- Pago con Webpay Sandbox (integración pendiente de implementar).
- Emisión de tickets y check-in con código QR.
- Devoluciones (reembolso o cupón).
- Notificaciones por correo electrónico y pop-up.
- Auditoría de acciones.
- Promociones por vuelo.

El proyecto académico divide el trabajo en tres programadores:

| Integrante | Responsabilidad |
|---|---|
| Programador 1 | Frontend de cliente/pasajero: registro, login, buscador, flujo de compra, mapa de asientos, check-in y pase de abordar. |
| Programador 2 | Frontend de vendedor/administrador: consola de mostrador, dashboard, gestión de vuelos y cuentas. |
| Programador 3 | **Backend, base de datos y servicios** (dueño de este repositorio): RBAC, PostgreSQL, API REST de catálogo, inventario/concurrencia, Webpay, notificaciones. |

El usuario de este repositorio es el **Programador 3**. El código aquí es el
backend en Django; el frontend se desarrolla aparte.

---

## 2. Rutas canónicas

| Recurso | Ruta |
|---|---|
| Proyecto Django (raíz) | `C:\Users\faine\OneDrive\Desktop\SkyAndes\WebSkyandes` |
| App principal | `...\WebSkyandes\skyandes\` |
| Configuración | `...\WebSkyandes\proyecto\settings.py` |
| Documento de requisitos | `C:\Users\faine\OneDrive\Desktop\ESCRITORIO\GRUPO 1.pdf` |
| Diagrama de clases original | `C:\Users\faine\OneDrive\Desktop\ESCRITORIO\diagrama de clases.png` |
| Asignación de tareas | `C:\Users\faine\OneDrive\Desktop\proyecto web.pdf` |
| README backend | `README.md` |
| README del contrato frontend | `README_FRONTEND_PROGRAMADOR_3.md` |

> En este equipo Linux el proyecto está en `/home/fainez22/SkyAndes`
> y el repositorio Git es <https://github.com/cfainez/SkyAndes.git>. Las rutas
> de Windows de la tabla son históricas; usa la ruta Linux indicada.

---

## 3. Stack y entorno

| Componente | Versión / estado |
|---|---|
| Python | 3.14.x |
| Django | 6.1.3 |
| Base de datos de desarrollo | PostgreSQL 17 en Docker Compose (`docker-compose.yml`) |
| Base de datos recomendada | PostgreSQL (Azure Database for PostgreSQL Flexible Server) |
| Driver PostgreSQL | `psycopg[binary]` (instalado en `.venv`) |
| Variables de entorno | `python-dotenv` (opcional) |
| Zona horaria | `America/Santiago` |
| Idioma | `es-cl` |
| Moneda | CLP |
| Frontend | No incluido en este repositorio (Next.js/React según arquitectura) |

Dependencias declaradas en `requirements.txt`:

```
Django>=6.1,<7.0
psycopg[binary]>=3.2,<4.0
python-dotenv>=1.0,<2.0
```

Configuración relevante en `proyecto/settings.py`:

- `INSTALLED_APPS` incluye `skyandes.apps.SkyandesConfig`.
- `AUTH_USER_MODEL = "skyandes.Usuario"`.
- `DB_ENGINE=postgresql` activa PostgreSQL; cualquier otro valor usa SQLite.
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` y `DJANGO_ALLOWED_HOSTS` se leen del entorno.
- Correo por consola por defecto (`console.EmailBackend`).

---

## 4. Estructura del proyecto

```
WebSkyandes/
├─ manage.py
├─ requirements.txt
├─ .env.example
├─ README.md
├─ README_FRONTEND_PROGRAMADOR_3.md
├─ AGENTS.md
├─ db.sqlite3
├─ proyecto/
│  ├─ settings.py
│  ├─ urls.py
│  ├─ views.py
│  ├─ asgi.py
│  └─ wsgi.py
├─ templates/
│  └─ inicio.html
└─ skyandes/
   ├─ __init__.py
   ├─ apps.py
   ├─ models.py
   ├─ services.py
   ├─ admin.py
   ├─ tests.py
   ├─ migrations/
   │  ├─ __init__.py
   │  └─ 0001_initial.py
   └─ management/
      ├─ __init__.py
      └─ commands/
         ├─ __init__.py
         └─ liberar_bloqueos.py
```

---

## 5. Estado actual

### 5.1 Implementado

- Modelo de datos completo en `skyandes/models.py`:
  - 16 modelos concretos + `ModeloBase` abstracto.
  - Restricciones `CheckConstraint`, `UniqueConstraint` e índices.
  - Borrado lógico de vuelos.
  - Generación automática de PNR, código de ticket y código QR.
- Servicios de dominio transaccionales en `skyandes/services.py`.
- Panel de administración en `skyandes/admin.py`.
- 26 pruebas automatizadas en `skyandes/tests.py`.
- Migración inicial `skyandes/migrations/0001_initial.py`.
- Comando `python manage.py liberar_bloqueos`.
- Configuración de PostgreSQL/SQLite, correo y variables de entorno.
- Documentación:
  - `README.md`: instalación, modelo, reglas y servicios.
  - `README_FRONTEND_PROGRAMADOR_3.md`: contrato funcional de frontend.

### 5.2 Pendiente / no implementado

| Pendiente | Detalle |
|---|---|
| API REST | No hay DRF, serializers, viewsets ni rutas `/api/`. Los servicios existen, pero no están expuestos. |
| Webpay real | `procesar_pago()` registra el resultado; no existe adaptador ni llamada real a Webpay Sandbox. |
| Redis/Docker | El PDF menciona Redis vía Docker; el código actual usa bloqueo de filas en base de datos, sin Redis. |
| Envío real de correos | Se crean registros `Notificacion`, pero no se llama a `send_mail` ni a un worker. |
| Frontend | Vive en otro repositorio/proyecto; aquí solo hay una plantilla `inicio.html`. |
| Tareas programadas | Existe el comando, pero no está programado en cron/Programador de tareas. |
| Pruebas PostgreSQL | Las 26 pruebas se ejecutaron en SQLite. No hay pruebas de concurrencia real. |

---

## 6. Modelo de datos

### 6.1 Entidades y tablas

| Modelo | Tabla | Propósito |
|---|---|---|
| `Rol` | `rol` | Rol de acceso y permisos Django (RBAC). |
| `Usuario` | `usuario` | Usuario del sistema; extiende `AbstractUser`. |
| `Pasajero` | `pasajero` | Persona que viaja; puede tener o no cuenta de usuario. |
| `Aerolinea` | `aerolinea` | Aerolínea operadora. |
| `Vuelo` | `vuelo` | Itinerario, fechas, precio base y estado. |
| `Asiento` | `asiento` | Inventario por vuelo, estado y bloqueo temporal. |
| `Reserva` | `reserva` | PNR, usuario, vuelo, totales y estado. |
| `ReservaPasajero` | `reserva_pasajero` | Pasajero de una reserva + asiento + tarifa + equipaje. |
| `Pago` | `pago` | Transacción con pasarela; sin datos sensibles de tarjeta. |
| `Ticket` | `ticket` | Ticket electrónico por pasajero de reserva. |
| `CheckIn` | `check_in` | Check-in con QR y aceptación de políticas. |
| `Devolucion` | `devolucion` | Reembolso o cupón. |
| `Notificacion` | `notificacion` | Mensajes por canal `EMAIL` o `POPUP`. |
| `Auditoria` | `auditoria` | Registro de acciones del sistema. |
| `Promocion` | `promocion` | Descuento porcentual con vigencia. |
| `PromocionVuelo` | `promocion_vuelo` | Relación N:M entre promociones y vuelos. |
| `ModeloBase` | — | Abstracto: `fecha_creacion`, `fecha_actualizacion`. |

### 6.2 Relaciones clave

```
Rol 1 ── N Usuario 1 ── 0..1 Pasajero
Usuario 1 ── N Reserva N ── 1 Vuelo N ── 1 Aerolinea
Reserva 1 ── N ReservaPasajero N ── 1 Pasajero
ReservaPasajero N ── 0..1 Asiento N ── 1 Vuelo
Reserva 1 ── N Pago
ReservaPasajero 1 ── 1 Ticket 1 ── 0..1 CheckIn
Reserva 1 ── N Devolucion
Reserva 1 ── N Notificacion
Vuelo N ── N Promocion (through PromocionVuelo)
```

### 6.3 Decisiones de diseño importantes

- **`ReservaPasajero` reemplaza** al `reserva.id_pasajero` y a
  `reserva_asiento` del diagrama original. Una reserva admite N pasajeros y
  cada uno ocupa como máximo un asiento activo.
- **`Pasajero` es independiente de `Usuario`.** Un pasajero puede comprar en
  mostrador sin cuenta; si tiene cuenta, se enlaza 1:1.
- **Un solo modelo `Usuario`** cubre pasajeros, vendedores y administradores.
  La diferencia se resuelve con `Rol` + permisos, sin tablas duplicadas.
- **Borrado lógico de vuelos:** `Vuelo.activo`; `delete()` lanza
  `ProtectedError` si hay reservas confirmadas.
- **Asientos:** `estado`, `bloqueado_hasta`, `bloqueado_por` implementan
  RN-03/RN-04.
- **Pagos:** se guarda `transaccion_id` y `respuesta_pasarela` no sensible.
  Nunca PAN, CVV ni datos de banda.
- **Restricciones parciales:** un asiento asignado una sola vez
  (`activo=True`) y un solo pago aprobado por reserva.

---

## 7. Reglas de negocio

| Regla | Implementación |
|---|---|
| RN-01 Pasajero identificado | `Pasajero` exige RUN o pasaporte (`clean()` + `CheckConstraint`). |
| RN-02 Identificadores únicos | `rut`, `pasaporte`, `email` únicos en `Pasajero`; `email` único en `Usuario`. |
| RN-03 Asiento disponible | Validación en `bloquear_asientos()` y `asignar_asiento()`. |
| RN-04 Bloqueo máximo 10 min | `MAX_BLOQUEO_MINUTOS = 10`; `bloquear_asientos()` rechaza más. |
| RN-05 Pago aprobado confirma | `procesar_pago()` valida monto y confirma atómicamente. |
| RN-06 Pago rechazado libera | `procesar_pago()` marca `FALLIDA` y libera asientos. |
| RN-07 Vuelo con reservas no se elimina | `Vuelo.delete()` lanza `ProtectedError`. |
| RN-08 Cambio de vuelo notifica | `cambiar_estado_vuelo()` crea notificaciones `EMAIL` y `POPUP`. |
| RN-09 Acciones auditadas | `registrar_auditoria()` en reserva, pago, check-in, devolución y vuelo. |
| RN-10 Notificación al pasajero | Canales `EMAIL` y `POPUP`; WhatsApp fuera del MVP. |
| Check-in 48 h–2 h | `CheckIn.clean()` valida la ventana antes de guardar. |

Estados principales:

- `Reserva`: `PENDIENTE_PAGO`, `CONFIRMADA`, `FALLIDA`, `EXPIRADA`, `CANCELADA`, `REEMBOLSADA`.
- `Pago`: `PENDIENTE`, `APROBADO`, `RECHAZADO`, `EXPIRADO`, `REEMBOLSADO`, `ANULADO`.
- `Vuelo`: `PROGRAMADO`, `RETRASADO`, `REPROGRAMADO`, `EN_VUELO`, `ATERRIZADO`, `CANCELADO`.
- `Asiento`: `DISPONIBLE`, `BLOQUEADO`, `OCUPADO`, `INHABILITADO`.

---

## 8. Servicios de dominio (`skyandes/services.py`)

Todas las operaciones críticas usan `@transaction.atomic` y
`select_for_update()`.

| Función | Responsabilidad |
|---|---|
| `crear_reserva(...)` | Crea reserva, líneas de pasajeros, totales y bloqueo inicial. |
| `bloquear_asientos(reserva_id, asiento_ids, minutos=10)` | Bloquea asientos validando vuelo, estado y bloqueos ajenos. |
| `asignar_asiento(reserva_pasajero_id, asiento_id)` | Cambia asiento y ajusta tarifa. |
| `aplicar_promocion(reserva_id, promocion_id)` | Valida vigencia y recalcula descuento/total. |
| `procesar_pago(...)` | Aprueba/rechaza, confirma o libera, emite tickets y notifica. |
| `liberar_bloqueos_expirados()` | Expira reservas y libera asientos vencidos. |
| `registrar_check_in(...)` | Valida plazo, crea check-in y genera QR. |
| `cambiar_estado_vuelo(...)` | Cambia estado, notifica y audita. |
| `solicitar_devolucion(...)` | Crea reembolso/cupón, notifica y audita. |
| `registrar_auditoria(...)` | Inserta un registro de auditoría. |
| `crear_notificacion(...)` | Inserta una notificación. |

Excepciones de dominio:

- `SkyAndesError`
- `AsientoNoDisponible`
- `ReservaNoModificable`
- `ReservaExpirada`
- `MontoIncorrecto`
- `CheckInFueraDePlazo`

---

## 9. Convenciones e invariantes

### 9.1 Código

- Idioma del dominio y los comentarios: **español**.
- Nombres de modelos y tablas en singular (`Vuelo`, `vuelo`).
- Importes siempre con `Decimal`, nunca `float`.
- Fechas con `django.utils.timezone`; no usar `datetime.now()` naive.
- Operaciones multi-tabla dentro de `transaction.atomic()`.
- Filas compartidas (reserva, asiento, vuelo) con `select_for_update()`.
- Validar en `clean()`/`full_clean()` lo que no pueda expresarse como constraint.
- Mantener las migraciones; no editar `0001_initial.py` a mano salvo que sea
  imprescindible y esté justificado.

### 9.2 Seguridad y datos

- **Nunca** almacenar número de tarjeta, CVV, fecha de expiración ni banda.
- **Nunca** confiar en montos, asientos ni roles enviados por el cliente.
- El backend valida permisos; el frontend solo oculta opciones.
- No incluir secretos reales en `.env.example`, README ni código.
- No registrar tokens, contraseñas ni datos personales en logs.

### 9.3 Reglas que no se deben romper

- Una reserva debe tener al menos un pasajero.
- Un asiento no puede pertenecer a dos asignaciones activas.
- Un asiento bloqueado por otra reserva no puede tomarse hasta que expire.
- El bloqueo nunca supera 10 minutos.
- Un pago aprobado debe coincidir con el total de la reserva.
- Una reserva confirmada no se puede volver a pagar.
- Un vuelo con reservas confirmadas no se elimina físicamente.
- El check-in solo se permite entre 48 y 2 horas antes de la salida.
- No se duplican check-in para el mismo ticket.

---

## 10. Comandos de trabajo

Ejecutar desde `/home/fainez22/SkyAndes`.

```bash
# Levantar PostgreSQL local (Docker)
docker compose up -d db

# Verificación del proyecto
python manage.py check

# Migraciones
python manage.py makemigrations skyandes
python manage.py migrate

# Pruebas (26 tests)
python manage.py test skyandes -v 2

# Liberar bloqueos vencidos
python manage.py liberar_bloqueos

# Servidor de desarrollo
python manage.py runserver

# Crear administrador
python manage.py createsuperuser
```

Para PostgreSQL, definir en `.env`:

```dotenv
DB_ENGINE=postgresql
DB_NAME=skyandes
DB_USER=skyandes
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432
```

---

## 11. Pruebas y limitaciones conocidas

- Última ejecución: **26 pruebas OK** con `python manage.py test skyandes`.
- Base usada en pruebas: **SQLite**.
- `select_for_update()` es un **no-op en SQLite**. La garantía real de
  concurrencia requiere PostgreSQL.
- **No** se ejecutaron pruebas de concurrencia real ni pruebas sobre PostgreSQL.
- No afirmar que Webpay, Redis o el envío de correos están implementados: no
  lo están.
- No afirmar que existe una API REST: no existe todavía.

---

## 12. Documentación relacionada

| Archivo | Contenido |
|---|---|
| `README.md` | Instalación, comparación con el diagrama, modelo, reglas y servicios. |
| `docs/BASE_DE_DATOS_LOCAL.md` | Guía de PostgreSQL local con Docker, flujo de equipo y paridad con Azure. |
| `README_FRONTEND_PROGRAMADOR_3.md` | Contrato funcional de frontend: autenticación, catálogo, asientos, pagos, notificaciones y check-in. |
| `AGENTS.md` | Este documento de contexto para agentes de IA. |

El contrato de frontend propone rutas `/api/v1/...`. Son una **propuesta de
interfaz**, no endpoints implementados. Si se implementa la API, actualizar el
documento y mantener la semántica de estados, errores e idempotencia.

---

## 13. Próximos pasos sugeridos

Orden recomendado para completar la parte del Programador 3:

1. **Capa REST**: instalar Django REST Framework, crear serializers y viewsets
   para autenticación, vuelos, asientos, reservas, pagos, notificaciones y
   check-in.
2. **Autenticación**: implementar login/logout/me y permisos por rol sobre los
   endpoints.
3. **Catálogo**: exponer listado, creación, edición, borrado lógico y
   reactivación de vuelos.
4. **Inventario**: exponer mapa de asientos y bloqueo; agregar manejo explícito
   de conflicto `409`.
5. **Webpay**: implementar el patrón Adapter y el flujo de confirmación
   idempotente.
6. **Notificaciones**: conectar el envío real de correos y, si aplica,
   SSE/WebSocket para pop-ups.
7. **PostgreSQL**: ejecutar migraciones y pruebas en PostgreSQL; agregar
   pruebas de concurrencia.
8. **Programar** `liberar_bloqueos` cada minuto.
9. **Docker/Redis** (si el alcance lo exige): definir la infraestructura y
   decidir si el bloqueo se mantiene en PostgreSQL o se complementa con Redis.

---

## 14. Reglas para agentes de IA

Antes de responder o modificar:

1. **Leer** `AGENTS.md`, `README.md` y el archivo que se va a tocar.
2. **No inventar** endpoints, modelos, dependencias ni resultados de pruebas.
3. **No ejecutar** migraciones destructivas ni borrar `db.sqlite3` sin pedir
   confirmación.
4. **No cambiar** el modelo de usuario ni las relaciones principales sin
   justificarlo y actualizar migraciones/documentación.
5. **No eliminar** restricciones de integridad, auditoría o validaciones de
   seguridad.
6. **No introducir** datos sensibles de tarjetas, secretos reales ni
   credenciales en el código.
7. **Mantener** el español en documentación, mensajes de negocio y comentarios.
8. **Ejecutar** `python manage.py check` y `python manage.py test skyandes`
   después de cambios relevantes.
9. **Reportar** con honestidad qué se ejecutó y en qué base de datos.
10. Si un cambio afecta el contrato frontend, **actualizar**
    `README_FRONTEND_PROGRAMADOR_3.md`.

### Checklist antes de terminar una tarea

- [ ] `python manage.py check` sin errores.
- [ ] `python manage.py makemigrations --check --dry-run` sin cambios pendientes.
- [ ] `python manage.py test skyandes` en verde.
- [ ] Documentación actualizada si cambió el comportamiento.
- [ ] Sin secretos ni datos sensibles en el diff.
- [ ] Respuesta final en español, indicando archivos y verificaciones realizadas.
