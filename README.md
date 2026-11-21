# Orion Code

Agente de terminal para Termux con la API de Gemini.

## Interfaces

- **TUI (si está instalado Textual):** pantalla completa.
  ```bash
  orion
  orion --tui
  ```
- **Modo clásico:**
  ```bash
  orion --cli
  ```
- **Una sola petición:** `orion -p "explica este error"`. Sin terminal interactiva, las acciones que requieren permiso se deniegan.

## Instalación (Termux)

```bash
pkg install python git
bash install.sh
orion
```

`install.sh` instala las dependencias obligatorias (`requirements.txt`) y, si puede, los extras de la TUI (`requirements-optional.txt`).

## Git y GitHub

La primera vez que hagas un commit o un push, Orion te pedirá en el propio chat tu nombre,
tu correo y, si hace falta, un token de GitHub (Settings -> Developer settings -> Personal
access tokens). Con eso configura `git` y guarda el token en `~/.orion-code/.env`
(permisos 600, solo lectura para ti). No hace falta repetirlo: se recuerda entre sesiones y
entre repositorios. El token nunca se imprime en pantalla ni se guarda en el historial del chat.

## Permisos

Las acciones que modifican algo (escribir archivos, `git add/commit/push/pull`, `git init`, borrar la memoria y comandos de shell que no sean de solo lectura) piden confirmación `s/N`. El modelo no puede confirmar por su cuenta.

Los archivos sensibles (`.env`, claves SSH, `credentials`, etc.) no se leen, no se añaden a git y no se envían al modelo.

## Copias de seguridad

- Se guarda una copia local en `~/.orion-code/backup` al salir y con `/backup`.
- `/backup compartir` exporta a `~/storage/shared/orion-cerebro`. Otras apps del teléfono pueden leer esa carpeta.
- `/restaurar` recupera desde la copia compartida y `/restaurar local` desde la local. Nunca se restaura de forma automática.

## Comandos

`/` ayuda · `/config` · `/git` · `/proyecto` · `/image` · `/model` · `/red` · `/animo` · `/diario` · `/backup` · `/restaurar` · `/save` · `/load` · `/clear` · `/salir`

En la TUI: `F1` ayuda, `Ctrl+C` salir, `PgUp/PgDn` desplazar, `End` final.

Adjuntar archivos: `@ruta/archivo.py` o `@carpeta`. El `@` debe ir al inicio o después de un espacio, así que los correos no disparan búsquedas.

## Licencia

MIT
