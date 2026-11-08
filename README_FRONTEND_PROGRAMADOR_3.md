# README — Funciones de frontend requeridas por los servicios del Programador 3

## 1. Contexto y alcance

Este documento describe las **funciones de frontend que deben implementarse para consumir e integrar los servicios del Programador 3** (backend, base de datos, autenticación, inventario, pagos y notificaciones) del proyecto SKYANDES.

El Programador 3 es responsable de:

- Base de datos PostgreSQL y autenticación con RBAC.
- API REST del catálogo de vuelos con borrado lógico.
- Control de inventario y concurrencia con bloqueo de asientos por 10 minutos.
- Integración con Webpay Sandbox mediante patrón Adapter e idempotencia.
- Motor de notificaciones por correo y pop-ups.

Este README **no implementa frontend**: define el contrato funcional que el equipo de frontend (Programador 1 y Programador 2) debe construir para que las funcionalidades del Programador 3 sean utilizables desde la interfaz.

> Supuestos de trabajo:
> - Frontend web en **Next.js/React** (según la arquitectura del proyecto).
> - Comunicación mediante **API REST JSON**.
> - Backend en **Django**, base de datos **PostgreSQL**.
> - Zona horaria **America/Santiago** y moneda **CLP**.
>
> Si el equipo usa Django Templates en lugar de Next.js, los mismos contratos, estados y validaciones siguen aplicando.

---

## 2. Convenciones de integración

### 2.1 Base de la API

```
/api/v1/
```

### 2.2 Formato de datos

- JSON en `camelCase` o `snake_case` (definir uno y mantenerlo en todo el proyecto).
- Fechas en ISO 8601 con zona horaria: `2026-11-07T18:30:00-03:00`.
- Montos como string decimal para evitar errores de punto flotante: `"125000.00"`.
- Identificadores numéricos o UUID según el modelo.
- Paginación estándar:

```json
{
  "count": 120,
  "next": "/api/v1/vuelos/?page=2",
  "previous": null,
  "results": []
}
```

### 2.3 Autenticación

Recomendación para frontend web: **cookie de sesión HttpOnly + CSRF**.
Si el frontend está en otro dominio, usar **JWT** con access token corto y refresh token.

Reglas mínimas:

- Toda petición protegida debe enviar credenciales.
- El frontend **no decide permisos**: solo oculta o muestra opciones según el rol recibido; el backend siempre valida.
- Ante `401`, limpiar sesión y redirigir al login.
- Ante `403`, mostrar pantalla o mensaje de acceso denegado sin cerrar sesión.

### 2.4 Formato de error acordado

```json
{
  "code": "ASIENTO_BLOQUEADO",
  "message": "El asiento 12A está bloqueado por otra reserva.",
  "details": {
    "asientoId": 45
  }
}
```

### 2.5 Idempotencia en pagos

Cada intento de pago debe enviar:

```
Idempotency-Key: <uuid-generado-una-sola-vez-por-intento>
```

Si el usuario reintenta la misma operación, se reutiliza la misma clave hasta obtener una respuesta definitiva.

---

## 3. Matriz resumen de funciones

| Módulo | Función frontend | Rol principal | Prioridad |
|---|---|---|---|
| Autenticación | Login, logout, sesión actual, guard por rol | Todos | Alta |
| Catálogo | Listar, crear, editar, desactivar y reactivar vuelos | Administrador | Alta |
| Inventario | Mapa de asientos, bloqueo 10 min, cuenta regresiva | Pasajero / Vendedor | Crítica |
| Pagos | Iniciar pago, redirigir a Webpay, confirmar resultado | Pasajero / Vendedor | Crítica |
| Notificaciones | Campana, pop-ups, centro de notificaciones, alertas de vuelo | Todos | Media/Alta |
| Check-in | Mostrar ventana 48 h–2 h, aceptar políticas, renderizar QR | Pasajero | Alta |

---

## 4. Autenticación y RBAC

### 4.1 Funciones del cliente API

```ts
type Rol = "PASAJERO" | "VENDEDOR" | "ADMINISTRADOR";

interface UsuarioSesion {
  id: number;
  username: string;
  email: string;
  nombre: string;
  rol: Rol;
  estado: "ACTIVO" | "INACTIVO" | "BLOQUEADO";
  permisos: string[];
}

login(credenciales: { username: string; password: string }): Promise<UsuarioSesion>;

logout(): Promise<void>;

obtenerSesion(): Promise<UsuarioSesion>;

cambiarPassword(datos: {
  passwordActual: string;
  passwordNueva: string;
}): Promise<void>;
```

### 4.2 Endpoints propuestos

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/auth/login/` | Inicia sesión |
| `POST` | `/api/v1/auth/logout/` | Cierra sesión |
| `GET` | `/api/v1/auth/me/` | Devuelve usuario, rol y permisos |
| `POST` | `/api/v1/auth/password/` | Cambio de contraseña |
| `POST` | `/api/v1/auth/refresh/` | Renueva token (solo si se usa JWT) |

### 4.3 Componentes y funciones de UI

- `LoginPage`: formulario con usuario/correo y contraseña, mostrar/ocultar contraseña, estado de carga y error.
- `useSession()`: hook que obtiene y cachea la sesión actual.
- `RequireAuth`: redirige al login si no hay sesión.
- `RequireRole({ roles })`: bloquea rutas no autorizadas y muestra `403`.
- `SessionExpiredModal`: avisa cuando la sesión expiró.
- `LogoutButton`: cierra sesión y limpia caché local.
- Menú lateral filtrado por rol:
  - Pasajero: buscar vuelos, mis reservas, check-in.
  - Vendedor: consola de mostrador, reservas, devoluciones.
  - Administrador: catálogo de vuelos, cuentas, métricas, auditoría.

### 4.4 Criterios de aceptación

- Un usuario `INACTIVO` o `BLOQUEADO` no puede iniciar sesión y recibe un mensaje claro.
- Un `PASAJERO` no ve ni puede abrir rutas de administración.
- Si el backend responde `401`, el frontend limpia la sesión y redirige al login.
- Si responde `403`, muestra acceso denegado y no elimina la sesión.
- La contraseña nunca se guarda en `localStorage`.

---

## 5. Gestión del catálogo de vuelos

### 5.1 Funciones del cliente API

```ts
interface FiltrosVuelo {
  origen?: string;
  destino?: string;
  fechaDesde?: string;
  fechaHasta?: string;
  aerolinea?: number;
  estado?: string;
  activo?: boolean;
  page?: number;
  pageSize?: number;
}

listarVuelos(filtros: FiltrosVuelo): Promise<Pagina<Vuelo>>;

obtenerVuelo(id: number): Promise<Vuelo>;

crearVuelo(dto: VueloDTO): Promise<Vuelo>;

actualizarVuelo(id: number, dto: Partial<VueloDTO>): Promise<Vuelo>;

desactivarVuelo(id: number): Promise<Vuelo>;   // borrado lógico

reactivarVuelo(id: number): Promise<Vuelo>;
```

`VueloDTO` debe incluir como mínimo:

```ts
interface VueloDTO {
  aerolineaId: number;
  numeroVuelo: string;
  origen: string;
  destino: string;
  fechaSalida: string;   // ISO 8601
  fechaLlegada: string;  // ISO 8601
  precioBase: string;    // "50000.00"
  estado: "PROGRAMADO" | "RETRASADO" | "REPROGRAMADO" |
          "EN_VUELO" | "ATERRIZADO" | "CANCELADO";
  observaciones?: string;
}
```

### 5.2 Endpoints propuestos

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/vuelos/` | Lista con filtros y paginación |
| `POST` | `/api/v1/vuelos/` | Crea vuelo (solo admin) |
| `GET` | `/api/v1/vuelos/{id}/` | Detalle |
| `PATCH` | `/api/v1/vuelos/{id}/` | Edición parcial |
| `DELETE` | `/api/v1/vuelos/{id}/` | Borrado lógico (`activo=false`) |
| `POST` | `/api/v1/vuelos/{id}/reactivar/` | Reactiva un vuelo |

### 5.3 Pantallas y componentes

- `VuelosTable`: columnas de número, aerolínea, origen, destino, salida, llegada, precio, estado y activo.
- `VueloFiltros`: búsqueda por origen, destino, fechas, aerolínea y estado.
- `VueloForm`: crear/editar con validación en cliente y errores del servidor por campo.
- `ConfirmarDesactivacionModal`: explica que el vuelo dejará de mostrarse, sin borrar reservas.
- `EstadoVueloBadge`: colores distintos por estado.
- Botón **Reactivar** visible solo para vuelos inactivos.

### 5.4 Reglas de UI

- `fecha_llegada` debe ser posterior a `fecha_salida`.
- `origen` y `destino` no pueden ser iguales.
- `precio_base` no puede ser negativo.
- El borrado es **lógico**: tras desactivar, el vuelo sigue existiendo y puede reactivarse.
- Si el backend rechaza una operación por reservas confirmadas, mostrar el mensaje y ofrecer **cancelar/desactivar** en lugar de eliminar.

### 5.5 Criterios de aceptación

- El listado responde a filtros y paginación sin recargar la página.
- Los formularios muestran errores de validación del backend junto al campo correspondiente.
- Desactivar un vuelo lo marca como inactivo y lo oculta del buscador público.
- Un vuelo inactivo no puede seleccionarse para una reserva nueva.
- Solo el rol `ADMINISTRADOR` accede a estas funciones.

---

## 6. Control de inventario y concurrencia

Esta es la funcionalidad **crítica** del Programador 3. El frontend debe reflejar fielmente el estado del servidor y nunca asumir que un asiento está disponible solo porque la UI lo muestra.

### 6.1 Funciones del cliente API

```ts
interface Asiento {
  id: number;
  fila: string;
  numero: string;
  clase: "ECONOMICA" | "EJECUTIVA" | "PRIMERA";
  precio: string;
  estado: "DISPONIBLE" | "BLOQUEADO" | "OCUPADO" | "INHABILITADO";
  bloqueadoHasta: string | null;
}

obtenerMapaAsientos(vueloId: number): Promise<{
  vueloId: number;
  actualizadoEn: string;
  asientos: Asiento[];
}>;

crearReserva(dto: {
  vueloId: number;
  pasajeros: Array<{
    pasajeroId: number;
    asientoId?: number;
    equipajeBodega?: boolean;
    maletasAdicionales?: number;
  }>;
  promocionCodigo?: string;
}): Promise<Reserva>;

bloquearAsientos(reservaId: number, asientoIds: number[]): Promise<{
  reservaId: number;
  bloqueadoHasta: string;
  asientos: Asiento[];
}>;

liberarBloqueo(reservaId: number): Promise<void>;

consultarBloqueo(reservaId: number): Promise<{
  vigente: boolean;
  bloqueadoHasta: string | null;
}>;
```

### 6.2 Endpoints propuestos

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/vuelos/{id}/asientos/` | Mapa de asientos actualizado |
| `POST` | `/api/v1/reservas/` | Crea reserva y bloquea asientos |
| `POST` | `/api/v1/reservas/{id}/bloquear-asientos/` | Bloquea o reemplaza asientos |
| `POST` | `/api/v1/reservas/{id}/liberar-bloqueo/` | Libera asientos manualmente |
| `GET` | `/api/v1/reservas/{id}/bloqueo/` | Consulta vigencia del bloqueo |

### 6.3 Funciones y componentes de UI

- `MapaAsientos`: representación gráfica por filas y columnas.
- `LeyendaAsientos`: disponible, seleccionado, bloqueado por otro, ocupado, inhabilitado.
- `SeleccionAsientos`: permite seleccionar tantos asientos como pasajeros haya.
- `useCountdownBloqueo(bloqueadoHasta)`: cuenta regresiva de 10 minutos.
- `BloqueoExpiradoModal`: avisa que el bloqueo venció y ofrece volver a seleccionar.
- `ConflictoAsientoModal`: aparece ante `409` e indica qué asiento dejó de estar disponible.
- `ActualizarMapaButton`: refresca manualmente el inventario.
- Actualización automática cada 15–30 segundos o mediante WebSocket/SSE si el backend lo expone.

### 6.4 Reglas de UI

- El contador se calcula con la hora del servidor (`bloqueadoHasta`), no con la hora local del navegador.
- Al llegar a cero:
  - deshabilitar el botón de pago;
  - mostrar modal de expiración;
  - refrescar el mapa de asientos;
  - no permitir confirmar con asientos vencidos.
- Si otro usuario toma un asiento, la UI debe refrescar y marcar el conflicto; nunca reintentar silenciosamente con otro asiento.
- La UI puede mostrar disponibilidad, pero **la reserva y el bloqueo siempre los confirma el backend**.
- Si la red falla durante el bloqueo, no asumir éxito: consultar `GET /reservas/{id}/bloqueo/`.
- No permitir seleccionar asientos `OCUPADO`, `INHABILITADO` ni `BLOQUEADO` por otra reserva.

### 6.5 Criterios de aceptación

- Dos sesiones distintas no pueden reservar el mismo asiento.
- El contador muestra minutos y segundos y es consistente entre pestañas.
- Al expirar, los asientos se liberan y la UI lo refleja.
- Un `409` produce un mensaje comprensible y un refresco del mapa.
- El usuario puede completar una reserva con varios pasajeros y varios asientos.
- El total mostrado coincide con el total calculado por el backend.

---

## 7. Pasarela de pagos Webpay Sandbox

### 7.1 Funciones del cliente API

```ts
iniciarPago(reservaId: number, idempotencyKey: string): Promise<{
  pagoId: number;
  monto: string;
  moneda: "CLP";
  urlWebpay: string;
  token: string;
}>;

confirmarPago(token: string): Promise<{
  pagoId: number;
  estado: "APROBADO" | "RECHAZADO" | "EXPIRADO" | "ANULADO";
  reservaId: number;
  reservaEstado: string;
  mensaje: string;
}>;

consultarPago(pagoId: number): Promise<ResultadoPago>;
```

### 7.2 Flujo obligatorio

1. El usuario confirma la reserva y pulsa **Pagar**.
2. El frontend genera una `Idempotency-Key` y llama a `iniciarPago`.
3. El backend crea el pago pendiente y devuelve la URL de Webpay.
4. El frontend redirige al usuario a Webpay.
5. Webpay retorna a la URL de retorno del frontend con un token.
6. El frontend envía el token a `confirmarPago`.
7. **El backend** consulta a Webpay y confirma o rechaza la transacción.
8. El frontend muestra el resultado y actualiza la reserva.

### 7.3 Endpoints propuestos

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/pagos/iniciar/` | Crea intento de pago y devuelve URL de Webpay |
| `POST` | `/api/v1/pagos/confirmar/` | Confirma el retorno de Webpay |
| `GET` | `/api/v1/pagos/{id}/` | Consulta estado del pago |

### 7.4 Pantallas y componentes

- `ResumenPago`: monto, moneda, reserva y cantidad de pasajeros.
- `BotonPagar`: deshabilitado durante el proceso y ante bloqueo vencido.
- `RedireccionWebpay`: maneja la salida hacia la pasarela.
- `ResultadoPagoPage`: estados aprobado, rechazado, expirado y error de red.
- `ReintentarPagoButton`: solo si el pago fue rechazado o expiró.
- `PagoPendientePage`: para retornos sin confirmación inmediata.

### 7.5 Reglas de UI

- **Nunca** capturar ni almacenar número de tarjeta, CVV, fecha de expiración ni datos de banda.
- El monto se muestra desde el backend; no se recalcula en el cliente.
- No confirmar una reserva solo porque Webpay redirigió correctamente: esperar la respuesta de `confirmarPago`.
- Reutilizar la misma `Idempotency-Key` al reintentar el mismo pago.
- Si el pago ya fue aprobado, no permitir un segundo cobro.
- Mostrar siempre el estado final: aprobado, rechazado, expirado o anulado.

### 7.6 Criterios de aceptación

- Un pago aprobado confirma la reserva y emite los tickets.
- Un pago rechazado libera los asientos y muestra opción de reintentar.
- Un doble clic o doble retorno de Webpay no genera dos pagos aprobados.
- El frontend no envía ni recibe datos sensibles de tarjeta.
- El monto mostrado y el cobrado coinciden exactamente.

---

## 8. Motor de notificaciones

### 8.1 Funciones del cliente API

```ts
interface Notificacion {
  id: number;
  tipo: "CONFIRMACION_RESERVA" | "PAGO" | "CAMBIO_VUELO" |
        "REPROGRAMACION" | "RETRASO" | "CANCELACION" |
        "RECORDATORIO_CHECKIN" | "DEVOLUCION" | "GENERAL";
  canal: "EMAIL" | "POPUP";
  estado: "PENDIENTE" | "ENVIADA" | "FALLIDA" | "LEIDA";
  asunto: string;
  mensaje: string;
  reservaId?: number;
  vueloId?: number;
  creadaEn: string;
  leidaEn?: string | null;
}

listarNotificaciones(params?: {
  estado?: string;
  page?: number;
}): Promise<Pagina<Notificacion>>;

marcarNotificacionLeida(id: number): Promise<void>;

marcarTodasLeidas(): Promise<void>;
```

### 8.2 Endpoints propuestos

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/notificaciones/` | Lista notificaciones del usuario |
| `POST` | `/api/v1/notificaciones/{id}/leer/` | Marca una como leída |
| `POST` | `/api/v1/notificaciones/leer-todas/` | Marca todas como leídas |
| `GET` | `/api/v1/notificaciones/stream/` | SSE/WebSocket para pop-ups (opcional) |

### 8.3 Componentes y funciones de UI

- `NotificationBell`: campana con contador de no leídas.
- `NotificationToast`: pop-up temporal para eventos nuevos.
- `NotificationCenter`: lista paginada con filtros y estado leído/no leído.
- `FlightAlertBanner`: banner persistente para retraso, reprogramación o cancelación.
- `useNotificacionesTiempoReal()`: conexión SSE/WebSocket o polling cada 30–60 segundos.
- `marcarComoLeida(id)`: actualiza el contador de forma optimista y revierte si falla.

### 8.4 Reglas de UI

- No mostrar el mismo pop-up dos veces para la misma notificación.
- Las notificaciones críticas de vuelo (cancelación/reprogramación) deben ser persistentes, no solo un toast.
- El correo lo envía el backend; el frontend no necesita enviar correos.
- Si el usuario no tiene sesión, no abrir conexiones de notificaciones.
- Al cerrar sesión, limpiar el estado y desconectar el stream.

### 8.5 Criterios de aceptación

- El contador de no leídas coincide con el backend.
- Marcar como leída actualiza la UI sin recargar la página.
- Un cambio de vuelo genera una alerta visible en la sesión del pasajero afectado.
- Los pop-ups no se duplican tras reconectar.
- La UI sigue funcionando si el stream en tiempo real no está disponible (fallback a polling).

---

## 9. Check-in y pase de abordar

> La pantalla de check-in pertenece al Programador 1, pero consume servicios del Programador 3. Este apartado define la integración mínima.

### 9.1 Funciones del cliente API

```ts
consultarVentanaCheckIn(reservaPasajeroId: number): Promise<{
  disponible: boolean;
  abreEn: string;
  cierraEn: string;
  mensaje: string;
}>;

realizarCheckIn(
  reservaPasajeroId: number,
  aceptaPoliticas: boolean
): Promise<{
  checkInId: number;
  codigoQr: string;
  fechaCheckIn: string;
  ticket: { codigoTicket: string };
}>;
```

### 9.2 Componentes y funciones de UI

- `VentanaCheckInInfo`: indica si faltan horas o si ya está disponible.
- `AceptarPoliticasCheckbox`: obligatorio antes de continuar.
- `BotonCheckIn`: deshabilitado fuera de la ventana de 48 h a 2 h.
- `PaseAbordar`: muestra pasajero, vuelo, asiento, puerta y **código QR**.
- `QrRenderer`: renderiza el `codigoQr` recibido; no genera un QR propio.
- `DescargarPasePDF` (opcional): descarga o imprime el pase.

### 9.3 Reglas de UI

- La ventana se calcula con la hora del servidor y la zona `America/Santiago`.
- El frontend puede informar la ventana, pero **el backend es quien valida**.
- No permitir check-in si la reserva no está `CONFIRMADA`.
- El QR debe provenir del backend; no inventar ni modificar el identificador.
- Si el check-in ya existe, mostrar el pase existente en lugar de duplicarlo.

### 9.4 Criterios de aceptación

- Fuera de la ventana 48 h–2 h, el botón está deshabilitado y se explica el motivo.
- Sin aceptar políticas, no se puede confirmar el check-in.
- El pase muestra un QR escaneable y persistente.
- Un segundo intento devuelve el mismo check-in, no uno nuevo.

---

## 10. Funciones transversales del frontend

Estas funciones deben implementarse una sola vez y reutilizarse en todos los módulos.

```ts
apiFetch<T>(ruta: string, opciones?: RequestInit): Promise<T>;

normalizarError(error: unknown): {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

formatearCLP(monto: string | number): string;        // $125.000
formatearFechaHora(iso: string): string;             // 07-11-2026 18:30
formatearDuracion(segundos: number): string;         // 09:59
```

Requisitos:

- Manejo centralizado de `401`, `403`, `404`, `409`, `429` y `500`.
- Estados de carga con skeletons o spinners.
- Estados vacíos con mensajes claros.
- Validación de formularios en cliente, sin reemplazar la validación del backend.
- Accesibilidad: etiquetas, foco visible, navegación por teclado y contraste.
- Diseño responsive para escritorio y móvil.
- No registrar datos personales ni tokens en consola.
- No cachear respuestas sensibles de pago o autenticación.

### 10.1 Manejo de errores HTTP

| Código | Significado | Comportamiento UI |
|---|---|---|
| `400` | Datos inválidos | Mostrar errores por campo |
| `401` | Sesión expirada | Limpiar sesión y redirigir al login |
| `403` | Sin permisos | Mostrar acceso denegado |
| `404` | Recurso inexistente | Mostrar estado vacío o volver al listado |
| `409` | Conflicto de asiento o pago duplicado | Refrescar datos y explicar el conflicto |
| `429` | Demasiadas solicitudes | Mostrar espera y deshabilitar reintento temporalmente |
| `500` | Error del servidor | Mensaje genérico y opción de reintentar |

---

## 11. Trazabilidad con la asignación del Programador 3

| Responsabilidad del Programador 3 | Función de frontend asociada | Módulo de este README |
|---|---|---|
| Base de datos y autenticación RBAC | Login, logout, sesión, guards por rol | 4 |
| Gestión de catálogo con API REST | Tabla, formulario, desactivar/reactivar vuelos | 5 |
| Inventario y concurrencia con bloqueo de 10 min | Mapa de asientos, contador, manejo de conflictos | 6 |
| Pasarela Webpay Sandbox con Adapter e idempotencia | Iniciar pago, redirección, confirmación, reintento | 7 |
| Motor de notificaciones por correo y pop-ups | Campana, toasts, centro y alertas de vuelo | 8 |
| Servicio de check-in con QR y ventana 48 h–2 h | Aviso de ventana, aceptación de políticas, pase con QR | 9 |

---

## 12. Checklist de entrega del frontend

- [ ] Login, logout y recuperación de sesión funcionando.
- [ ] Rutas protegidas por rol y manejo de `401`/`403`.
- [ ] Listado de vuelos con filtros y paginación.
- [ ] Formulario de vuelo con validaciones y errores del backend.
- [ ] Desactivación lógica y reactivación de vuelos.
- [ ] Mapa de asientos con leyenda y estados en tiempo real.
- [ ] Cuenta regresiva de 10 minutos basada en la hora del servidor.
- [ ] Manejo de `409` por asiento ocupado o bloqueado.
- [ ] Flujo de pago con Webpay y confirmación en servidor.
- [ ] Idempotencia en reintentos de pago.
- [ ] Pantallas de pago aprobado, rechazado, expirado y error.
- [ ] Campana y centro de notificaciones con contador.
- [ ] Pop-ups sin duplicados y alertas persistentes de vuelo.
- [ ] Check-in con ventana horaria, aceptación de políticas y QR.
- [ ] Estados de carga, vacío y error en todas las pantallas.
- [ ] Formato de moneda CLP y fechas en America/Santiago.
- [ ] Sin datos de tarjeta ni tokens en almacenamiento inseguro.

---

## 13. Anexos: ejemplos de contrato

### 13.1 Login

```http
POST /api/v1/auth/login/
Content-Type: application/json

{
  "username": "pasajero1",
  "password": "ClaveSegura123"
}
```

```json
{
  "id": 1,
  "username": "pasajero1",
  "email": "pasajero1@skyandes.cl",
  "nombre": "Ana Pérez",
  "rol": "PASAJERO",
  "estado": "ACTIVO",
  "permisos": ["ver_vuelos", "crear_reserva"]
}
```

### 13.2 Mapa de asientos

```http
GET /api/v1/vuelos/10/asientos/
```

```json
{
  "vueloId": 10,
  "actualizadoEn": "2026-11-07T18:30:00-03:00",
  "asientos": [
    { "id": 1, "fila": "1", "numero": "A", "clase": "ECONOMICA", "precio": "50000.00", "estado": "DISPONIBLE", "bloqueadoHasta": null },
    { "id": 2, "fila": "1", "numero": "B", "clase": "ECONOMICA", "precio": "50000.00", "estado": "BLOQUEADO", "bloqueadoHasta": "2026-11-07T18:40:00-03:00" },
    { "id": 3, "fila": "1", "numero": "C", "clase": "ECONOMICA", "precio": "50000.00", "estado": "OCUPADO", "bloqueadoHasta": null }
  ]
}
```

### 13.3 Bloqueo de asientos

```http
POST /api/v1/reservas/55/bloquear-asientos/
Content-Type: application/json

{
  "asientoIds": [1, 4]
}
```

```json
{
  "reservaId": 55,
  "bloqueadoHasta": "2026-11-07T18:40:00-03:00",
  "asientos": [
    { "id": 1, "estado": "BLOQUEADO" },
    { "id": 4, "estado": "BLOQUEADO" }
  ]
}
```

Conflicto:

```http
HTTP/1.1 409 Conflict
```

```json
{
  "code": "ASIENTO_BLOQUEADO",
  "message": "El asiento 1A está bloqueado por otra reserva.",
  "details": { "asientoId": 1 }
}
```

### 13.4 Inicio de pago

```http
POST /api/v1/pagos/iniciar/
Idempotency-Key: 6f1c2a9e-4b7d-4f0e-9a3c-2d8b1e5f7a10
Content-Type: application/json

{
  "reservaId": 55
}
```

```json
{
  "pagoId": 90,
  "monto": "100000.00",
  "moneda": "CLP",
  "urlWebpay": "https://webpay3gint.transbank.cl/...",
  "token": "..."
}
```

### 13.5 Notificación

```json
{
  "id": 300,
  "tipo": "CANCELACION",
  "canal": "POPUP",
  "estado": "ENVIADA",
  "asunto": "Vuelo SK100 cancelado",
  "mensaje": "El vuelo SK100 Santiago → Antofagasta fue cancelado.",
  "reservaId": 55,
  "vueloId": 10,
  "creadaEn": "2026-11-07T18:30:00-03:00",
  "leidaEn": null
}
```

---

## 14. Nota final

Este README define el **contrato funcional de frontend** para la parte del Programador 3. Los endpoints indicados son la interfaz propuesta entre frontend y backend; si el backend implementa rutas distintas, debe actualizarse este documento y mantenerse la misma semántica de estados, errores e idempotencia.

La lógica crítica —bloqueo de asientos, confirmación de pagos, expiración de reservas y emisión de tickets— **siempre se valida en el servidor**. El frontend solo representa el estado, guía al usuario y maneja los errores de forma comprensible.
