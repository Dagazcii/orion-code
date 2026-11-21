"""
AegisBot (Termux) — entrada principal.

Estructura:
  bot.py      → arranque, intents, carga de cogs
  core.py     → DB, permisos, utilidades compartidas
  cogs/       → un módulo por dominio (limpieza, moderación, etc.)
  ayuda.py    → /help (extension aparte)

USO:
  1. export DISCORD_TOKEN="tu_token"
  2. python bot.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sys
import time
import traceback
import subprocess
import importlib

# ------------------------------------------------------------
# Auto-instalación de dependencias
# ------------------------------------------------------------
def _instalar(paquete: str, modulo: str, opcional: bool = False) -> bool:
    try:
        importlib.import_module(modulo)
        return True
    except ImportError:
        print(f"{paquete} no encontrado. Instalando...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", paquete])
            importlib.invalidate_caches()
            importlib.import_module(modulo)
            return True
        except Exception as e:
            if not opcional:
                raise
            print(f"No se pudo instalar {paquete} ({e}). Se continúa sin esa función.")
            return False


_instalar("discord.py", "discord")


def _version_discord() -> tuple:
    try:
        from importlib.metadata import version
        return tuple(int(x) for x in re.findall(r"\d+", version("discord.py"))[:2])
    except Exception:
        return (0, 0)


if _version_discord() < (2, 4) and not os.environ.get("AEGIS_REEXEC"):
    print("discord.py desactualizado. Actualizando y reiniciando...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "discord.py"])
    os.environ["AEGIS_REEXEC"] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import core

core.HAY_UNIDECODE = _instalar("unidecode", "unidecode", opcional=True)
core.HAY_PILLOW = _instalar("Pillow", "PIL", opcional=True)

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core import cfg, L, cargar_db, guardar_db, DB

TOKEN = os.environ.get("DISCORD_TOKEN", "")

# Pydroid / Termux: carpeta del script en sys.path
_CARPETA = os.path.dirname(os.path.abspath(__file__))
if _CARPETA not in sys.path:
    sys.path.insert(0, _CARPETA)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

cargar_db()


def _firma_comandos(tree: app_commands.CommandTree) -> str:
    lineas = []
    for cmd in tree.walk_commands():
        trozos = [cmd.qualified_name, getattr(cmd, "description", "") or ""]
        nl = getattr(cmd, "name_localizations", None) or {}
        dl = getattr(cmd, "description_localizations", None) or {}
        if nl:
            trozos.append("nloc:" + ",".join(f"{k}={v}" for k, v in sorted(nl.items())))
        if dl:
            trozos.append("dloc:" + ",".join(f"{k}={v}" for k, v in sorted(dl.items())))
        for par in getattr(cmd, "parameters", []) or []:
            tipo = getattr(getattr(par, "type", None), "name", None) or str(getattr(par, "type", ""))
            trozos.append(f"{par.name}:{tipo}:{int(bool(getattr(par, 'required', False)))}")
        lineas.append("|".join(trozos))
    lineas.sort()
    return hashlib.sha256("\n".join(lineas).encode()).hexdigest()


# Nombre/descripcion localizados es-ES / en-US (el cliente de Discord elige segun idioma del usuario)
_SLASH_LOC = {
    # name_es, desc_es, desc_en  (name en-US = qualified base name)
    "ping": ("ping", "Prueba que el bot responde", "Check that the bot responds"),
    "help": ("ayuda", "Cómo usar cada comando (solo administradores)", "How to use each command (admins only)"),
    "ban": ("ban", "Banear a un miembro", "Ban a member"),
    "unban": ("unban", "Quitar el ban a un usuario por ID", "Unban a user by ID"),
    "kick": ("kick", "Expulsar a un miembro", "Kick a member"),
    "mute": ("mute", "Silenciar (timeout) a un miembro", "Timeout a member"),
    "unmute": ("unmute", "Quitar el silencio a un miembro", "Remove a member timeout"),
    "softban": ("softban", "Ban + unban inmediato (limpia mensajes)", "Ban + immediate unban (clears messages)"),
    "tempban": ("tempban", "Ban temporal (se desbanea solo)", "Temporary ban (auto-unban)"),
    "case": ("caso", "Consulta un caso de moderación", "Look up a moderation case"),
    "lock": ("bloquear", "Bloquear un canal", "Lock a channel"),
    "unlock": ("desbloquear", "Desbloquear un canal", "Unlock a channel"),
    "lockdown": ("lockdown", "Cerrar o abrir todo el servidor", "Lock or unlock the whole server"),
    "purge": ("purge", "Borrar N mensajes recientes", "Delete N recent messages"),
    "clear": ("clear", "Limpia el canal conservando links y videos", "Clear the channel keeping links and videos"),
    "clearuser": ("clearuser", "Borra mensajes de una persona en este canal", "Delete one person's messages in this channel"),
    "clearall": ("clearall", "Elimina TODO el historial del canal", "Delete the entire channel history"),
    "warn": ("warn", "Advertir a un miembro", "Warn a member"),
    "warns": ("warns", "Ver warns de un miembro", "View a member's warns"),
    "unwarn": ("unwarn", "Quitar un warn concreto", "Remove a specific warn"),
    "clearwarns": ("clearwarns", "Borrar todos los warns de un usuario", "Clear all warns for a user"),
    "userinfo": ("userinfo", "Información de un miembro", "Member information"),
    "slowmode": ("slowmode", "Cambiar el modo lento de un canal", "Change a channel's slowmode"),
    "audit": ("audit", "Revisar acceso a canales privados", "Review access to private channels"),
    "verify": ("verificar", "Dar acceso manual a un pendiente de presentación", "Manually verify a pending member"),
    "rolreaccion": ("rolreaccion", "Añadir emoji+rol a un mensaje de roles", "Add emoji+role to a roles message"),
    "sugerir": ("sugerir", "Enviar una sugerencia", "Submit a suggestion"),
    "confess": ("confesar", "Enviar una confesión anónima", "Send an anonymous confession"),
    "report": ("reportar", "Reportar a un usuario a la red global", "Report a user to the global network"),
    "reportinfo": ("reportinfo", "Ver reportes de un usuario", "View reports for a user"),
    "reportremove": ("reportremove", "Retirar el reporte de este servidor", "Withdraw this server's report"),
    "reportadmin": ("reportadmin", "Gestionar la red global de reportes", "Manage the global report network"),
    "giveaways": ("giveaways", "Juegos gratis disponibles ahora", "Free games available now"),
    "weather": ("clima", "Clima actual de una ciudad", "Current weather for a city"),
    "config": ("config", "Configuración del servidor (menú: /config panel)", "Server settings (menu: /config panel)"),
    "config view": ("view", "Muestra la configuración actual", "Show current configuration"),
    "config panel": ("panel", "Configurar el servidor: seguridad, logs, tickets, bienvenida, roles…", "Configure the server: security, logs, tickets, welcome, roles…"),
    "config language": ("language", "Cambia el idioma del bot en este servidor", "Change the bot language in this server"),
    "config modrole": ("modrole", "Agrega o quita un rol de moderador", "Add or remove a moderator role"),
    "config logchannel": ("logchannel", "Define el canal de logs y alertas", "Set the logs and alerts channel"),
    "config words": ("words", "Filtro de vocabulario", "Word filter"),
    "config newaccounts": ("newaccounts", "Alerta de cuentas nuevas", "New account alerts"),
    "config giveaway": ("giveaway", "Tablero de juegos gratis", "Free games board"),
    "config warns": ("warns", "Sanción automática por warns", "Automatic warn punishment"),
    "config autorole": ("autorole", "Rol automático al entrar", "Auto-role on join"),
    "config auditroles": ("auditroles", "Roles autorizados para /audit", "Roles allowed for /audit"),
    "config confess": ("confess", "Confesiones anónimas", "Anonymous confessions"),
}


def aplicar_localizaciones(tree: app_commands.CommandTree):
    """Aplica nombre/descripcion en es-ES y en-US a los slash commands."""
    for cmd in tree.walk_commands():
        key = cmd.qualified_name
        info = _SLASH_LOC.get(key)
        if not info:
            continue
        name_es, desc_es, desc_en = info
        try:
            # Solo localizamos el "leaf" name (ultimo segmento)
            leaf = key.split()[-1]
            cmd.name_localizations = {"es-ES": name_es, "en-US": leaf}
            cmd.description_localizations = {"es-ES": desc_es, "en-US": desc_en}
            # description por defecto en español (comunidad principal)
            if getattr(cmd, "description", None) is not None:
                cmd.description = desc_es
        except Exception as e:
            print(f"[loc] No pude localizar /{key}: {e!r}")


async def sincronizar_comandos(tree: app_commands.CommandTree):
    firma = None
    try:
        firma = _firma_comandos(tree)
    except Exception as e:
        print(f"[sync] No pude calcular la firma ({e!r}). Sincronizo igual.")
    meta = DB.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        DB["meta"] = meta
    if firma and meta.get("cmd_sync") == firma:
        print("Comandos sin cambios: no se sincroniza con Discord.")
        return
    try:
        synced = await tree.sync()
        print(f"Sincronizados {len(synced)} comandos slash")
        if firma:
            meta["cmd_sync"] = firma
            guardar_db()
    except Exception as e:
        print(f"Error al sincronizar comandos: {e}")


# Orden importa: seguridad/moderacion exportan helpers que otros cogs usan
COGS = [
    "cogs.seguridad",
    "cogs.moderacion",
    "cogs.limpieza",
    "cogs.audit",
    "cogs.reportes",
    "cogs.bienvenida",
    "cogs.tickets",
    "cogs.utilidades",
    "cogs.config_cmd",
    "cogs.warns",
    "cogs.logs",
    "cogs.confess",
    "cogs.presentacion",
    "cogs.red",
    "cogs.reaction_roles",
    "cogs.sugerencias",
]


class AegisBot(commands.Bot):
    session: aiohttp.ClientSession
    listo: bool = False

    def idioma_de(self, gid) -> str:
        return cfg(gid)["lang"] if gid else "es"

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        core.bot = self

        # Grupo /config compartido por varios cogs
        core.config_group = app_commands.Group(
            name="config",
            description="Configuración del servidor (usa /config panel para el menú)",
            guild_only=True,
            default_permissions=discord.Permissions(administrator=True),
        )
        self.tree.add_command(core.config_group)

        for ext in COGS:
            try:
                await self.load_extension(ext)
                print(f"[cog] {ext}")
            except Exception as e:
                print(f"[cog] Error cargando {ext}: {e!r}")
                traceback.print_exc()

        # Vistas persistentes
        try:
            if core.TicketPanelView is not None:
                self.add_view(core.TicketPanelView())
            # Claim+Close unificado (evita custom_id duplicado con TicketCloseView)
            if getattr(core, "TicketClaimCloseView", None) is not None:
                self.add_view(core.TicketClaimCloseView())
            elif core.TicketCloseView is not None:
                self.add_view(core.TicketCloseView())
            if getattr(core, "SuggestPanelView", None) is not None:
                self.add_view(core.SuggestPanelView())
            if getattr(core, "SuggestStaffView", None) is not None:
                self.add_view(core.SuggestStaffView())
            if core.ReporteBoton is not None:
                self.add_dynamic_items(core.ReporteBoton)
        except Exception as e:
            print(f"Error registrando botones persistentes: {e}")

        try:
            if "ayuda" not in self.extensions:
                await self.load_extension("ayuda")
        except Exception as e:
            print(f"[ayuda] No se pudo cargar ayuda.py: {e!r}")
            traceback.print_exc()

        try:
            aplicar_localizaciones(self.tree)
        except Exception as e:
            print(f"[loc] {e!r}")
        await sincronizar_comandos(self.tree)

    async def close(self):
        try:
            await self.session.close()
        except Exception:
            pass
        await super().close()


bot = AegisBot(command_prefix="!", intents=intents)
core.bot = bot


def _desenvolver_error(error: Exception) -> Exception:
    """Saca el error real de CommandInvokeError / ExtensionFailed / etc."""
    visto = set()
    while True:
        if id(error) in visto:
            break
        visto.add(id(error))
        orig = getattr(error, "original", None)
        if orig is None or orig is error:
            break
        error = orig
    return error


def _mensaje_error(gid, error: Exception) -> str:
    """Traduce errores comunes de Discord/app_commands a texto usable."""
    error = _desenvolver_error(error)

    if isinstance(error, app_commands.MissingPermissions):
        faltan = ", ".join(getattr(error, "missing_permissions", []) or []) or "?"
        return L(gid, f"Te faltan permisos: `{faltan}`.",
                 f"You lack permissions: `{faltan}`.")
    if isinstance(error, app_commands.BotMissingPermissions):
        faltan = ", ".join(getattr(error, "missing_permissions", []) or []) or "?"
        return L(gid, f"Al bot le faltan permisos: `{faltan}`.",
                 f"The bot is missing permissions: `{faltan}`.")
    if isinstance(error, app_commands.NoPrivateMessage):
        return L(gid, "Este comando solo funciona en un servidor.",
                 "This command only works in a server.")
    if isinstance(error, app_commands.CommandOnCooldown):
        seg = getattr(error, "retry_after", 0) or 0
        return L(gid, f"Espera {seg:.0f}s antes de volver a usar este comando.",
                 f"Wait {seg:.0f}s before using this command again.")
    if isinstance(error, app_commands.TransformerError):
        return L(gid, "No pude entender uno de los parámetros. Revisa el valor e inténtalo de nuevo.",
                 "I couldn't parse one of the parameters. Check the value and try again.")
    if isinstance(error, app_commands.CheckFailure):
        return L(gid, "No estás autorizado para usar este comando.",
                 "You are not authorized to use this command.")
    if isinstance(error, discord.Forbidden):
        code = getattr(error, "code", None)
        if code == 50001 or "50001" in str(error):
            return L(gid,
                     "No tengo acceso a ese canal o recurso (error 50001). "
                     "Dame **Ver canal**, **Leer historial** y **Gestionar mensajes**.",
                     "I can't access that channel or resource (error 50001). "
                     "Give me **View Channel**, **Read Message History** and **Manage Messages**.")
        if code == 50013 or "50013" in str(error):
            return L(gid,
                     "No tengo permisos suficientes (error 50013). Revisa el rol del bot y los permisos del canal.",
                     "I don't have enough permissions (error 50013). Check the bot role and channel permissions.")
        return L(gid, f"Discord me denegó la acción: {error}",
                 f"Discord denied the action: {error}")
    if isinstance(error, discord.NotFound):
        return L(gid, "No encontré ese mensaje, canal o usuario (puede haberse borrado).",
                 "I couldn't find that message, channel or user (it may have been deleted).")
    if isinstance(error, discord.HTTPException):
        return L(gid, f"Discord respondió con error HTTP: {error}",
                 f"Discord returned an HTTP error: {error}")
    return L(gid, "Ocurrió un error inesperado. Quedó registrado en la consola.",
             "Something went wrong. It was logged to the console.")


_ERRORES_ESPERADOS = (
    app_commands.MissingPermissions,
    app_commands.BotMissingPermissions,
    app_commands.NoPrivateMessage,
    app_commands.CheckFailure,
    app_commands.CommandOnCooldown,
    app_commands.TransformerError,
    discord.Forbidden,
    discord.NotFound,
)


@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Manejador global: log en consola + mensaje al usuario (evita 'La aplicación no respondió')."""
    gid = interaction.guild_id
    cmd = interaction.command.qualified_name if interaction.command else "?"
    usuario = getattr(interaction.user, "id", "?")
    real = _desenvolver_error(error)

    # Siempre una línea en consola
    print(f"[error] /{cmd} por {usuario} en guild={gid}: {type(real).__name__}: {real!r}")

    # Traceback completo si no es un fallo "esperado"
    if not isinstance(real, _ERRORES_ESPERADOS):
        try:
            traceback.print_exception(type(real), real, real.__traceback__)
        except Exception:
            traceback.print_exception(type(error), error, error.__traceback__)

    msg = _mensaje_error(gid, error)

    # Intentar avisar al usuario por todos los medios razonables
    enviado = False
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
            enviado = True
        else:
            await interaction.response.send_message(msg, ephemeral=True)
            enviado = True
    except discord.HTTPException as e1:
        print(f"[error] No pude responder la interaction: {e1!r}")
        try:
            await interaction.followup.send(msg, ephemeral=True)
            enviado = True
        except discord.HTTPException as e2:
            print(f"[error] Tampoco followup: {e2!r}")
            try:
                if interaction.channel is not None:
                    await interaction.channel.send(
                        f"{interaction.user.mention} {msg}",
                        delete_after=20,
                    )
                    enviado = True
            except discord.HTTPException as e3:
                print(f"[error] Tampoco por canal: {e3!r}")
    if not enviado:
        print(f"[error] El usuario no recibió aviso de /{cmd} (interaction huérfana).")


@bot.tree.command(name="ping", description="Prueba que el bot responde")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"🏓 {round(bot.latency * 1000)} ms · pid {os.getpid()}", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user} (pid {os.getpid()})")
    if not bot.listo:
        bot.listo = True
        for gid_s, g in list(DB["guilds"].items()):
            ld = g.get("lockdown", {})
            if ld.get("active") and core.programar_levantamiento:
                restante = ld.get("until", 0) - time.time()
                core.programar_levantamiento(int(gid_s), max(0, restante))
        # Limpieza de datos muertos al arrancar (en background)
        try:
            asyncio.create_task(core.limpiar_datos_muertos(bot))
        except Exception as e:
            print(f"[limpieza-db] arranque: {e!r}")



@bot.event
async def on_guild_join(guild: discord.Guild):
    """Aviso al dueño cuando el bot entra a un servidor."""
    gid = guild.id
    cfg(gid)
    guardar_db()

    me = guild.me
    perms_needed = [
        ("view_channel", "Ver canales", "View Channels"),
        ("send_messages", "Enviar mensajes", "Send Messages"),
        ("embed_links", "Insertar enlaces", "Embed Links"),
        ("attach_files", "Adjuntar archivos", "Attach Files"),
        ("manage_messages", "Gestionar mensajes", "Manage Messages"),
        ("moderate_members", "Aislar miembros (timeout)", "Timeout Members"),
        ("kick_members", "Expulsar miembros", "Kick Members"),
        ("ban_members", "Banear miembros", "Ban Members"),
        ("manage_channels", "Gestionar canales", "Manage Channels"),
        ("manage_roles", "Gestionar roles", "Manage Roles"),
        ("add_reactions", "Añadir reacciones", "Add Reactions"),
        ("read_message_history", "Leer historial", "Read Message History"),
    ]
    faltan = []
    if me is not None:
        p = me.guild_permissions
        for attr, es_n, en_n in perms_needed:
            if not getattr(p, attr, False):
                faltan.append(L(gid, es_n, en_n))

    es = cfg(gid)["lang"] != "en"
    if es:
        titulo = "AegisBot ya está en el servidor"
        desc = (
            "Usa **/config panel** para configurar seguridad, logs, tickets, "
            "bienvenida, presentación y roles por reacción.\n\n"
        )
        if faltan:
            desc += "**Permisos que me faltan (recomendados):**\n"
            desc += "\n".join(f"• `{x}`" for x in faltan)
        else:
            desc += (
                "Tengo los permisos recomendados a nivel de servidor. "
                "Revisa también los de cada canal si algo falla."
            )
    else:
        titulo = "AegisBot joined the server"
        desc = (
            "Use **/config panel** to set up security, logs, tickets, "
            "welcome, introduction and reaction roles.\n\n"
        )
        if faltan:
            desc += "**Permissions I'm missing (recommended):**\n"
            desc += "\n".join(f"• `{x}`" for x in faltan)
        else:
            desc += (
                "I have the recommended server-level permissions. "
                "Still check per-channel overrides if something fails."
            )

    embed = discord.Embed(title=titulo, description=desc, color=discord.Color.blurple())
    embed.set_footer(text="AegisBot")

    destinos = []
    if guild.owner is not None:
        destinos.append(guild.owner)
    if guild.system_channel is not None:
        destinos.append(guild.system_channel)

    for dest in destinos:
        try:
            await dest.send(embed=embed)
            break
        except discord.HTTPException:
            continue
    else:
        print(f"[guild_join] No pude avisar en {guild.id} ({guild.name})")


async def hay_internet() -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection("discord.com", 443), timeout=5)
    except Exception:
        return False
    try:
        w.close()
        await w.wait_closed()
    except Exception:
        pass
    return True


def _esperar_internet_inicial():
    espera = 5
    while True:
        try:
            ok = asyncio.run(hay_internet())
        except Exception:
            ok = False
        if ok:
            return
        print(f"[red] Sin internet al arrancar. Reintento en {espera}s...")
        time.sleep(espera)
        espera = min(espera * 2, 60)


if __name__ == "__main__":
    if not TOKEN or TOKEN == "TU_TOKEN_AQUI":
        print("Falta configurar el token. Usa: export DISCORD_TOKEN=\"...\"")
        sys.exit(1)
    espera = 5
    while True:
        _esperar_internet_inicial()
        try:
            bot.run(TOKEN, reconnect=True)
            break
        except discord.LoginFailure:
            print("Token inválido. Revisa DISCORD_TOKEN.")
            sys.exit(1)
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
            print(f"[red] Falló el arranque: {e!r}. Reintento en {espera}s...")
            time.sleep(espera)
            espera = min(espera * 2, 300)
            bot.clear()
