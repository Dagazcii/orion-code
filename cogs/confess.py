"""Confesiones"""
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
    # CONFESIONES ANÓNIMAS
    # ============================================================

    CONFESS_CD: dict[tuple, float] = {}
    CONFESS_COOLDOWN = 30  # segundos entre confesiones por usuario


    def guardar_registro_confesion(guild: discord.Guild, user: discord.abc.User, canal_id: int,
                                   n: int, msg_id: int, texto: str):
        """Añade una línea al archivo confesiones.log (en el servidor, junto a la base de datos)."""
        una_linea = texto.replace("\r", " ").replace("\n", " ⏎ ")
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        linea = (f"[{ts} UTC] #{n} | {guild.name} ({guild.id}) | {user} ({user.id}) "
                 f"[{getattr(user, 'display_name', user.name)}] | canal {canal_id} | msg {msg_id} | {una_linea}\n")
        try:
            with open(CONFESS_LOG, "a", encoding="utf-8") as f:
                f.write(linea)
        except Exception as e:
            print(f"[confess] No se pudo escribir {CONFESS_LOG}: {e}")


    @bot.tree.command(name="confess", description="Envía una confesión anónima al canal de confesiones")
    @app_commands.describe(mensaje="Tu confesión (máx. 1500 caracteres)")
    @app_commands.guild_only()
    async def confess(interaction: discord.Interaction, mensaje: app_commands.Range[str, 1, 1500]):
        gid = interaction.guild_id
        c = cfg(gid)
        cf = c["confess"]

        if not cf["enabled"] or not cf["channel"]:
            await interaction.response.send_message(
                L(gid, "Las confesiones no están activadas en este servidor.",
                  "Confessions are not enabled in this server."), ephemeral=True)
            return
        if interaction.channel_id != cf["channel"]:
            await interaction.response.send_message(
                L(gid, f"Este comando solo funciona en <#{cf['channel']}>.",
                  f"This command only works in <#{cf['channel']}>."), ephemeral=True)
            return

        key = (gid, interaction.user.id)
        ahora = time.monotonic()
        espera = CONFESS_COOLDOWN - (ahora - CONFESS_CD.get(key, -1e9))
        if espera > 0:
            await interaction.response.send_message(
                L(gid, f"Espera {int(espera) + 1}s antes de enviar otra confesión.",
                  f"Wait {int(espera) + 1}s before sending another confession."), ephemeral=True)
            return

        # Mismos filtros que el AutoMod: vocabulario e invitaciones
        rx = core.compilar_palabras(tuple(c["automod"]["words"]))
        if (rx and rx.search(core.normalizar(mensaje))) or INVITE_PATTERN.search(sin_invisibles(mensaje)):
            await interaction.response.send_message(
                L(gid, "Tu confesión contiene contenido no permitido.",
                  "Your confession contains disallowed content."), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        canal = interaction.channel
        n = cf["counter"] + 1
        embed = discord.Embed(title=f"💬 Confesión #{n}" if c["lang"] != "en" else f"💬 Confession #{n}",
                              description=mensaje, color=discord.Color.dark_purple(),
                              timestamp=discord.utils.utcnow())
        try:
            msg = await canal.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            await interaction.followup.send(
                L(gid, f"No pude enviar la confesión: {e}", f"Could not send the confession: {e}"), ephemeral=True)
            return

        cf["counter"] = n
        guardar_db()
        CONFESS_CD[key] = ahora
        guardar_registro_confesion(interaction.guild, interaction.user, canal.id, n, msg.id, mensaje)
        await interaction.followup.send(
            L(gid, f"<:aceptado:1560557801464668240> Confesión #{n} enviada.", f"<:aceptado:1560557801464668240> Confession #{n} sent."), ephemeral=True)


    @config.command(name="confess", description="Activa las confesiones anónimas y elige su canal")
    @app_commands.describe(canal="Único canal donde funcionará /confess", activar="Activar o desactivar")
    @solo_admin()
    async def cfg_confess(interaction: discord.Interaction, canal: discord.TextChannel | None = None,
                          activar: bool | None = None):
        gid = interaction.guild_id
        cf = cfg(gid)["confess"]
        if canal is not None:
            perms = canal.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await interaction.response.send_message(
                    L(gid, "No tengo permisos para enviar embeds en ese canal.",
                      "I can't send embeds in that channel."), ephemeral=True)
                return
            cf["channel"] = canal.id
            if activar is None:
                activar = True
        if activar is not None:
            if activar and not cf["channel"]:
                await interaction.response.send_message(
                    L(gid, "Indica primero un canal.", "Set a channel first."), ephemeral=True)
                return
            cf["enabled"] = activar
        guardar_db()
        estado = "<:aceptado:1560557801464668240>" if cf["enabled"] else "<:X_:1560557532836270101>"
        canal_txt = f"<#{cf['channel']}>" if cf["channel"] else "—"
        await interaction.response.send_message(
            L(gid, f"{estado} Confesiones en {canal_txt}. Los usuarios las envían con `/confess`.",
              f"{estado} Confessions in {canal_txt}. Users send them with `/confess`."), ephemeral=True)




