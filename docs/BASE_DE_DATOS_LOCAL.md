# Base de datos local: PostgreSQL con Docker

Documento de trabajo para los tres desarrolladores de SKYANDES.

El objetivo es que cada uno tenga **su propia base de datos PostgreSQL** en el
computador, con la misma versión mayor que se usará en Azure, sin instalar
servicios en el sistema y sin compartir datos por Git.

---

## 1. Qué vamos a usar

| Entorno | Motor | Dónde |
|---|---|---|
| Desarrollo local | PostgreSQL 17 en Docker Compose | `docker-compose.yml` |
| Producción | Azure Database for PostgreSQL Flexible Server | Azure |
| Respaldo local sin Docker | SQLite | Solo si no existe `.env` |

Decisiones:

- **No usamos XAMPP ni MySQL.** El proyecto ya está escrito para PostgreSQL
  (`psycopg`) y el bloqueo de asientos necesita `select_for_update()` real, que
  SQLite no implementa.
- **No se comparte la base de datos.** Se comparten el esquema (migraciones) y
  los archivos de configuración. Cada uno levanta su contenedor.
- **La versión local debe coincidir con la de Azure** (misma versión mayor:
  16, 17 u 18). Por ahora usamos `postgres:17-alpine`.

---

## 2. Requisitos

- Git
- Python 3.14 y `venv`
- Docker Engine 24 o superior
- Docker Compose v2 (`docker compose`, no `docker-compose`)

Verificar:

```bash
docker --version
docker compose version
```

---

## 3. Instalar y habilitar Docker

### Arch Linux / Omarchy

```bash
sudo pacman -S docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Después **cierra sesión y vuelve a entrar** para que se aplique el grupo
`docker`. Verifica:

```bash
docker run --rm hello-world
```

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

Cierra sesión y vuelve a entrar.

### Windows y macOS

Instalar **Docker Desktop** y mantenerlo abierto mientras se trabaja. En
Windows usar WSL2. Los comandos son los mismos (`docker compose ...`).

> En Linux el rendimiento es prácticamente nativo. En Windows/macOS hay una
> capa de virtualización, pero para desarrollo con PostgreSQL sigue siendo
> suficiente.

---

## 4. Preparar el proyecto

```bash
git clone https://github.com/cfainez/SkyAndes.git
cd SkyAndes

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env
```

Editar `.env` si es necesario. Los valores por defecto para local son:

```dotenv
DB_ENGINE=postgresql
DB_NAME=skyandes
DB_USER=skyandes
DB_PASSWORD=skyandes_local
DB_HOST=127.0.0.1
DB_PORT=5432
DB_SSLMODE=disable
```

> `DB_NAME`, `DB_USER`, `DB_PASSWORD` y `DB_PORT` también los lee
> `docker-compose.yml`. Si cambias uno, cambia el otro o usa las mismas
> variables en `.env`.

---

## 5. Levantar PostgreSQL

```bash
docker compose up -d db
docker compose ps
docker compose logs -f db
```

El contenedor se llama `skyandes-db` y debe aparecer como `healthy`. Para salir
de los logs: `Ctrl+C`.

Probar la conexión:

```bash
docker compose exec db psql -U skyandes -d skyandes -c "SELECT version();"
```

Si cambiaste el usuario o la base en `.env`, usa esos valores.

---

## 6. Crear el esquema y ejecutar Django

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abrir:

- Aplicación: <http://127.0.0.1:8000/>
- Admin: <http://127.0.0.1:8000/admin/>

---

## 7. Comandos del día a día

| Acción | Comando |
|---|---|
| Levantar la base | `docker compose up -d db` |
| Ver estado | `docker compose ps` |
| Ver logs | `docker compose logs -f db` |
| Detener sin borrar datos | `docker compose down` |
| Detener solo la base | `docker compose stop db` |
| Abrir consola SQL | `docker compose exec db psql -U skyandes -d skyandes` |
| Backup | `docker compose exec -T db pg_dump -U skyandes -d skyandes > backup.sql` |
| Restaurar | `docker compose exec -T db psql -U skyandes -d skyandes < backup.sql` |
| **Borrar todos los datos locales** | `docker compose down -v` |

> `docker compose down -v` elimina el volumen `skyandes_pgdata`. Úsalo solo
> cuando quieras reiniciar la base desde cero.

Reinicio limpio:

```bash
docker compose down -v
docker compose up -d db
python manage.py migrate
```

---

## 8. Pruebas automatizadas

Con el contenedor levantado y `.env` apuntando a PostgreSQL:

```bash
python manage.py test skyandes -v 2
python manage.py makemigrations --check --dry-run
python manage.py check
```

Django crea una base temporal `test_skyandes`, ejecuta las pruebas y la borra.
El usuario de Docker es superusuario, así que tiene permiso para crearla.

**Importante:** las pruebas deben correr contra PostgreSQL para validar
`select_for_update()` y las restricciones reales. Nunca ejecutar pruebas contra
la base de Azure.

---

## 9. Trabajo en equipo con Git

### Sí se versiona

- `docker-compose.yml`
- `.env.example`
- `requirements.txt`
- `skyandes/migrations/`
- Documentación y fixtures/comandos de datos de ejemplo

### No se versiona

- `.env` (credenciales locales)
- `db.sqlite3`
- `__pycache__/`, `*.pyc`
- `.venv/`
- El volumen de PostgreSQL (`skyandes_pgdata`)

### Flujo al recibir cambios

```bash
git pull
docker compose up -d db
python manage.py migrate
```

### Flujo al cambiar modelos

```bash
python manage.py makemigrations
python manage.py migrate
git add skyandes/migrations/
git commit -m "Agrega migración para ..."
git push
```

Reglas:

- No editar migraciones a mano ni borrar `0001_initial.py`.
- No compartir dumps de la base como método normal de trabajo; si se necesitan
  datos iguales para una demo, crear un comando `seed_demo` o fixtures.
- Si hay conflicto de migraciones, coordinar con el equipo antes de resolverlo.

---

## 10. Paridad con Azure

En Azure se usará **Azure Database for PostgreSQL Flexible Server**. Para
desplegar:

```dotenv
DB_ENGINE=postgresql
DB_HOST=nombre-servidor.postgres.database.azure.com
DB_PORT=5432
DB_NAME=skyandes
DB_USER=usuario_azure
DB_PASSWORD=...
DB_SSLMODE=require
```

Recomendaciones:

- Usar la misma versión mayor que en local (por ejemplo, 17).
- En Azure el SSL es obligatorio: `DB_SSLMODE=require`.
- Agregar la IP de desarrollo o la salida de App Service al firewall del
  servidor flexible.
- No subir `.env` ni contraseñas al repositorio. En Azure usar App Service
  Configuration, Key Vault o GitHub Secrets.
- Ejecutar `python manage.py migrate` como paso de despliegue, no desde la
  aplicación en cada arranque.
- Antes de cambios importantes, generar un backup con `pg_dump`.

---

## 11. Problemas comunes

| Problema | Causa / solución |
|---|---|
| `permission denied ... docker.sock` | Falta el grupo `docker`: `sudo usermod -aG docker "$USER"` y volver a iniciar sesión. |
| `Cannot connect to the Docker daemon` | `sudo systemctl start docker` (o abrir Docker Desktop). |
| `port is already allocated` en 5432 | Otro PostgreSQL/XAMPP está ocupando el puerto. Detenerlo o cambiar `DB_PORT` en `.env` y el mapeo del compose. |
| `password authentication failed` | El volumen se creó con otra contraseña. Ajustar `.env` o reiniciar con `docker compose down -v` (borra datos). |
| `database "skyandes" does not exist` | Revisar `DB_NAME`; el nombre se crea solo la primera vez que se inicializa el volumen. |
| Contenedor `unhealthy` | `docker compose logs db` para ver el error. |
| `ModuleNotFoundError: psycopg` | Activar el venv y ejecutar `pip install -r requirements.txt`. |
| Cambié `.env` y no se aplica | `docker compose up -d --force-recreate db` (solo recrea el contenedor). |
| Quedó XAMPP instalado | `sudo /opt/lampp/uninstall` y, si quedan restos, `sudo rm -rf /opt/lampp`. |

---

## 12. Referencias

- Django + PostgreSQL: <https://docs.djangoproject.com/en/6.1/ref/databases/#postgresql-notes>
- psycopg 3: <https://www.psycopg.org/psycopg3/docs/>
- Azure Database for PostgreSQL: <https://learn.microsoft.com/azure/postgresql/>
- Docker Compose: <https://docs.docker.com/compose/>
