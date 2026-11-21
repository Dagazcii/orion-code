"""Audit de canales"""
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
    # /audit
    # ============================================================

    def es_canal_privado(canal: discord.abc.GuildChannel) -> bool:
        """Un canal se considera privado si @everyone no tiene view_channel."""
        overwrite = canal.overwrites_for(canal.guild.default_role)
        return overwrite.view_channel is False


    def resolver_acceso_canal(canal: discord.abc.GuildChannel):
        """Lista (target, tipo, via) para cada rol/usuario con view_channel=True,
        por overwrite explícito o por Administrator (que ignora overwrites)."""
        resultado = []
        for target, overwrite in canal.overwrites.items():
            if overwrite.view_channel is True:
                tipo = "rol" if isinstance(target, discord.Role) else "usuario"
                resultado.append((target, tipo, "overwrite"))
        for rol in canal.guild.roles:
            if rol.permissions.administrator and rol != canal.guild.default_role:
                if not any(t == rol for t, _, _ in resultado):
                    resultado.append((rol, "rol", "administrator"))
        return resultado


    def roles_permitidos(guild: discord.Guild) -> set[int]:
        propios = set(cfg(guild.id)["audit_roles"])
        return propios or {r for r in ALLOWED_ROLE_IDS if guild.get_role(r)}


    @bot.tree.command(name="audit", description="Revisa qué usuarios/roles tienen acceso a canales privados")
    @app_commands.describe(canal="Canal específico a auditar (opcional, si no se pasa revisa todos)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def audit(interaction: discord.Interaction, canal: discord.TextChannel | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        gid = guild.id
        permitidos = roles_permitidos(guild)

        if canal is not None:
            canales_a_revisar = [canal]
        else:
            canales_a_revisar = [
                c for c in guild.channels
                if isinstance(c, (discord.TextChannel, discord.VoiceChannel, discord.ForumChannel))
                and es_canal_privado(c)
            ]

        if not canales_a_revisar:
            await interaction.followup.send(L(
                gid, "No se encontraron canales privados (ningún canal tiene @everyone con acceso denegado).",
                "No private channels found (no channel denies @everyone access)."))
            return

        if not permitidos:
            await interaction.followup.send(L(
                gid, "⚠️ No hay roles autorizados configurados: todo acceso se marcará como inesperado. "
                     "Usa `/config auditroles`.",
                "⚠️ No authorized roles configured: all access will be flagged. Use `/config auditroles`."))

        embeds: list[discord.Embed] = []
        total_anomalias = 0

        for c in canales_a_revisar:
            esperadas, anomalas = [], []
            for target, tipo, via in resolver_acceso_canal(c):
                if tipo == "rol":
                    linea = f"@{target.name}" + (" (bypass: Administrator)" if via == "administrator"
                                                 else L(gid, " (overwrite directo)", " (direct overwrite)"))
                    (esperadas if target.id in permitidos else anomalas).append(linea)
                else:
                    anomalas.append(L(gid, f"{target.mention} (overwrite individual de usuario, no por rol)",
                                      f"{target.mention} (individual user overwrite, not via role)"))
            if not anomalas:
                continue
            total_anomalias += len(anomalas)
            embed = discord.Embed(title=f"⚠️ #{c.name}", color=discord.Color.red())
            embed.add_field(name=L(gid, "Acceso inesperado", "Unexpected access"),
                            value="\n".join(anomalas)[:1024], inline=False)
            if esperadas:
                embed.add_field(name=L(gid, "Acceso esperado (referencia)", "Expected access (reference)"),
                                value="\n".join(esperadas)[:1024], inline=False)
            embeds.append(embed)

        if not embeds:
            await interaction.followup.send(L(
                gid, f"Revisados {len(canales_a_revisar)} canal(es) privado(s). Sin anomalías.",
                f"Checked {len(canales_a_revisar)} private channel(s). No anomalies."))
            return

        await interaction.followup.send(L(
            gid, f"Revisados {len(canales_a_revisar)} canal(es) privado(s). {total_anomalias} anomalía(s) en {len(embeds)} canal(es).",
            f"Checked {len(canales_a_revisar)} private channel(s). {total_anomalias} anomaly(ies) in {len(embeds)} channel(s)."))
        for i in range(0, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[i:i + 10])


    core.roles_permitidos = roles_permitidos
