"""Bienvenida"""
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
from collections import deque
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import core
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None
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
    TICKET_LOCKS, _lock_tickets, CONFESS_CD, CONFESS_COOLDOWN, CONFESS_LOG,
    DATA_FILE, BACKUP_DIR, _si_no,
)



async def setup(bot: commands.Bot):
    core.bot = bot
    config = core.config_group
    # ============================================================
    # EVENTOS DE ENTRADA: reportes, cuenta nueva, anti-raid, bienvenida
    # ============================================================
    def _fuente(tam: int, font_id: str | None = None):
        """Carga la tipografía elegida en /config welcome (carpeta fonts/)."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fuentes = getattr(core, "FUENTES_BIENVENIDA", {})
        info = fuentes.get(font_id or "default") or fuentes.get("default") or {}
        candidatas = []
        archivo = info.get("file") if isinstance(info, dict) else None
        if archivo:
            candidatas.append(os.path.join(base, "fonts", archivo))
        candidatas.extend(["DejaVuSans-Bold.ttf", "arial.ttf"])
        for nombre in candidatas:
            try:
                return ImageFont.truetype(nombre, tam)
            except Exception:
                pass
        try:
            return ImageFont.load_default(tam)
        except TypeError:
            return ImageFont.load_default()


    def crear_tarjeta(avatar_bytes: bytes, nombre: str, servidor: str, miembros: int, es: bool,
                      font_id: str | None = None) -> io.BytesIO:
        W, H = 900, 300
        img = Image.new("RGB", (W, H), (24, 26, 48))
        d = ImageDraw.Draw(img)
        for x in range(W):
            t = x / W
            d.line([(x, 0), (x, H)], fill=(int(30 + 60 * t), int(32 + 40 * t), int(70 + 110 * t)))
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((200, 200))
        mask = Image.new("L", (200, 200), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 199, 199), fill=255)
        d.ellipse((44, 44, 256, 256), outline=(255, 255, 255), width=5)
        img.paste(av, (50, 50), mask)
        d.text((290, 60), "Bienvenido" if es else "Welcome", font=_fuente(56, font_id), fill=(255, 255, 255))
        d.text((290, 140), nombre[:24], font=_fuente(38, font_id), fill=(200, 220, 255))
        d.text((290, 200), servidor[:34], font=_fuente(28, font_id), fill=(180, 190, 230))
        d.text((290, 240), (f"Miembro #{miembros}" if es else f"Member #{miembros}"),
               font=_fuente(26, font_id), fill=(160, 170, 210))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf


    async def enviar_bienvenida(member: discord.Member, probar: bool = False):
        g = member.guild
        c = cfg(g.id)
        if not probar and not c["welcome_enabled"]:
            return
        canal = g.get_channel(c["welcome_channel"]) if c["welcome_channel"] else None
        if canal is None:
            return
        texto = (c["welcome_message"].replace("{user}", member.mention)
                 .replace("{server}", g.name).replace("{count}", str(g.member_count)))
        archivo = None
        if core.HAY_PILLOW:
            try:
                datos = await member.display_avatar.replace(size=256, format="png").read()
                buf = await asyncio.to_thread(
                    crear_tarjeta, datos, member.display_name, g.name,
                    g.member_count or 0, c["lang"] != "en", c.get("welcome_font") or "blackgold")
                archivo = discord.File(buf, filename="bienvenida.png")
            except Exception as e:
                print(f"[bienvenida] No se pudo generar la tarjeta: {e}")
        try:
            await canal.send(texto, file=archivo, allowed_mentions=discord.AllowedMentions(users=True)) \
                if archivo else await canal.send(texto, allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException as e:
            print(f"[bienvenida] Error al enviar: {e}")


    @bot.listen("on_member_join")
    async def al_unirse(member: discord.Member):
        g = member.guild
        c = cfg(g.id)
        gid = g.id

        # 1) Red global de reportes
        try:
            otros = [r for r in core.reportes_aprobados(member.id) if r['guild_id'] != gid]
            if otros:
                embed = discord.Embed(
                    title=L(gid, "🚨 Usuario reportado en la red global",
                            "🚨 Reported user in the global network"),
                    description=f"{member.mention} ({member.id})",
                    color=discord.Color.red(), timestamp=discord.utils.utcnow())
                embed.add_field(name=L(gid, "Reportes", "Reports"), value=str(len(otros)), inline=False)
                for r in otros[:3]:
                    embed.add_field(name=r["guild_name"], value=r["reason"][:500], inline=False)
                await alerta(g, embed)
        except Exception as e:
            print(f"[reportes] {e}")

        # 2) Cuenta nueva
        try:
            if c["newacc_enabled"]:
                edad = discord.utils.utcnow() - member.created_at
                if edad < timedelta(days=c["newacc_days"]):
                    await registrar(
                        g, L(gid, "🆕 Cuenta nueva", "🆕 New account"),
                        f"{member.mention} ({member.id})", discord.Color.yellow(),
                        [(L(gid, "Antigüedad", "Account age"),
                          L(gid, f"{edad.days} día(s)", f"{edad.days} day(s)")),
                         (L(gid, "Creada", "Created"), f"<t:{int(member.created_at.timestamp())}:R>")])
        except Exception as e:
            print(f"[cuenta nueva] {e}")

        # 3) Anti-raid
        try:
            ar = c["antiraid"]
            if ar["enabled"] and not member.bot:
                dq = ENTRADAS.setdefault(gid, deque())
                ahora = time.monotonic()
                dq.append((ahora, member.id))
                while dq and ahora - dq[0][0] > ar["seconds"]:
                    dq.popleft()
                if len(dq) >= ar["joins"] and not c["lockdown"]["active"]:
                    ids = [i for _, i in dq]
                    dq.clear()
                    embed = discord.Embed(
                        title=L(gid, "🚨 Posible raid detectado", "🚨 Possible raid detected"),
                        description=L(gid, f"{len(ids)} cuentas entraron en {ar['seconds']}s. Activando lockdown "
                                           f"por {ar['lockdown_minutes']} min.",
                                      f"{len(ids)} accounts joined in {ar['seconds']}s. Enabling lockdown "
                                      f"for {ar['lockdown_minutes']} min."),
                        color=discord.Color.red(), timestamp=discord.utils.utcnow())
                    embed.add_field(name="IDs", value=", ".join(f"<@{i}>" for i in ids)[:1000], inline=False)
                    await alerta(g, embed)
                    asyncio.create_task(core.activar_lockdown(g, ar["lockdown_minutes"], "Anti-raid"))
        except Exception as e:
            print(f"[anti-raid] {e}")

        # 4) Bienvenida
        try:
            await enviar_bienvenida(member)
        except Exception as e:
            print(f"[bienvenida] {e}")

        # 5) Autorol
        try:
            if c["autorole"]:
                rol = g.get_role(c["autorole"])
                if rol is not None and rol < g.me.top_role:
                    await member.add_roles(rol, reason="AegisBot autorole")
        except Exception as e:
            print(f"[autorole] {e}")

        # 5b) Canal de presentación: rol "Sin presentar" hasta que escriba en el canal
        try:
            it = c["intro"]
            if it["enabled"] and it["applied"] and it["pending_role"] and not member.bot:
                pend = g.get_role(it["pending_role"])
                if pend is not None and pend < g.me.top_role:
                    await member.add_roles(pend, reason="AegisBot: pendiente de presentación")
                    ps = it.setdefault("pending_since", {})
                    ps[str(member.id)] = time.time()
                    guardar_db()
        except Exception as e:
            print(f"[intro] {e}")

        # 6) Log de entrada
        try:
            if c["logs"]["members"]:
                await registrar(g, L(gid, "📥 Entró un miembro", "📥 Member joined"),
                                f"{member.mention} ({member.id})", discord.Color.green(),
                                [(L(gid, "Cuenta creada", "Account created"),
                                  f"<t:{int(member.created_at.timestamp())}:R>")])
        except Exception as e:
            print(f"[log entrada] {e}")




    core.enviar_bienvenida = enviar_bienvenida

