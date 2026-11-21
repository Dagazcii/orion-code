"""Moderación y lockdown"""
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
    # MODERACIÓN MANUAL
    # ============================================================
    def error_jerarquia(interaction: discord.Interaction, usuario_id: int,
                        miembro: discord.Member | None) -> str | None:
        g = interaction.guild
        gid = g.id
        if usuario_id == interaction.user.id:
            return L(gid, "No puedes aplicarte esto a ti mismo.", "You can't do this to yourself.")
        if usuario_id == g.owner_id:
            return L(gid, "No puedes actuar sobre el dueño del servidor.",
                     "You can't act on the server owner.")
        if usuario_id == bot.user.id:
            return L(gid, "No puedo aplicarme esto a mí mismo.", "I can't do this to myself.")
        if miembro is not None:
            if interaction.user.id != g.owner_id and miembro.top_role >= interaction.user.top_role:
                return L(gid, "Ese usuario tiene un rol igual o superior al tuyo.",
                         "That user has a role equal to or higher than yours.")
            if miembro.top_role >= g.me.top_role:
                return L(gid, "Ese usuario tiene un rol igual o superior al mío.",
                         "That user has a role equal to or higher than mine.")
        return None

    core.error_jerarquia = error_jerarquia


    def registrar_caso(guild: discord.Guild, tipo: str, target_id: int, mod_id: int, motivo: str) -> int:
        mc = cfg(guild.id).setdefault("mod_cases", {"counter": 0, "data": {}})
        mc["counter"] = int(mc.get("counter") or 0) + 1
        n = mc["counter"]
        mc.setdefault("data", {})[str(n)] = {
            "type": tipo,
            "target": target_id,
            "mod": mod_id,
            "reason": motivo,
            "ts": int(time.time()),
        }
        guardar_db()
        return n

    core.registrar_caso = registrar_caso


    @bot.tree.command(name="softban", description="Ban + unban inmediato (limpia mensajes)")
    @app_commands.describe(usuario="Usuario", motivo="Motivo", borrar_dias="Días de mensajes a borrar (1-7)")
    @app_commands.guild_only()
    @solo_perm("ban_members")
    async def softban(interaction: discord.Interaction, usuario: discord.User,
                      motivo: app_commands.Range[str, 1, 300] = "Sin motivo",
                      borrar_dias: app_commands.Range[int, 1, 7] = 1):
        g = interaction.guild
        gid = g.id
        err = error_jerarquia(interaction, usuario.id, g.get_member(usuario.id))
        if err:
            await responder(interaction, err, ephemeral=True)
            return
        if not await pedir_confirmacion(interaction, L(
                gid, f"¿Softban a {usuario.mention}? Motivo: {motivo}",
                f"Softban {usuario.mention}? Reason: {motivo}")):
            return
        try:
            await g.ban(usuario, reason=f"Softban {interaction.user} | {motivo}",
                        delete_message_seconds=borrar_dias * 86400)
            await g.unban(usuario, reason=f"Softban complete | {interaction.user}")
        except discord.HTTPException as e:
            await interaction.followup.send(L(gid, f"No pude softban: {e}", f"Could not softban: {e}"),
                                            ephemeral=True)
            return
        caso = registrar_caso(g, "softban", usuario.id, interaction.user.id, motivo)
        await interaction.followup.send(
            L(gid, f"<:ban:1560558020277174272> Softban a {usuario} · caso #{caso}",
              f"<:ban:1560558020277174272> Softban {usuario} · case #{caso}"),
            ephemeral=True)
        await registrar(g, f"<:ban:1560558020277174272> Softban #{caso}",
                        f"{usuario.mention} ({usuario.id})", discord.Color.red(),
                        [("Mod", interaction.user.mention), ("Motivo", motivo)])


    @bot.tree.command(name="tempban", description="Ban temporal (se desbanea solo)")
    @app_commands.describe(usuario="Usuario", horas="Horas de ban (1-720)", motivo="Motivo")
    @app_commands.guild_only()
    @solo_perm("ban_members")
    async def tempban(interaction: discord.Interaction, usuario: discord.User,
                      horas: app_commands.Range[int, 1, 720],
                      motivo: app_commands.Range[str, 1, 300] = "Sin motivo"):
        g = interaction.guild
        gid = g.id
        err = error_jerarquia(interaction, usuario.id, g.get_member(usuario.id))
        if err:
            await responder(interaction, err, ephemeral=True)
            return
        if not await pedir_confirmacion(interaction, L(
                gid, f"¿Ban temporal {horas}h a {usuario.mention}?",
                f"Tempban {horas}h for {usuario.mention}?")):
            return
        try:
            await g.ban(usuario, reason=f"Tempban {horas}h | {interaction.user} | {motivo}",
                        delete_message_seconds=0)
        except discord.HTTPException as e:
            await interaction.followup.send(L(gid, f"No pude banear: {e}", f"Could not ban: {e}"),
                                            ephemeral=True)
            return
        until = int(time.time()) + horas * 3600
        cfg(gid).setdefault("tempbans", {})[str(usuario.id)] = until
        caso = registrar_caso(g, "tempban", usuario.id, interaction.user.id, f"{motivo} ({horas}h)")
        guardar_db()
        await interaction.followup.send(
            L(gid, f"<:ban:1560558020277174272> Tempban {horas}h a {usuario} · caso #{caso}",
              f"<:ban:1560558020277174272> Tempban {horas}h {usuario} · case #{caso}"),
            ephemeral=True)
        await registrar(g, f"<:ban:1560558020277174272> Tempban #{caso}",
                        f"{usuario.mention} ({usuario.id})", discord.Color.red(),
                        [("Mod", interaction.user.mention), ("Motivo", motivo),
                         ("Hasta", f"<t:{until}:R>")])


    @bot.tree.command(name="case", description="Consulta un caso de moderación por número")
    @app_commands.describe(numero="Número del caso")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def case_cmd(interaction: discord.Interaction, numero: app_commands.Range[int, 1, 999999]):
        gid = interaction.guild_id
        data = cfg(gid).get("mod_cases", {}).get("data", {}).get(str(numero))
        if not data:
            await responder(interaction, L(gid, "Caso no encontrado.", "Case not found."), ephemeral=True)
            return
        embed = discord.Embed(
            title=L(gid, f"Caso #{numero}", f"Case #{numero}"),
            color=discord.Color.orange(),
        )
        embed.add_field(name="Tipo", value=data.get("type", "—"))
        embed.add_field(name="Usuario", value=f"<@{data.get('target')}>")
        embed.add_field(name="Mod", value=f"<@{data.get('mod')}>")
        embed.add_field(name=L(gid, "Motivo", "Reason"), value=data.get("reason", "—")[:500], inline=False)
        if data.get("ts"):
            embed.add_field(name="Fecha", value=f"<t:{data['ts']}:f>")
        await responder(interaction, embed=embed, ephemeral=True)


    @bot.tree.command(name="ban", description="Banea a un usuario del servidor")
    @app_commands.describe(usuario="Usuario a banear", motivo="Motivo del baneo",
                           borrar_dias="Días de mensajes a borrar (0-7)")
    @app_commands.guild_only()
    @solo_perm("ban_members")
    async def ban(interaction: discord.Interaction, usuario: discord.User,
                  motivo: app_commands.Range[str, 1, 300] = "Sin motivo",
                  borrar_dias: app_commands.Range[int, 0, 7] = 0):
        g = interaction.guild
        gid = g.id
        err = error_jerarquia(interaction, usuario.id, g.get_member(usuario.id))
        if err:
            await responder(interaction, err, ephemeral=True)
            return
        if not await pedir_confirmacion(interaction, L(
                gid, f"¿Banear a {usuario.mention}? Motivo: {motivo}",
                f"Ban {usuario.mention}? Reason: {motivo}")):
            return
        try:
            await g.ban(usuario, reason=f"{interaction.user} | {motivo}",
                        delete_message_seconds=borrar_dias * 86400)
        except discord.HTTPException as e:
            await interaction.followup.send(L(gid, f"No pude banear: {e}", f"Could not ban: {e}"),
                                            ephemeral=True)
            return
        await interaction.followup.send(L(gid, f"<:ban:1560558020277174272> {usuario} baneado.", f"<:ban:1560558020277174272> {usuario} banned."),
                                        ephemeral=True)
        caso = registrar_caso(g, "ban", usuario.id, interaction.user.id, motivo)
        await registrar(g, f"<:ban:1560558020277174272> Ban #{caso}", f"{usuario.mention} ({usuario.id})", discord.Color.red(),
                        [("Mod", interaction.user.mention), ("Motivo / Reason", motivo), ("Caso", f"#{caso}")])


    @bot.tree.command(name="unban", description="Quita el ban a un usuario por ID")
    @app_commands.describe(usuario_id="ID del usuario baneado", motivo="Motivo")
    @app_commands.guild_only()
    @solo_perm("ban_members")
    async def unban(interaction: discord.Interaction, usuario_id: str,
                    motivo: app_commands.Range[str, 1, 300] = "Sin motivo"):
        gid = interaction.guild_id
        try:
            uid = int(usuario_id.strip())
        except ValueError:
            await responder(interaction, L(gid, "ID inválido.", "Invalid ID."), ephemeral=True)
            return
        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"{interaction.user} | {motivo}")
        except discord.NotFound:
            await responder(interaction, L(gid, "Ese usuario no está baneado.",
                                           "That user is not banned."), ephemeral=True)
            return
        except discord.HTTPException as e:
            await responder(interaction, f"Error: {e}", ephemeral=True)
            return
        await responder(interaction, L(gid, f"<:ban:1560558020277174272> <@{uid}> desbaneado.", f"<:ban:1560558020277174272> <@{uid}> unbanned."),
                        ephemeral=True)
        await registrar(interaction.guild, "♻️ Unban", f"<@{uid}> ({uid})", discord.Color.green(),
                        [("Mod", interaction.user.mention), ("Motivo / Reason", motivo)])


    @bot.tree.command(name="kick", description="Expulsa a un miembro del servidor")
    @app_commands.describe(usuario="Miembro a expulsar", motivo="Motivo")
    @app_commands.guild_only()
    @solo_perm("kick_members")
    async def kick(interaction: discord.Interaction, usuario: discord.Member,
                   motivo: app_commands.Range[str, 1, 300] = "Sin motivo"):
        gid = interaction.guild_id
        err = error_jerarquia(interaction, usuario.id, usuario)
        if err:
            await responder(interaction, err, ephemeral=True)
            return
        if not await pedir_confirmacion(interaction, L(
                gid, f"¿Expulsar a {usuario.mention}? Motivo: {motivo}",
                f"Kick {usuario.mention}? Reason: {motivo}")):
            return
        try:
            await usuario.kick(reason=f"{interaction.user} | {motivo}")
        except discord.HTTPException as e:
            await interaction.followup.send(L(gid, f"No pude expulsar: {e}", f"Could not kick: {e}"),
                                            ephemeral=True)
            return
        await interaction.followup.send(L(gid, f"<:aceptado:1560557801464668240> {usuario} expulsado.", f"<:aceptado:1560557801464668240> {usuario} kicked."),
                                        ephemeral=True)
        await registrar(interaction.guild, "👢 Kick", f"{usuario.mention} ({usuario.id})",
                        discord.Color.orange(),
                        [("Mod", interaction.user.mention), ("Motivo / Reason", motivo)])


    @bot.tree.command(name="mute", description="Silencia (timeout) a un miembro")
    @app_commands.describe(usuario="Miembro a silenciar", minutos="Duración en minutos (1-40320)",
                           motivo="Motivo")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def mute(interaction: discord.Interaction, usuario: discord.Member,
                   minutos: app_commands.Range[int, 1, 40320] = 10,
                   motivo: app_commands.Range[str, 1, 300] = "Sin motivo"):
        gid = interaction.guild_id
        err = error_jerarquia(interaction, usuario.id, usuario)
        if err:
            await responder(interaction, err, ephemeral=True)
            return
        try:
            await usuario.timeout(timedelta(minutes=minutos), reason=f"{interaction.user} | {motivo}")
        except discord.HTTPException as e:
            await responder(interaction, L(gid, f"No pude silenciar: {e}", f"Could not mute: {e}"),
                            ephemeral=True)
            return
        await responder(interaction, L(gid, f"🔇 {usuario.mention} silenciado {minutos} min.",
                                       f"🔇 {usuario.mention} muted for {minutos} min."), ephemeral=True)
        await registrar(interaction.guild, "🔇 Mute", f"{usuario.mention} ({usuario.id})",
                        discord.Color.orange(),
                        [("Mod", interaction.user.mention), ("Duración / Duration", f"{minutos} min"),
                         ("Motivo / Reason", motivo)])


    @bot.tree.command(name="unmute", description="Quita el silencio a un miembro")
    @app_commands.describe(usuario="Miembro a des-silenciar")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def unmute(interaction: discord.Interaction, usuario: discord.Member):
        gid = interaction.guild_id
        try:
            await usuario.timeout(None, reason=f"{interaction.user}")
        except discord.HTTPException as e:
            await responder(interaction, f"Error: {e}", ephemeral=True)
            return
        await responder(interaction, L(gid, f"🔊 {usuario.mention} ya puede hablar.",
                                       f"🔊 {usuario.mention} can talk again."), ephemeral=True)
        await registrar(interaction.guild, "🔊 Unmute", f"{usuario.mention} ({usuario.id})",
                        discord.Color.green(), [("Mod", interaction.user.mention)])


    @bot.tree.command(name="lock", description="Bloquea un canal (nadie puede escribir)")
    @app_commands.describe(canal="Canal a bloquear (por defecto, el actual)")
    @app_commands.guild_only()
    @solo_perm("manage_channels")
    async def lock(interaction: discord.Interaction, canal: discord.TextChannel | None = None):
        gid = interaction.guild_id
        canal = canal or interaction.channel
        if not isinstance(canal, discord.TextChannel):
            await responder(interaction, L(gid, "Solo funciona en canales de texto.",
                                           "Only works on text channels."), ephemeral=True)
            return
        ow = canal.overwrites_for(interaction.guild.default_role)
        ow.send_messages = False
        try:
            await canal.set_permissions(interaction.guild.default_role, overwrite=ow,
                                        reason=f"/lock por {interaction.user}")
        except discord.HTTPException as e:
            await responder(interaction, f"Error: {e}", ephemeral=True)
            return
        await responder(interaction, L(gid, f"🔒 {canal.mention} bloqueado.",
                                       f"🔒 {canal.mention} locked."), ephemeral=True)
        await registrar(interaction.guild, "🔒 Lock", canal.mention, discord.Color.orange(),
                        [("Mod", interaction.user.mention)])


    @bot.tree.command(name="unlock", description="Desbloquea un canal")
    @app_commands.describe(canal="Canal a desbloquear (por defecto, el actual)")
    @app_commands.guild_only()
    @solo_perm("manage_channels")
    async def unlock(interaction: discord.Interaction, canal: discord.TextChannel | None = None):
        gid = interaction.guild_id
        canal = canal or interaction.channel
        if not isinstance(canal, discord.TextChannel):
            await responder(interaction, L(gid, "Solo funciona en canales de texto.",
                                           "Only works on text channels."), ephemeral=True)
            return
        ow = canal.overwrites_for(interaction.guild.default_role)
        ow.send_messages = None
        try:
            await canal.set_permissions(
                interaction.guild.default_role,
                overwrite=None if ow.is_empty() else ow,
                reason=f"/unlock por {interaction.user}",
            )
        except discord.HTTPException as e:
            await responder(interaction, f"Error: {e}", ephemeral=True)
            return
        await responder(interaction, L(gid, f"🔓 {canal.mention} desbloqueado.",
                                       f"🔓 {canal.mention} unlocked."), ephemeral=True)
        await registrar(interaction.guild, "🔓 Unlock", canal.mention, discord.Color.green(),
                        [("Mod", interaction.user.mention)])


    @bot.tree.command(name="purge", description="Borra hasta 500 mensajes recientes (menos de 14 días)")
    @app_commands.describe(cantidad="Cantidad de mensajes a borrar (1-500)",
                           usuario="Opcional: borrar solo los de este usuario")
    @app_commands.guild_only()
    @solo_perm("manage_messages")
    async def purge_cmd(interaction: discord.Interaction, cantidad: app_commands.Range[int, 1, 500],
                        usuario: discord.User | None = None):
        gid = interaction.guild_id
        canal = interaction.channel
        texto = L(gid, f"Se borrarán hasta **{cantidad}** mensajes en {canal.mention}"
                       + (f" de {usuario.mention}" if usuario else "")
                       + ". Los fijados y los de más de 14 días no se tocan. ¿Continuar?",
                  f"Up to **{cantidad}** messages will be deleted in {canal.mention}"
                  + (f" from {usuario.mention}" if usuario else "")
                  + ". Pinned and 14+ day old messages are skipped. Continue?")
        if not await pedir_confirmacion(interaction, texto):
            return

        # Igual que /clear: estos borrados no se replican uno por uno en el canal de logs.
        SILENCIO_CANALES.add(canal.id)
        borrados = 0
        try:
            corte = discord.utils.utcnow() - LIMITE_PURGE
            objetivo = []
            try:
                async for m in canal.history(limit=10000):
                    if m.created_at <= corte:
                        break
                    if m.pinned:
                        continue
                    if usuario and m.author.id != usuario.id:
                        continue
                    objetivo.append(m)
                    if len(objetivo) >= cantidad:
                        break

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
            except discord.HTTPException as e:
                await interaction.followup.send(L(gid, f"Error al borrar: {e}", f"Delete error: {e}"),
                                                ephemeral=True)
                return

            await interaction.followup.send(
                L(gid, f"🧹 {borrados} mensajes eliminados.", f"🧹 {borrados} messages deleted."),
                ephemeral=True)
            await registrar(interaction.guild, "🧹 Purge", f"{borrados} → {canal.mention}",
                            discord.Color.orange(), [("Mod", interaction.user.mention)])
        finally:
            SILENCIO_CANALES.discard(canal.id)


    # ============================================================
    # LOCKDOWN (anti-raid)
    # ============================================================
    def _canales_lockdown(guild: discord.Guild) -> list:
        """Texto y foros. El cierre de hilos va en el overwrite del canal padre."""
        vistos: set[int] = set()
        salida = []
        for ch in list(guild.text_channels) + list(getattr(guild, "forums", [])):
            if ch.id in vistos:
                continue
            vistos.add(ch.id)
            salida.append(ch)
        return salida


    def _estado_escritura(ow: discord.PermissionOverwrite) -> dict:
        return {
            "send_messages": ow.send_messages,
            "send_messages_in_threads": ow.send_messages_in_threads,
        }


    def _ya_cerrado(estado: dict) -> bool:
        return estado.get("send_messages") is False and estado.get("send_messages_in_threads") is False


    def _cerrar_escritura(ow: discord.PermissionOverwrite):
        ow.send_messages = False
        ow.send_messages_in_threads = False


    def _restaurar_escritura(ow: discord.PermissionOverwrite, valor):
        """Formato nuevo: dict con los dos permisos. Formato viejo: solo send_messages."""
        if isinstance(valor, dict):
            ow.send_messages = valor.get("send_messages")
            ow.send_messages_in_threads = valor.get("send_messages_in_threads")
        else:
            ow.send_messages = valor


    async def activar_lockdown(guild: discord.Guild, minutos: int, motivo: str) -> bool:
        c = cfg(guild.id)
        ld = c["lockdown"]
        if ld["active"]:
            return False
        # Se marca y se guarda YA. Si el proceso muere a mitad, /lockdown off (o el
        # temporizador al reiniciar) puede devolver cada canal a como estaba.
        ld["active"] = True
        ld["prev"] = {}
        ld["until"] = time.time() + minutos * 60
        guardar_db()
        for ch in _canales_lockdown(guild):
            ow = ch.overwrites_for(guild.default_role)
            estado = _estado_escritura(ow)
            if _ya_cerrado(estado):
                continue  # ya estaba cerrado del todo: no se toca al restaurar
            ld["prev"][str(ch.id)] = estado
            guardar_db()
            _cerrar_escritura(ow)
            try:
                await ch.set_permissions(guild.default_role, overwrite=ow, reason=f"Lockdown: {motivo}")
            except discord.HTTPException:
                ld["prev"].pop(str(ch.id), None)
                guardar_db()
            await asyncio.sleep(0.3)
        programar_levantamiento(guild.id, max(0, ld["until"] - time.time()))
        return True


    def programar_levantamiento(guild_id: int, segundos: float):
        viejo = LOCK_TASKS.pop(guild_id, None)
        if viejo and not viejo.done():
            viejo.cancel()
        LOCK_TASKS[guild_id] = asyncio.create_task(_esperar_y_levantar(guild_id, segundos))


    async def _esperar_y_levantar(guild_id: int, segundos: float):
        await asyncio.sleep(max(0, segundos))
        g = bot.get_guild(guild_id)
        if g:
            await levantar_lockdown(g, "automático / automatic")


    async def levantar_lockdown(guild: discord.Guild, motivo: str) -> bool:
        c = cfg(guild.id)
        ld = c["lockdown"]
        if not ld["active"]:
            return False
        tarea = LOCK_TASKS.pop(guild.id, None)
        if tarea and tarea is not asyncio.current_task() and not tarea.done():
            tarea.cancel()
        for cid, valor in list(ld["prev"].items()):
            ch = guild.get_channel(int(cid))
            if ch is None:
                continue
            ow = ch.overwrites_for(guild.default_role)
            _restaurar_escritura(ow, valor)
            try:
                await ch.set_permissions(guild.default_role,
                                         overwrite=None if ow.is_empty() else ow,
                                         reason=f"Fin lockdown: {motivo}")
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.3)
        ld["active"] = False
        ld["prev"] = {}
        ld["until"] = 0
        guardar_db()
        await registrar(guild, L(guild.id, "<:aceptado:1560557801464668240> Lockdown terminado", "<:aceptado:1560557801464668240> Lockdown ended"), motivo,
                        discord.Color.green())
        return True


    @bot.tree.command(name="lockdown", description="Activa o desactiva el bloqueo total de canales")
    @app_commands.describe(accion="Activar o desactivar", minutos="Duración al activar (1-1440)")
    @app_commands.choices(accion=[
        app_commands.Choice(name="activar / on", value="on"),
        app_commands.Choice(name="desactivar / off", value="off"),
    ])
    @app_commands.guild_only()
    @solo_perm("manage_channels")
    async def lockdown_cmd(interaction: discord.Interaction, accion: app_commands.Choice[str],
                           minutos: app_commands.Range[int, 1, 1440] = 10):
        gid = interaction.guild_id
        if accion.value == "on":
            if not await pedir_confirmacion(interaction, L(
                    gid,
                    f"⚠️ Vas a **bloquear casi todos los canales** del servidor durante **{minutos} min**. "
                    f"Solo staff podrá escribir. **¿Continuar?**",
                    f"⚠️ You are about to **lock almost all channels** for **{minutos} min**. "
                    f"Only staff will be able to write. **Continue?**")):
                return
            ok = await activar_lockdown(interaction.guild, minutos, f"Manual: {interaction.user}")
            if ok:
                await interaction.followup.send(L(gid, f"🚨 Lockdown activo por {minutos} min.",
                                                  f"🚨 Lockdown active for {minutos} min."))
                await registrar(interaction.guild, "🚨 Lockdown",
                                f"{interaction.user.mention} · {minutos} min", discord.Color.red())
            else:
                await interaction.followup.send(L(gid, "Ya hay un lockdown activo.",
                                                  "A lockdown is already active."))
        else:
            if not await pedir_confirmacion(interaction, L(
                    gid, "¿Desactivar el lockdown y restaurar permisos de los canales?",
                    "Disable lockdown and restore channel permissions?")):
                return
            ok = await levantar_lockdown(interaction.guild, f"Manual: {interaction.user}")
            await interaction.followup.send(
                L(gid, "<:aceptado:1560557801464668240> Lockdown desactivado.",
                  "<:aceptado:1560557801464668240> Lockdown disabled.") if ok
                else L(gid, "No hay lockdown activo.", "No active lockdown."))




    core.programar_levantamiento = programar_levantamiento
    core.activar_lockdown = activar_lockdown
    core.levantar_lockdown = levantar_lockdown

    @tasks.loop(minutes=10)
    async def tarea_tempbans():
        ahora = int(time.time())
        for gid_s, gdata in list(DB.get("guilds", {}).items()):
            tb = gdata.get("tempbans") or {}
            if not tb:
                continue
            guild = core.bot.get_guild(int(gid_s))
            if guild is None:
                continue
            for uid, until in list(tb.items()):
                if int(until) > ahora:
                    continue
                try:
                    await guild.unban(discord.Object(id=int(uid)), reason="AegisBot: fin tempban")
                    await registrar(guild, "🔓 Tempban terminado", f"<@{uid}>", discord.Color.green())
                except discord.HTTPException:
                    pass
                tb.pop(uid, None)
            guardar_db()

    if not tarea_tempbans.is_running():
        tarea_tempbans.start()
