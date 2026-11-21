"""Limpieza de canales"""
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
    # LIMPIEZA DE CANALES (/clear, /clearuser, /clearall)
    # ============================================================


    def _permisos_limpieza(canal: discord.TextChannel, me: discord.Member) -> list[str]:
        """Devuelve nombres de permisos que le faltan al bot en el canal."""
        perms = canal.permissions_for(me)
        faltan = []
        if not perms.view_channel:
            faltan.append(L(canal.guild.id, "Ver canal", "View Channel"))
        if not perms.read_message_history:
            faltan.append(L(canal.guild.id, "Leer historial de mensajes", "Read Message History"))
        if not perms.manage_messages:
            faltan.append(L(canal.guild.id, "Gestionar mensajes", "Manage Messages"))
        return faltan

    async def _avisar_sin_permisos(interaction: discord.Interaction, canal, faltan: list[str]) -> None:
        gid = interaction.guild_id
        lista = ", ".join(f"`{p}`" for p in faltan)
        texto = L(
            gid,
            f"No puedo limpiar {canal.mention}: me faltan permisos ({lista}). "
            f"Revisa el rol del bot y los permisos del canal.",
            f"I can't clean {canal.mention}: I'm missing permissions ({lista}). "
            f"Check the bot role and channel permissions.",
        )
        if interaction.response.is_done():
            await interaction.followup.send(texto, ephemeral=True)
        else:
            await interaction.response.send_message(texto, ephemeral=True)


    async def borrado_rapido(canal, corte, filtro, limite: int | None = None) -> int:
        """Borra por lotes mensajes más nuevos que `corte` que cumplan `filtro`.
        Recorre el historial completo. Si hay `limite`, borra solo los N más recientes."""
        objetivo = []
        async for m in canal.history(limit=None):
            if m.created_at <= corte:
                break
            if filtro(m):
                objetivo.append(m)
                if limite is not None and len(objetivo) >= limite:
                    break

        borrados = 0
        for i in range(0, len(objetivo), 100):
            lote = objetivo[i:i + 100]
            try:
                if len(lote) == 1:
                    await lote[0].delete()
                else:
                    await canal.delete_messages(lote)
                borrados += len(lote)
            except discord.NotFound:
                pass
            await asyncio.sleep(1)
        return borrados


    async def limpiar_canal(interaction: discord.Interaction, canal: discord.TextChannel,
                            preservar_link_video: bool = True):
        gid = interaction.guild_id
        corte = discord.utils.utcnow() - LIMITE_PURGE

        total_borrados = 0
        total_conservados = 0
        total_antiguos_borrados = 0

        async def avisar(texto: str):
            try:
                await interaction.followup.send(texto, ephemeral=True)
            except discord.HTTPException:
                try:
                    await canal.send(texto)
                except discord.HTTPException:
                    pass

        def filtro(m):
            nonlocal total_conservados
            if preservar_link_video and es_link_o_video(m):
                total_conservados += 1
                return False
            return True

        try:
            total_borrados = await borrado_rapido(canal, corte, filtro)
        except discord.HTTPException as e:
            await avisar(L(gid, f"Error durante el borrado por lotes: {e}", f"Bulk delete error: {e}"))

        resumen = L(gid, f"Fase rápida completa: {total_borrados} mensajes eliminados",
                    f"Fast phase done: {total_borrados} messages deleted")
        if preservar_link_video:
            resumen += L(gid, f" ({total_conservados} con link/video conservados)",
                         f" ({total_conservados} with link/video kept)")
        await avisar(resumen + ".\n" + L(
            gid, "Revisando mensajes de más de 14 días (uno por uno, puede tardar)...",
            "Checking messages older than 14 days (one by one, may take a while)..."))

        revisados = 0
        async for mensaje in canal.history(limit=None, before=corte):
            revisados += 1
            if preservar_link_video and es_link_o_video(mensaje):
                total_conservados += 1
                continue
            try:
                await mensaje.delete()
                total_antiguos_borrados += 1
            except discord.NotFound:
                pass
            except discord.Forbidden:
                pass
            except Exception:
                await asyncio.sleep(3)
                try:
                    await mensaje.delete()
                    total_antiguos_borrados += 1
                except Exception:
                    pass

            await asyncio.sleep(1.1)

            if revisados % 50 == 0:
                await avisar(L(
                    gid, f"Progreso: {revisados} mensajes antiguos revisados, {total_antiguos_borrados} eliminados...",
                    f"Progress: {revisados} old messages checked, {total_antiguos_borrados} deleted..."))

        total = total_borrados + total_antiguos_borrados
        final = L(gid, f"Limpieza completa.\nTotal eliminados: {total} ({total_borrados} recientes + {total_antiguos_borrados} antiguos).",
                  f"Cleanup complete.\nTotal deleted: {total} ({total_borrados} recent + {total_antiguos_borrados} old).")
        if preservar_link_video:
            final += L(gid, f"\nTotal conservados (link/video): {total_conservados}.",
                       f"\nTotal kept (link/video): {total_conservados}.")
        await avisar(final)


    async def borrar_mensajes_de_usuario(interaction: discord.Interaction, canal: discord.TextChannel,
                                         usuario_id: int, limite: int | None):
        gid = interaction.guild_id
        corte = discord.utils.utcnow() - LIMITE_PURGE
        total = 0

        async def avisar(texto: str):
            try:
                await interaction.followup.send(texto, ephemeral=True)
            except discord.HTTPException:
                try:
                    await canal.send(texto)
                except discord.HTTPException:
                    pass

        try:
            total = await borrado_rapido(canal, corte, lambda m: m.author.id == usuario_id, limite)
        except discord.HTTPException as e:
            await avisar(L(gid, f"Error durante el borrado por lotes: {e}", f"Bulk delete error: {e}"))

        if limite is not None and total >= limite:
            await avisar(L(gid, f"Eliminados {total} mensajes de <@{usuario_id}> en este canal.",
                           f"Deleted {total} messages from <@{usuario_id}> in this channel."))
            return

        if limite is not None:
            await avisar(L(
                gid, f"Eliminados {total} mensajes recientes de <@{usuario_id}> (no había suficientes en los "
                     f"últimos 14 días para llegar a {limite}; revisando más antiguos...)",
                f"Deleted {total} recent messages from <@{usuario_id}> (not enough in the last 14 days to "
                f"reach {limite}; checking older ones...)"))
        else:
            await avisar(L(
                gid, f"Fase rápida completa: {total} mensajes de <@{usuario_id}> eliminados.\n"
                     f"Revisando mensajes de más de 14 días (uno por uno, puede tardar)...",
                f"Fast phase done: {total} messages from <@{usuario_id}> deleted.\n"
                f"Checking messages older than 14 days (one by one, may take a while)..."))

        revisados = 0
        async for mensaje in canal.history(limit=None, before=corte):
            if limite is not None and total >= limite:
                break
            if mensaje.author.id != usuario_id:
                continue
            revisados += 1
            try:
                await mensaje.delete()
                total += 1
            except discord.NotFound:
                pass
            except discord.Forbidden:
                pass
            except Exception:
                await asyncio.sleep(3)
                try:
                    await mensaje.delete()
                    total += 1
                except Exception:
                    pass
            await asyncio.sleep(1.1)
            if revisados % 50 == 0:
                await avisar(L(gid, f"Progreso: {total} mensajes de <@{usuario_id}> eliminados...",
                               f"Progress: {total} messages from <@{usuario_id}> deleted..."))

        await avisar(L(gid, f"Limpieza de <@{usuario_id}> completa. Total eliminados: {total}.",
                       f"Cleanup of <@{usuario_id}> complete. Total deleted: {total}."))


    async def _ejecutar_limpieza(interaction, canal, coro_fn, nombre: str):
        SILENCIO_CANALES.add(canal.id)
        try:
            await coro_fn()
        except Exception as e:
            print(f"[{nombre}] Error inesperado durante la limpieza: {e}")
            try:
                await canal.send(L(interaction.guild_id, f"El borrado se detuvo por un error inesperado: {e}",
                                   f"The cleanup stopped due to an unexpected error: {e}"))
            except discord.HTTPException:
                pass
        finally:
            SILENCIO_CANALES.discard(canal.id)


    @bot.tree.command(name="clear", description="Elimina TODOS los mensajes del canal (conserva links y videos)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(interaction: discord.Interaction):
        gid = interaction.guild_id
        canal = interaction.channel
        if not isinstance(canal, discord.TextChannel):
            await interaction.response.send_message(
                L(gid, "Este comando solo funciona en un canal de texto.",
                  "This command only works in a text channel."), ephemeral=True)
            return
        me = interaction.guild.me if interaction.guild else None
        if me is None:
            return
        faltan = _permisos_limpieza(canal, me)
        if faltan:
            await _avisar_sin_permisos(interaction, canal, faltan)
            return
        if not await pedir_confirmacion(interaction, L(
                gid, f"Esto eliminará **todos** los mensajes de {canal.mention} excepto los que contengan links o "
                     f"videos. Los de más de 14 días se borran uno por uno y puede tardar. **No se puede deshacer.**",
                f"This will delete **all** messages in {canal.mention} except those with links or videos. "
                f"Messages older than 14 days are deleted one by one and may take a while. **This can't be undone.**")):
            return
        await _ejecutar_limpieza(interaction, canal, lambda: limpiar_canal(interaction, canal), "clear")


    @bot.tree.command(name="clearuser", description="Elimina mensajes de una persona específica en este canal")
    @app_commands.describe(
        usuario="Persona cuyos mensajes se eliminarán (mención o ID)",
        cantidad="Opcional: cuántos de sus mensajes más recientes borrar. Sin esto, borra todos.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearuser(interaction: discord.Interaction, usuario: discord.User,
                        cantidad: app_commands.Range[int, 1, 100] = None):
        gid = interaction.guild_id
        canal = interaction.channel
        if not isinstance(canal, discord.TextChannel):
            await interaction.response.send_message(
                L(gid, "Este comando solo funciona en un canal de texto.",
                  "This command only works in a text channel."), ephemeral=True)
            return
        me = interaction.guild.me if interaction.guild else None
        if me is None:
            return
        faltan = _permisos_limpieza(canal, me)
        if faltan:
            await _avisar_sin_permisos(interaction, canal, faltan)
            return
        if cantidad is not None:
            if not await pedir_confirmacion(interaction, L(
                    gid, f"Se borrarán hasta **{cantidad}** mensajes de {usuario.mention} en {canal.mention}. "
                         f"**No se puede deshacer.** ¿Continuar?",
                    f"Up to **{cantidad}** messages from {usuario.mention} in {canal.mention} will be deleted. "
                    f"**This can't be undone.** Continue?")):
                return
        else:
            if not await pedir_confirmacion(interaction, L(
                    gid, f"Esto eliminará **todos** los mensajes de {usuario.mention} en {canal.mention}. "
                         f"Los de más de 14 días se borran uno por uno y puede tardar. **No se puede deshacer.**",
                    f"This will delete **all** messages from {usuario.mention} in {canal.mention}. "
                    f"Messages older than 14 days are deleted one by one and may take a while. **This can't be undone.**")):
                return
        await _ejecutar_limpieza(
            interaction, canal, lambda: borrar_mensajes_de_usuario(interaction, canal, usuario.id, cantidad),
            "clearuser")


    @bot.tree.command(name="clearall", description="Elimina TODO el historial del canal, sin excepciones")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearall(interaction: discord.Interaction):
        gid = interaction.guild_id
        canal = interaction.channel
        if not isinstance(canal, discord.TextChannel):
            await interaction.response.send_message(
                L(gid, "Este comando solo funciona en un canal de texto.",
                  "This command only works in a text channel."), ephemeral=True)
            return
        me = interaction.guild.me if interaction.guild else None
        if me is None:
            return
        faltan = _permisos_limpieza(canal, me)
        if faltan:
            await _avisar_sin_permisos(interaction, canal, faltan)
            return
        if not await pedir_confirmacion(interaction, L(
                gid, f"⚠️ Esto eliminará **absolutamente todo** en {canal.mention}: texto, links, videos, fotos y "
                     f"adjuntos, de cualquier persona. Los de más de 14 días se borran uno por uno y puede tardar. "
                     f"**No se puede deshacer.**",
                f"⚠️ This will delete **absolutely everything** in {canal.mention}: text, links, videos, photos and "
                f"attachments, from anyone. Messages older than 14 days are deleted one by one and may take a while. "
                f"**This can't be undone.**")):
            return
        await _ejecutar_limpieza(
            interaction, canal, lambda: limpiar_canal(interaction, canal, preservar_link_video=False), "clearall")




