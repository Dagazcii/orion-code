"""
AegisBot · núcleo compartido (DB, permisos, utilidades, estado en memoria).
Los cogs importan desde aquí. No registra comandos.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import time
import asyncio
import functools
from collections import deque
from datetime import timedelta

import aiohttp
import discord
from discord import app_commands

# Rellenado por bot.py tras crear el bot
bot = None  # type: ignore

# Opcionales (bot.py los fija tras instalar)
HAY_UNIDECODE = False
HAY_PILLOW = False
unidecode = None  # type: ignore

# --- Config fija ---
ALLOWED_ROLE_IDS: set[int] = {
    1449538999344697446,
    1377376909150650448,
}
REVIEW_CHANNEL_ID = 1557839772221710411

URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
INVITE_PATTERN = re.compile(
    r"(discord\.gg|discord(?:app)?\.com/invite|discord\.me|discord\.io)/\S+", re.IGNORECASE
)
_INVISIBLE = re.compile(r"[\u200b-\u200f\u2060\ufeff\u180e]")

def sin_invisibles(texto: str) -> str:
    return _INVISIBLE.sub("", texto)

CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:\w+:\d+>")
UNICODE_EMOJI_PATTERN = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F000-\U0001F2FF]")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v")
LIMITE_PURGE = timedelta(days=14, minutes=-5)

_BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(_BASE, "aegis_data.json")
BACKUP_DIR = os.path.join(_BASE, "backups")
CONFESS_LOG = os.path.join(_BASE, "confesiones.log")

DEFAULT_GUILD = {
    "lang": "es",
    "mod_roles": [],
    "log_channel": None,
    "welcome_enabled": False,
    "welcome_channel": None,
    "welcome_message": "¡Bienvenido {user} a **{server}**! Eres el miembro #{count}.",
    "welcome_font": "blackgold",
    "newacc_enabled": True,
    "newacc_days": 7,
    "automod": {
        "enabled": True,
        "words": [],
        "block_links": False,
        "block_invites": True,
        "caps": True,
        "caps_threshold": 70,
        "emojis": True,
        "emoji_limit": 10,
    },
    "antispam": {"enabled": True, "messages": 5, "seconds": 3, "action": "mute", "warn_first": True, "v": 2},
    "antiraid": {"enabled": True, "joins": 8, "seconds": 10, "lockdown_minutes": 5},
    "lockdown": {"active": False, "prev": {}, "until": 0},
    "tickets": {
        "category": None,
        "support_role": None,
        "log_channel": None,
        "counter": 0,
        "require_reason": True,
        "autoclose_hours": 48,
        "reasons": [],  # motivos predefinidos
        "active": {},  # channel_id -> opener, claimed_by, last_activity, reason, priority
        "stats": {"opened": 0, "closed": 0},
    },
    "suggestions": {
        "enabled": False,
        "channel": None,
        "counter": 0,
        "anonymous": False,
    },
    "giveaway": {"channel": None, "message_id": None, "platform": "pc"},
    "warns": {"threshold": 3, "action": "mute", "minutes": 60},
    "warn_data": {},
    "logs": {
        "messages": False,
        "members": False,
        "roles": False,
        "channels": False,
        "mod": False,
    },
    "antinuke": {
        "enabled": True,
        "channel_deletes": 3,
        "role_deletes": 3,
        "seconds": 15,
        "action": "strip",  # strip | alert
    },
    "mod_cases": {"counter": 0, "data": {}},  # id -> case dict
    "tempbans": {},  # user_id -> unban_ts
    "reaction_roles": {},  # message_id -> {channel_id, pairs: {emoji_key: role_id}}
    "autorole": None,
    "audit_roles": [],
    "confess": {"enabled": False, "channel": None, "counter": 0},
    "intro": {
        "enabled": False,
        "channel": None,
        "pending_role": None,
        "member_role": None,
        "min_chars": 1,
        "applied": False,
        "touched": [],
        "guide_message_id": None,
        "timeout_days": 0,
        "timeout_action": "alert",
        "pending_since": {},
    },
}

DB: dict = {"guilds": {}, "reports": {}, "meta": {}}

# Estado en memoria
ENTRADAS: dict[int, deque] = {}
SPAM: dict[tuple, deque] = {}
LOCK_TASKS: dict[int, asyncio.Task] = {}
SPAM_AVISOS: dict[tuple, float] = {}
SILENCIO_CANALES: set[int] = set()
IGNORAR_IDS: dict[int, float] = {}
IGNORAR_TTL = 180
TICKET_LOCKS: dict[int, asyncio.Lock] = {}
CONFESS_CD: dict[tuple, float] = {}
CONFESS_COOLDOWN = 30

def _leer_json(ruta):
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)

def cargar_db():
    data = None
    if os.path.exists(DATA_FILE):
        try:
            data = _leer_json(DATA_FILE)
        except Exception as e:
            print(f"{DATA_FILE} dañado: {e}")
            try:
                os.replace(DATA_FILE, DATA_FILE + ".corrupto")
            except OSError:
                pass
            if os.path.isdir(BACKUP_DIR):
                for f in sorted((x for x in os.listdir(BACKUP_DIR) if x.startswith("aegis_data_")), reverse=True):
                    try:
                        data = _leer_json(os.path.join(BACKUP_DIR, f))
                        print(f"Restaurado desde backup: {f}")
                        break
                    except Exception:
                        continue
    if isinstance(data, dict):
        DB["guilds"] = data.get("guilds", {})
        DB["reports"] = data.get("reports", {})
        meta = data.get("meta")
        DB["meta"] = meta if isinstance(meta, dict) else {}
    else:
        DB["meta"] = {}
    migrados = 0
    for lista in DB["reports"].values():
        if not isinstance(lista, list):
            continue
        for r in lista:
            if isinstance(r, dict) and "status" not in r:
                r["status"] = "approved"
                migrados += 1
    if migrados:
        print(f"[reportes] {migrados} reporte(s) antiguo(s) marcados como approved.")
        guardar_db()
    for g in DB["guilds"].values():
        sp = g.get("antispam")
        if isinstance(sp, dict) and sp.get("v", 1) < 2:
            sp.update({"messages": 5, "seconds": 3, "action": "mute", "warn_first": True, "v": 2})

def hacer_backup():
    if not os.path.exists(DATA_FILE):
        return
    os.makedirs(BACKUP_DIR, exist_ok=True)
    destino = os.path.join(BACKUP_DIR, time.strftime("aegis_data_%Y%m%d_%H%M%S.json"))
    shutil.copy2(DATA_FILE, destino)
    if os.path.exists(CONFESS_LOG):
        shutil.copy2(CONFESS_LOG, os.path.join(BACKUP_DIR, time.strftime("confesiones_%Y%m%d_%H%M%S.log")))
    for prefijo in ("aegis_data_", "confesiones_"):
        viejos = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(prefijo))
        for f in viejos[:-5]:
            try:
                os.remove(os.path.join(BACKUP_DIR, f))
            except OSError:
                pass

def guardar_db():
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DB, f, ensure_ascii=False, indent=1)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        print(f"Error guardando datos: {e}")

def _rellenar(dst: dict, src: dict):
    for k, v in src.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(dst[k], dict):
            _rellenar(dst[k], v)

def cfg(gid) -> dict:
    if gid is None:
        return copy.deepcopy(DEFAULT_GUILD)
    g = DB["guilds"].setdefault(str(gid), {})
    _rellenar(g, DEFAULT_GUILD)
    return g

def L(gid, es: str, en: str) -> str:
    return en if gid and cfg(gid)["lang"] == "en" else es

def marcar_ignorado(mid: int):
    """Marca un message_id para que on_message_delete no lo loguee (borrado por el bot)."""
    ahora = time.monotonic()
    # Tope duro: si crece demasiado, tira los más viejos de golpe
    if len(IGNORAR_IDS) > 2500:
        for k, _ in sorted(IGNORAR_IDS.items(), key=lambda kv: kv[1])[:800]:
            IGNORAR_IDS.pop(k, None)
    IGNORAR_IDS[mid] = ahora

def era_ignorado(mid: int) -> bool:
    return IGNORAR_IDS.pop(mid, None) is not None

def limpiar_ignorados():
    """Compat: solo IGNORAR_IDS por TTL."""
    limite = time.monotonic() - IGNORAR_TTL
    for mid, ts in list(IGNORAR_IDS.items()):
        if ts < limite:
            IGNORAR_IDS.pop(mid, None)

def limpiar_memoria_seguridad() -> dict:
    """Limpia estructuras en RAM: IGNORAR_IDS, SPAM, SPAM_AVISOS, ENTRADAS, CONFESS_CD.

    Se llama cada pocos minutos desde cogs/seguridad.py. Evita crecimiento indefinido
    en servidores con mucho tráfico o muchos borrados del AutoMod.
    """
    ahora = time.monotonic()
    stats = {
        "ignorar": 0,
        "spam": 0,
        "spam_avisos": 0,
        "entradas": 0,
        "confess_cd": 0,
    }

    # --- IGNORAR_IDS (TTL + tope) ---
    limite_ig = ahora - IGNORAR_TTL
    for mid, ts in list(IGNORAR_IDS.items()):
        if ts < limite_ig:
            IGNORAR_IDS.pop(mid, None)
            stats["ignorar"] += 1
    if len(IGNORAR_IDS) > 2500:
        sobra = len(IGNORAR_IDS) - 2000
        for k, _ in sorted(IGNORAR_IDS.items(), key=lambda kv: kv[1])[:sobra]:
            IGNORAR_IDS.pop(k, None)
            stats["ignorar"] += 1

    # --- SPAM: deques de (timestamp, ...) por (guild, user, channel) ---
    for key in list(SPAM.keys()):
        dq = SPAM.get(key)
        if not dq:
            SPAM.pop(key, None)
            stats["spam"] += 1
            continue
        # Quitar entradas viejas dentro del deque (> 120 s)
        while dq and ahora - dq[0][0] > 120:
            dq.popleft()
        if not dq or ahora - dq[-1][0] > 120:
            SPAM.pop(key, None)
            stats["spam"] += 1

    # --- SPAM_AVISOS: no reavisar spam reciente ---
    for key, ts in list(SPAM_AVISOS.items()):
        if ahora - ts > 300:
            SPAM_AVISOS.pop(key, None)
            stats["spam_avisos"] += 1

    # --- ENTRADAS: anti-raid (timestamps de joins por guild) ---
    for gid, dq in list(ENTRADAS.items()):
        if not dq:
            ENTRADAS.pop(gid, None)
            stats["entradas"] += 1
            continue
        while dq and ahora - dq[0] > 300:
            dq.popleft()
        if not dq:
            ENTRADAS.pop(gid, None)
            stats["entradas"] += 1

    # --- CONFESS_CD: cooldowns de confesiones ---
    cd_limite = ahora - max(CONFESS_COOLDOWN, 30) - 10
    for key, ts in list(CONFESS_CD.items()):
        if ts < cd_limite:
            CONFESS_CD.pop(key, None)
            stats["confess_cd"] += 1

    total = sum(stats.values())
    if total >= 50:
        print(
            f"[memoria] limpios={total} "
            f"ignorar={len(IGNORAR_IDS)} spam={len(SPAM)} "
            f"avisos={len(SPAM_AVISOS)} entradas={len(ENTRADAS)} confess={len(CONFESS_CD)}"
        )
    return stats

def _lock_tickets(gid: int) -> asyncio.Lock:
    lock = TICKET_LOCKS.get(gid)
    if lock is None:
        lock = asyncio.Lock()
        TICKET_LOCKS[gid] = lock
    return lock

def es_link_o_video(mensaje: discord.Message) -> bool:
    if URL_PATTERN.search(mensaje.content):
        return True
    for embed in mensaje.embeds:
        if embed.url or embed.type in ("link", "video", "image", "article", "gifv"):
            return True
    for adjunto in mensaje.attachments:
        if adjunto.content_type and adjunto.content_type.startswith("video"):
            return True
        if adjunto.filename.lower().endswith(VIDEO_EXTENSIONS):
            return True
    return False

def es_mod(miembro: discord.Member) -> bool:
    p = miembro.guild_permissions
    if p.administrator or p.manage_guild or p.manage_messages:
        return True
    roles_mod = set(cfg(miembro.guild.id)["mod_roles"])
    return any(r.id in roles_mod for r in miembro.roles)

def solo_mod():
    async def pred(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        if es_mod(interaction.user):
            return True
        raise app_commands.CheckFailure("mod")
    return app_commands.check(pred)

def tiene_perm(miembro: discord.Member, perm: str) -> bool:
    p = miembro.guild_permissions
    if p.administrator or getattr(p, perm, False):
        return True
    roles_mod = set(cfg(miembro.guild.id)["mod_roles"])
    return any(r.id in roles_mod for r in miembro.roles)

def solo_perm(perm: str):
    async def pred(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        if tiene_perm(interaction.user, perm):
            return True
        raise app_commands.CheckFailure(perm)
    return app_commands.check(pred)

def solo_admin():
    async def pred(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        if interaction.user.guild_permissions.administrator:
            return True
        raise app_commands.CheckFailure("admin")
    return app_commands.check(pred)

async def responder(interaction: discord.Interaction, texto: str = None, **kw):
    if interaction.response.is_done():
        await interaction.followup.send(texto, **kw)
    else:
        await interaction.response.send_message(texto, **kw)

async def registrar(guild: discord.Guild, titulo: str, descripcion: str,
                    color: discord.Color = None, campos: list | None = None) -> bool:
    gcfg = cfg(guild.id)
    if not gcfg.get("logs", {}).get("mod", False):
        return False
    canal_id = gcfg["log_channel"]
    canal = guild.get_channel(canal_id) if canal_id else None
    if canal is None:
        return False
    embed = discord.Embed(
        title=titulo[:256], description=descripcion[:4000],
        color=color or discord.Color.blurple(), timestamp=discord.utils.utcnow(),
    )
    for nombre, valor in campos or []:
        embed.add_field(name=nombre[:256], value=valor[:1024], inline=False)
    try:
        await canal.send(embed=embed)
        return True
    except discord.HTTPException:
        return False

async def alerta(guild: discord.Guild, embed: discord.Embed):
    canal_id = cfg(guild.id)["log_channel"]
    canal = guild.get_channel(canal_id) if canal_id else None
    try:
        if canal is not None:
            await canal.send(embed=embed)
            return
        owner = guild.owner or await guild.fetch_member(guild.owner_id)
        await owner.send(content=f"[{guild.name}]", embed=embed)
    except Exception:
        pass

async def http_json(url: str, params: dict | None = None):
    async with bot.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
        r.raise_for_status()
        return await r.json(content_type=None)

class ConfirmarView(discord.ui.View):
    def __init__(self, autor_id: int, gid: int | None = None):
        super().__init__(timeout=30)
        self.autor_id = autor_id
        self.gid = gid
        self.confirmado = None
        # Etiquetas segun idioma del servidor
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.style == discord.ButtonStyle.danger:
                    item.label = L(gid, "Confirmar", "Confirm")
                else:
                    item.label = L(gid, "Cancelar", "Cancel")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                L(interaction.guild_id, "Solo quien ejecutó el comando puede confirmar.",
                  "Only the command author can confirm."), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmado = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmado = False
        self.stop()
        await interaction.response.defer()


async def pedir_confirmacion(interaction: discord.Interaction, texto: str) -> bool:
    """Pide confirmación (botones). Si la interaction ya respondió, usa followup."""
    gid = interaction.guild_id
    view = ConfirmarView(autor_id=interaction.user.id, gid=gid)
    if interaction.response.is_done():
        await interaction.followup.send(texto, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(texto, view=view, ephemeral=True)
    await view.wait()
    if view.confirmado is None:
        try:
            await interaction.followup.send(
                L(gid, "Tiempo agotado, operación cancelada.", "Timed out, operation cancelled."),
                ephemeral=True)
        except discord.HTTPException:
            pass
        return False
    if not view.confirmado:
        try:
            await interaction.followup.send(
                L(gid, "Operación cancelada.", "Operation cancelled."), ephemeral=True)
        except discord.HTTPException:
            pass
        return False
    return True


async def limpiar_datos_muertos(bot_ref=None) -> dict:
    """Quita de la DB entradas que apuntan a canales/mensajes/miembros inexistentes."""
    b = bot_ref or bot
    stats = {"reaction_roles": 0, "tickets": 0, "intro_pending": 0, "tempbans": 0}
    if b is None:
        return stats
    ahora = int(time.time())
    for gid_s, gdata in list(DB.get("guilds", {}).items()):
        try:
            gid = int(gid_s)
        except (TypeError, ValueError):
            continue
        guild = b.get_guild(gid)
        if guild is None:
            continue

        # Reaction roles: canal o mensaje desaparecido
        rr = gdata.get("reaction_roles")
        if isinstance(rr, dict):
            for mid in list(rr.keys()):
                entry = rr.get(mid) or {}
                ch_id = entry.get("channel_id")
                ch = guild.get_channel(ch_id) if ch_id else None
                if not isinstance(ch, (discord.TextChannel, discord.Thread)):
                    rr.pop(mid, None)
                    stats["reaction_roles"] += 1
                    continue
                try:
                    await ch.fetch_message(int(mid))
                except discord.NotFound:
                    rr.pop(mid, None)
                    stats["reaction_roles"] += 1
                except (discord.Forbidden, discord.HTTPException, ValueError, TypeError):
                    pass

        # Tickets activos cuyo canal ya no existe
        tk = (gdata.get("tickets") or {}).get("active")
        if isinstance(tk, dict):
            for cid in list(tk.keys()):
                try:
                    c_id = int(cid)
                except (TypeError, ValueError):
                    tk.pop(cid, None)
                    stats["tickets"] += 1
                    continue
                if guild.get_channel(c_id) is None:
                    tk.pop(cid, None)
                    stats["tickets"] += 1

        # Intro: pendientes de miembros que ya no están
        intro = gdata.get("intro") or {}
        ps = intro.get("pending_since")
        if isinstance(ps, dict):
            for uid in list(ps.keys()):
                try:
                    u_id = int(uid)
                except (TypeError, ValueError):
                    ps.pop(uid, None)
                    stats["intro_pending"] += 1
                    continue
                if guild.get_member(u_id) is None:
                    ps.pop(uid, None)
                    stats["intro_pending"] += 1

        # Tempbans ya vencidos (por si la tarea no corrió)
        tb = gdata.get("tempbans")
        if isinstance(tb, dict):
            for uid, until in list(tb.items()):
                try:
                    if int(until) <= ahora:
                        tb.pop(uid, None)
                        stats["tempbans"] += 1
                except (TypeError, ValueError):
                    tb.pop(uid, None)
                    stats["tempbans"] += 1

    if any(stats.values()):
        guardar_db()
        print(f"[limpieza-db] {stats}")
    return stats

def _si_no(v) -> str:
    return "<:aceptado:1560557801464668240>" if v else "<:X_:1560557532836270101>"


# Grupo /config (bot.py lo crea y lo asigna antes de cargar cogs)
config_group = None  # type: ignore

# Helpers de dominio que varios cogs comparten (se rellenan al cargar el cog dueño)
normalizar = None  # type: ignore
compilar_palabras = None  # type: ignore
programar_levantamiento = None  # type: ignore
activar_lockdown = None  # type: ignore
levantar_lockdown = None  # type: ignore
enviar_bienvenida = None  # type: ignore
actualizar_tablero = None  # type: ignore
CHOICES_PLATAFORMA = []
abrir_panel_antispam = None  # type: ignore
abrir_panel_antiraid = None  # type: ignore
abrir_panel_automod = None  # type: ignore
abrir_panel_welcome = None  # type: ignore
abrir_panel_intro = None  # type: ignore
ReporteBoton = None  # type: ignore
TicketPanelView = None  # type: ignore
TicketCloseView = None  # type: ignore

reportes_aprobados = None  # type: ignore


# Tipografías disponibles para la tarjeta de bienvenida (archivos en fonts/)
FUENTES_BIENVENIDA = {
    "default": {
        "label_es": "Sistema (clara)",
        "label_en": "System (clean)",
        "file": None,  # DejaVu / Arial del sistema
    },
    "blackgold": {
        "label_es": "Black Gold",
        "label_en": "Black Gold",
        "file": "TBJBlackGoldMini-Regular.ttf",
    },
    "blackgold_italic": {
        "label_es": "Black Gold cursiva",
        "label_en": "Black Gold italic",
        "file": "TBJBlackGoldMini-Italic.ttf",
    },
    "retro": {
        "label_es": "Retro Space",
        "label_en": "Retro Space",
        "file": "RETRO_SPACE.ttf",
    },
    "mojangles": {
        "label_es": "Mojangles",
        "label_en": "Mojangles",
        "file": "mojangles-v2.otf",
    },
}


TicketClaimCloseView = None  # type: ignore
ReactionRoleView = None  # type: ignore
registrar_caso = None  # type: ignore


class PanelView(discord.ui.View):
    """Base de los paneles de /config: solo quien lo abrió puede tocarlo."""

    def __init__(self, autor_id: int, gid: int):
        super().__init__(timeout=180)
        self.autor_id = autor_id
        self.gid = gid
        self.mensaje: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(
                L(self.gid, "Este panel es de quien ejecutó el comando.",
                  "This panel belongs to whoever ran the command."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.mensaje is not None:
            try:
                await self.mensaje.edit(view=None)
            except discord.HTTPException:
                pass


class NumeroModal(discord.ui.Modal):
    """Modal genérico para editar un valor numérico de un panel."""

    def __init__(self, panel: PanelView, titulo: tuple, etiqueta: tuple,
                 minimo: int, maximo: int, obtener, guardar_valor):
        super().__init__(title=L(panel.gid, *titulo)[:45])
        self.panel = panel
        self.minimo = minimo
        self.maximo = maximo
        self.guardar_valor = guardar_valor
        self.campo = discord.ui.TextInput(
            label=L(panel.gid, *etiqueta)[:45], default=str(obtener(panel.gid)), max_length=6)
        self.add_item(self.campo)

    async def on_submit(self, interaction: discord.Interaction):
        gid = self.panel.gid
        try:
            v = int(self.campo.value.strip())
            if not (self.minimo <= v <= self.maximo):
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                L(gid, f"Tiene que ser un número entero entre {self.minimo} y {self.maximo}.",
                  f"Must be a whole number between {self.minimo} and {self.maximo}."), ephemeral=True)
            return
        self.guardar_valor(gid, v)
        guardar_db()
        await self.panel.actualizar(interaction)

error_jerarquia = None  # type: ignore

SuggestPanelView = None  # type: ignore
SuggestStaffView = None  # type: ignore
abrir_panel_logs = None  # type: ignore
abrir_panel_tickets = None  # type: ignore
abrir_panel_sugerencias = None  # type: ignore
abrir_panel_roles = None  # type: ignore
abrir_panel_intro = None  # type: ignore
