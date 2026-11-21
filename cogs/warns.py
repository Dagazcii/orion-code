"""Warns e info"""
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
    def error_jerarquia(interaction, usuario_id, miembro):
        fn = getattr(core, "error_jerarquia", None)
        if fn:
            return fn(interaction, usuario_id, miembro)
        return None

    # ============================================================
    # WARNS, INFO Y CONFIG EXTRA
    # ============================================================

    @bot.tree.command(name="warn", description="Advierte a un miembro (strikes con sanción automática)")
    @app_commands.describe(usuario="Miembro a advertir", motivo="Motivo")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def warn(interaction: discord.Interaction, usuario: discord.Member,
                   motivo: app_commands.Range[str, 1, 300]):
        gid = interaction.guild_id
        err = error_jerarquia(interaction, usuario.id, usuario)
        if err:
            await responder(interaction, err, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        c = cfg(gid)
        lista = c["warn_data"].setdefault(str(usuario.id), [])
        lista.append({"reason": motivo, "mod": interaction.user.id, "ts": int(time.time())})
        n = len(lista)
        w = c["warns"]
        sancion = ""
        if w["action"] != "none" and n >= w["threshold"]:
            try:
                if w["action"] == "kick":
                    await usuario.kick(reason=f"AegisBot: {n} warns")
                    sancion = L(gid, "expulsado", "kicked")
                else:
                    await usuario.timeout(timedelta(minutes=w["minutes"]), reason=f"AegisBot: {n} warns")
                    sancion = L(gid, f"silenciado {w['minutes']} min", f"muted {w['minutes']} min")
                lista.clear()
            except discord.HTTPException:
                sancion = L(gid, "no pude sancionar (faltan permisos)", "could not punish (missing permissions)")
        guardar_db()
        try:
            await usuario.send(L(gid, f"Recibiste un warn en **{interaction.guild.name}**: {motivo}",
                                 f"You received a warning in **{interaction.guild.name}**: {motivo}"))
        except Exception:
            pass
        texto = L(gid, f"⚠️ {usuario.mention} advertido ({n}/{w['threshold']}).",
                  f"⚠️ {usuario.mention} warned ({n}/{w['threshold']}).")
        if sancion:
            texto += f" → {sancion}"
        await interaction.followup.send(texto, ephemeral=True)
        caso = None
        if core.registrar_caso:
            caso = core.registrar_caso(interaction.guild, "warn", usuario.id, interaction.user.id, motivo)
        campos = [("Mod", interaction.user.mention), ("Motivo / Reason", motivo),
                  ("Total", f"{n}/{w['threshold']}" + (f" → {sancion}" if sancion else ""))]
        if caso:
            campos.append(("Caso", f"#{caso}"))
        await registrar(interaction.guild, f"⚠️ Warn" + (f" #{caso}" if caso else ""),
                        f"{usuario.mention} ({usuario.id})", discord.Color.orange(), campos)


    @bot.tree.command(name="warns", description="Muestra los warns de un miembro")
    @app_commands.describe(usuario="Miembro a consultar")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def warns(interaction: discord.Interaction, usuario: discord.User):
        gid = interaction.guild_id
        lista = cfg(gid)["warn_data"].get(str(usuario.id), [])
        if not lista:
            await responder(interaction, L(gid, "Sin warns.", "No warns."), ephemeral=True)
            return
        lineas = [f"**{i}.** <t:{w['ts']}:d> · <@{w['mod']}> · {w['reason']}" for i, w in enumerate(lista, 1)]
        embed = discord.Embed(title=f"⚠️ Warns · {usuario}", description="\n".join(lineas)[:4000],
                              color=discord.Color.orange())
        await responder(interaction, embed=embed, ephemeral=True)


    @bot.tree.command(name="unwarn", description="Quita un warn específico a un usuario")
    @app_commands.describe(usuario="Usuario", numero="Número del warn (ver /warns)")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def unwarn(interaction: discord.Interaction, usuario: discord.User, numero: app_commands.Range[int, 1, 100]):
        gid = interaction.guild_id
        lista = cfg(gid)["warn_data"].get(str(usuario.id), [])
        if numero > len(lista):
            await responder(interaction, L(gid, "Ese warn no existe.", "That warn doesn't exist."), ephemeral=True)
            return
        lista.pop(numero - 1)
        guardar_db()
        await responder(interaction, L(gid, f"<:aceptado:1560557801464668240> Warn #{numero} eliminado.", f"<:aceptado:1560557801464668240> Warn #{numero} removed."),
                        ephemeral=True)


    @bot.tree.command(name="clearwarns", description="Borra todos los warns de un usuario")
    @app_commands.describe(usuario="Usuario")
    @app_commands.guild_only()
    @solo_perm("moderate_members")
    async def clearwarns(interaction: discord.Interaction, usuario: discord.User):
        gid = interaction.guild_id
        cfg(gid)["warn_data"].pop(str(usuario.id), None)
        guardar_db()
        await responder(interaction, L(gid, "<:aceptado:1560557801464668240> Warns borrados.", "<:aceptado:1560557801464668240> Warns cleared."), ephemeral=True)


    @bot.tree.command(name="userinfo", description="Información de un miembro")
    @app_commands.describe(usuario="Miembro (por defecto, tú)")
    @app_commands.guild_only()
    @solo_mod()
    async def userinfo(interaction: discord.Interaction, usuario: discord.Member | None = None):
        gid = interaction.guild_id
        m = usuario or interaction.user
        roles = [r.mention for r in reversed(m.roles) if r != interaction.guild.default_role]
        embed = discord.Embed(title=str(m), color=m.color if m.color.value else discord.Color.blurple())
        embed.set_thumbnail(url=m.display_avatar.url)
        embed.add_field(name="ID", value=str(m.id))
        embed.add_field(name=L(gid, "Cuenta creada", "Account created"), value=f"<t:{int(m.created_at.timestamp())}:R>")
        if m.joined_at:
            embed.add_field(name=L(gid, "Se unió", "Joined"), value=f"<t:{int(m.joined_at.timestamp())}:R>")
        embed.add_field(name="Roles", value=(" ".join(roles[:15]) or "—")[:1000], inline=False)
        embed.add_field(name="Warns", value=str(len(cfg(gid)["warn_data"].get(str(m.id), []))))
        embed.add_field(name=L(gid, "Reportes en la red", "Network reports"), value=str(len(core.reportes_aprobados(m.id))))
        await responder(interaction, embed=embed, ephemeral=True)


    @bot.tree.command(name="slowmode", description="Cambia el modo lento de un canal")
    @app_commands.describe(segundos="0 para quitarlo (máx. 21600)", canal="Canal (por defecto, el actual)")
    @app_commands.guild_only()
    @solo_perm("manage_channels")
    async def slowmode(interaction: discord.Interaction, segundos: app_commands.Range[int, 0, 21600],
                       canal: discord.TextChannel | None = None):
        gid = interaction.guild_id
        canal = canal or interaction.channel
        if not isinstance(canal, discord.TextChannel):
            await responder(interaction, L(gid, "Solo funciona en canales de texto.",
                                           "Only works on text channels."), ephemeral=True)
            return
        try:
            await canal.edit(slowmode_delay=segundos, reason=f"/slowmode por {interaction.user}")
        except discord.HTTPException as e:
            await responder(interaction, f"Error: {e}", ephemeral=True)
            return
        await responder(interaction, L(gid, f"🐢 Modo lento de {canal.mention}: {segundos}s.",
                                       f"🐢 Slowmode in {canal.mention}: {segundos}s."), ephemeral=True)


    # --- configuración extra ---
    @config.command(name="warns", description="Configura la sanción automática por acumulación de warns")
    @app_commands.describe(umbral="Warns necesarios para sancionar (1-20)", accion="Sanción",
                           minutos="Duración del mute (1-40320)")
    @app_commands.choices(accion=[
        app_commands.Choice(name="mute", value="mute"),
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="ninguna / none", value="none"),
    ])
    @solo_admin()
    async def cfg_warns(interaction: discord.Interaction, umbral: app_commands.Range[int, 1, 20] | None = None,
                        accion: app_commands.Choice[str] | None = None,
                        minutos: app_commands.Range[int, 1, 40320] | None = None):
        gid = interaction.guild_id
        w = cfg(gid)["warns"]
        if umbral is not None:
            w["threshold"] = umbral
        if accion is not None:
            w["action"] = accion.value
        if minutos is not None:
            w["minutes"] = minutos
        guardar_db()
        await interaction.response.send_message(L(gid, "<:aceptado:1560557801464668240> Warns actualizado.", "<:aceptado:1560557801464668240> Warns updated."), ephemeral=True)




    @config.command(name="autorole", description="Rol que se da automáticamente a quien entra")
    @app_commands.describe(rol="Rol a asignar", quitar="Desactivar el autorol")
    @solo_admin()
    async def cfg_autorole(interaction: discord.Interaction, rol: discord.Role | None = None, quitar: bool = False):
        gid = interaction.guild_id
        c = cfg(gid)
        if quitar:
            c["autorole"] = None
        elif rol is not None:
            if rol >= interaction.guild.me.top_role or rol.is_default() or rol.managed:
                await interaction.response.send_message(L(
                    gid, "No puedo asignar ese rol (está por encima del mío o es de sistema).",
                    "I can't assign that role (above mine or managed)."), ephemeral=True)
                return
            c["autorole"] = rol.id
        guardar_db()
        await interaction.response.send_message(L(gid, "<:aceptado:1560557801464668240> Autorol actualizado.", "<:aceptado:1560557801464668240> Autorole updated."),
                                                ephemeral=True)


    @config.command(name="auditroles", description="Roles autorizados a ver canales privados (para /audit)")
    @app_commands.choices(accion=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ])
    @solo_admin()
    async def cfg_auditroles(interaction: discord.Interaction, accion: app_commands.Choice[str],
                             rol: discord.Role | None = None):
        gid = interaction.guild_id
        c = cfg(gid)
        if accion.value == "list":
            txt = " ".join(f"<@&{r}>" for r in sorted(core.roles_permitidos(interaction.guild))) or "—"
            await interaction.response.send_message(txt, ephemeral=True)
            return
        if rol is None:
            await interaction.response.send_message(L(gid, "Indica un rol.", "Provide a role."), ephemeral=True)
            return
        if accion.value == "add":
            if rol.id not in c["audit_roles"]:
                c["audit_roles"].append(rol.id)
        elif rol.id in c["audit_roles"]:
            c["audit_roles"].remove(rol.id)
        guardar_db()
        await interaction.response.send_message(L(gid, "<:aceptado:1560557801464668240> Roles de /audit actualizados.",
                                                  "<:aceptado:1560557801464668240> /audit roles updated."), ephemeral=True)
