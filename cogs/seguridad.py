"""AutoMod, anti-spam"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import sys
import time
import traceback
import functools
import unicodedata
from collections import deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import core
try:
    from unidecode import unidecode
except ImportError:
    def unidecode(x):
        return x
from core import (
    DB, cfg, L, guardar_db, cargar_db, hacer_backup,
    es_mod, solo_mod, solo_perm, solo_admin, tiene_perm,
    responder, registrar, alerta, http_json,
    pedir_confirmacion, ConfirmarView,
    es_link_o_video, sin_invisibles,
    URL_PATTERN, INVITE_PATTERN, CUSTOM_EMOJI_PATTERN, UNICODE_EMOJI_PATTERN,
    VIDEO_EXTENSIONS, LIMITE_PURGE, ALLOWED_ROLE_IDS, REVIEW_CHANNEL_ID,
    ENTRADAS, SPAM, LOCK_TASKS, SPAM_AVISOS, SILENCIO_CANALES,
    IGNORAR_IDS, marcar_ignorado, era_ignorado, limpiar_ignorados,
    limpiar_memoria_seguridad,
    TICKET_LOCKS, _lock_tickets, CONFESS_CD, CONFESS_COOLDOWN, CONFESS_LOG,
    DATA_FILE, BACKUP_DIR, _si_no,
)



async def setup(bot: commands.Bot):
    core.bot = bot
    config = core.config_group
    # ============================================================
    # AUTOMOD + ANTI-SPAM
    # ============================================================
    _LEET = str.maketrans({"4": "a", "3": "e", "1": "i", "0": "o", "5": "s", "7": "t", "@": "a", "$": "s"})


    def normalizar(texto: str) -> str:
        """Minúsculas, sin acentos (unidecode), sin leet, letras repetidas colapsadas."""
        texto = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", texto)
        if core.HAY_UNIDECODE:
            texto = unidecode(texto)
        else:
            texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
        texto = texto.lower().translate(_LEET)
        return re.sub(r"(.)\1+", r"\1", texto)


    @functools.lru_cache(maxsize=256)
    def compilar_palabras(palabras: tuple):
        patrones = []
        for p in palabras:
            n = normalizar(p).strip()
            letras = [re.escape(ch) for ch in n if not ch.isspace()]
            if letras:
                patrones.append(r"[\W_]{0,2}".join(letras))
        if not patrones:
            return None
        return re.compile(r"(?<![a-z0-9])(?:" + "|".join(patrones) + r")(?![a-z0-9])")


    async def revisar_spam(message: discord.Message, c: dict) -> bool:
        sp = c["antispam"]
        if not sp["enabled"]:
            return False
        key = (message.guild.id, message.author.id)
        dq = SPAM.setdefault(key, deque())
        ahora = time.monotonic()
        dq.append((ahora, message))
        while dq and ahora - dq[0][0] > sp["seconds"]:
            dq.popleft()
        if len(dq) < sp["messages"]:
            return False

        mensajes = [m for _, m in dq]
        dq.clear()
        gid = message.guild.id
        for m in mensajes:
            marcar_ignorado(m.id)
            try:
                await m.delete()
            except discord.HTTPException:
                IGNORAR_IDS.pop(m.id, None)

        miembro = message.author

        # Primera vez en 2 minutos: solo aviso (evita falsos positivos)
        ultimo = SPAM_AVISOS.get(key)
        if sp.get("warn_first", True) and (ultimo is None or ahora - ultimo > 120):
            SPAM_AVISOS[key] = ahora
            try:
                await message.channel.send(
                    L(gid, f"⚠️ {miembro.mention}, baja el ritmo: detecté spam. La próxima vez habrá sanción.",
                      f"⚠️ {miembro.mention}, slow down: spam detected. Next time there will be a penalty."),
                    delete_after=20)
            except discord.HTTPException:
                pass
            try:
                await miembro.send(L(
                    gid, f"⚠️ Aviso en **{message.guild.name}**: enviaste mensajes demasiado rápido. "
                         f"Si se repite en los próximos 2 minutos serás sancionado.",
                    f"⚠️ Warning in **{message.guild.name}**: you sent messages too fast. "
                    f"If it happens again within 2 minutes you'll be penalized."))
            except Exception:
                pass
            await registrar(message.guild, "🚫 Anti-spam (aviso / warning)", f"{miembro.mention} ({miembro.id})",
                            discord.Color.orange(), [("Canal / Channel", message.channel.mention)])
            return True
        SPAM_AVISOS.pop(key, None)

        try:
            if sp["action"] == "kick":
                await miembro.kick(reason="AegisBot anti-spam")
                accion_txt = L(gid, "expulsado", "kicked")
            else:
                await miembro.timeout(timedelta(minutes=10), reason="AegisBot anti-spam")
                accion_txt = L(gid, "silenciado 10 min", "muted 10 min")
        except discord.HTTPException:
            accion_txt = L(gid, "mensajes borrados (no tengo permisos para sancionar)",
                           "messages deleted (missing permissions to punish)")

        try:
            await message.channel.send(
                L(gid, f"🚫 {miembro.mention} detectado por spam: {accion_txt}.",
                  f"🚫 {miembro.mention} flagged for spam: {accion_txt}."), delete_after=8)
        except discord.HTTPException:
            pass
        await registrar(message.guild, "🚫 Anti-spam", f"{miembro.mention} ({miembro.id})", discord.Color.red(),
                        [("Acción / Action", accion_txt), ("Canal / Channel", message.channel.mention)])
        return True


    @bot.listen("on_message")
    async def automod(message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        miembro = message.author
        if not isinstance(miembro, discord.Member) or es_mod(miembro):
            return
        c = cfg(message.guild.id)
        gid = message.guild.id

        try:
            if await revisar_spam(message, c):
                return
        except Exception as e:
            print(f"[antispam] {e}")

        am = c["automod"]
        if not am["enabled"] or not message.content:
            return
        texto = message.content
        visible = sin_invisibles(texto)
        motivo = None

        rx = compilar_palabras(tuple(am["words"]))
        if rx and rx.search(normalizar(texto)):
            motivo = L(gid, "lenguaje no permitido", "prohibited language")
        elif am["block_invites"] and INVITE_PATTERN.search(visible):
            motivo = L(gid, "invitaciones no permitidas", "invites not allowed")
        elif am["block_links"] and URL_PATTERN.search(visible):
            motivo = L(gid, "links no permitidos", "links not allowed")
        elif am["caps"]:
            letras = [ch for ch in texto if ch.isalpha()]
            if len(letras) >= 10 and sum(ch.isupper() for ch in letras) * 100 / len(letras) >= am["caps_threshold"]:
                motivo = L(gid, "exceso de mayúsculas", "excessive caps")
        if motivo is None and am["emojis"]:
            n = len(CUSTOM_EMOJI_PATTERN.findall(texto)) + len(UNICODE_EMOJI_PATTERN.findall(texto))
            if n > am["emoji_limit"]:
                motivo = L(gid, "exceso de emojis", "excessive emojis")

        if motivo is None:
            return

        try:
            marcar_ignorado(message.id)
            await message.delete()
        except discord.HTTPException:
            IGNORAR_IDS.pop(message.id, None)
            return
        try:
            await message.channel.send(
                L(gid, f"⚠️ {miembro.mention}, mensaje eliminado: {motivo}.",
                  f"⚠️ {miembro.mention}, message removed: {motivo}."),
                delete_after=6)
        except discord.HTTPException:
            pass
        await registrar(message.guild, "<:Automod:1561610638055309312> AutoMod", f"{miembro.mention} ({miembro.id})",
                        discord.Color.orange(),
                        [("Motivo / Reason", motivo), ("Canal / Channel", message.channel.mention),
                         ("Mensaje / Message", discord.utils.escape_markdown(texto)[:900])])


    @tasks.loop(minutes=5)
    async def tarea_limpieza_memoria():
        """Limpia IGNORAR_IDS, SPAM, SPAM_AVISOS, ENTRADAS y CONFESS_CD en RAM."""
        try:
            limpiar_memoria_seguridad()
        except Exception as e:
            print(f"[memoria] {e}")


    @tarea_limpieza_memoria.before_loop
    async def _antes_limpieza_memoria():
        await bot.wait_until_ready()




    # exportar helpers usados por confess / config words
    core.normalizar = normalizar
    core.compilar_palabras = compilar_palabras



    # ============================================================
    # ANTI-NUKE LIGERO
    # ============================================================
    NUKE_CHANNEL: dict[int, deque] = {}
    NUKE_ROLE: dict[int, deque] = {}

    def _nuke_track(bucket: dict, guild_id: int, actor_id: int, window: float) -> int:
        ahora = time.monotonic()
        dq = bucket.setdefault(guild_id, deque())
        dq.append((ahora, actor_id))
        while dq and ahora - dq[0][0] > window:
            dq.popleft()
        return sum(1 for t, a in dq if a == actor_id)

    async def _antinuke_reaccionar(guild: discord.Guild, actor: discord.Member | None, tipo: str, count: int):
        gid = guild.id
        an = cfg(gid).get("antinuke") or {}
        if not an.get("enabled", True):
            return
        accion = an.get("action") or "strip"
        if actor is None or actor.id == guild.owner_id or actor.id == guild.me.id:
            await alerta(guild, discord.Embed(
                title=L(gid, f"🛡️ Anti-nuke: {tipo}", f"🛡️ Anti-nuke: {tipo}"),
                description=L(gid, f"Se detectaron **{count}** borrados rápidos (actor desconocido o protegido).",
                              f"**{count}** rapid deletes detected (unknown/protected actor)."),
                color=discord.Color.red(),
            ))
            return
        if actor.top_role >= guild.me.top_role:
            await alerta(guild, discord.Embed(
                title=L(gid, f"🛡️ Anti-nuke: {tipo}", f"🛡️ Anti-nuke: {tipo}"),
                description=L(gid, f"{actor.mention} borró **{count}** elementos pero está por encima del bot.",
                              f"{actor.mention} deleted **{count}** items but is above the bot."),
                color=discord.Color.red(),
            ))
            return
        detalle = f"{actor.mention} ({actor.id}) · {count}× {tipo}"
        if accion == "strip":
            try:
                quitables = [r for r in actor.roles if not r.is_default() and r < guild.me.top_role and not r.managed]
                if quitables:
                    await actor.remove_roles(*quitables, reason=f"AegisBot anti-nuke: {tipo}")
                await alerta(guild, discord.Embed(
                    title=L(gid, "🛡️ Anti-nuke: roles quitados", "🛡️ Anti-nuke: roles stripped"),
                    description=L(gid, f"Se quitaron roles a {detalle} por borrados masivos.",
                                  f"Roles stripped from {detalle} due to mass deletes."),
                    color=discord.Color.red(),
                ))
            except discord.HTTPException as e:
                print(f"[antinuke] strip {e}")
        else:
            await alerta(guild, discord.Embed(
                title=L(gid, f"🛡️ Anti-nuke alerta: {tipo}", f"🛡️ Anti-nuke alert: {tipo}"),
                description=detalle,
                color=discord.Color.red(),
            ))

    @bot.listen("on_guild_channel_delete")
    async def antinuke_channel(channel: discord.abc.GuildChannel):
        guild = channel.guild
        an = cfg(guild.id).get("antinuke") or {}
        if not an.get("enabled", True):
            return
        actor = None
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.channel_delete):
                if entry.target and entry.target.id == channel.id:
                    actor = guild.get_member(entry.user.id) if entry.user else None
                    break
        except discord.HTTPException:
            pass
        actor_id = actor.id if actor else 0
        n = _nuke_track(NUKE_CHANNEL, guild.id, actor_id, float(an.get("seconds") or 15))
        if n >= int(an.get("channel_deletes") or 3):
            await _antinuke_reaccionar(guild, actor, "canales", n)

    @bot.listen("on_guild_role_delete")
    async def antinuke_role(role: discord.Role):
        guild = role.guild
        an = cfg(guild.id).get("antinuke") or {}
        if not an.get("enabled", True):
            return
        actor = None
        try:
            async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.role_delete):
                if entry.target and entry.target.id == role.id:
                    actor = guild.get_member(entry.user.id) if entry.user else None
                    break
        except discord.HTTPException:
            pass
        actor_id = actor.id if actor else 0
        n = _nuke_track(NUKE_ROLE, guild.id, actor_id, float(an.get("seconds") or 15))
        if n >= int(an.get("role_deletes") or 3):
            await _antinuke_reaccionar(guild, actor, "roles", n)


    if not tarea_limpieza_memoria.is_running():
        tarea_limpieza_memoria.start()
