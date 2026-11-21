"""Logs y backup"""
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
    PanelView, _si_no,
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
    # LOGS Y BACKUPS
    # ============================================================

    def _logs_on(gid: int, key: str) -> bool:
        """Todos los tipos de log vienen desactivados por defecto."""
        return bool(cfg(gid).get("logs", {}).get(key, False))

    @bot.listen("on_raw_message_delete")
    async def log_borrado(payload: discord.RawMessageDeleteEvent):
        if era_ignorado(payload.message_id):
            return
        if payload.guild_id is None or payload.channel_id in SILENCIO_CANALES:
            return
        msg = payload.cached_message
        if msg is None or msg.author.bot:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None or not _logs_on(guild.id, "messages"):
            return
        gid = guild.id
        extras = [a.filename for a in msg.attachments]
        campos = [(L(gid, "Canal", "Channel"), f"<#{payload.channel_id}>"),
                  (L(gid, "Contenido", "Content"), discord.utils.escape_markdown(msg.content)[:1000] or "—")]
        if extras:
            campos.append((L(gid, "Adjuntos", "Attachments"), ", ".join(extras)))
        await registrar(guild, L(gid, "🗑️ Mensaje borrado", "🗑️ Message deleted"),
                        f"{msg.author.mention} ({msg.author.id})", discord.Color.dark_grey(), campos)


    @bot.listen("on_message_edit")
    async def log_edicion(antes: discord.Message, despues: discord.Message):
        if despues.guild is None or despues.author.bot or antes.content == despues.content:
            return
        gid = despues.guild.id
        if not _logs_on(gid, "messages"):
            return
        await registrar(despues.guild, L(gid, "✏️ Mensaje editado", "✏️ Message edited"),
                        f"{despues.author.mention} · {despues.jump_url}", discord.Color.light_grey(),
                        [(L(gid, "Antes", "Before"), discord.utils.escape_markdown(antes.content)[:1000] or "—"),
                         (L(gid, "Después", "After"), discord.utils.escape_markdown(despues.content)[:1000] or "—")])


    @bot.listen("on_member_remove")
    async def log_salida(member: discord.Member):
        gid = member.guild.id
        if not _logs_on(gid, "members"):
            return
        roles = " ".join(r.mention for r in member.roles if not r.is_default())[:900] or "—"
        await registrar(member.guild, L(gid, "📤 Salió un miembro", "📤 Member left"),
                        f"{member.mention} ({member.id})", discord.Color.dark_red(), [("Roles", roles)])


    @tasks.loop(hours=6)
    async def tarea_backup():
        try:
            await asyncio.to_thread(hacer_backup)
        except Exception as e:
            print(f"[backup] {e}")

    @tasks.loop(hours=12)
    async def tarea_limpieza_db():
        try:
            await core.limpiar_datos_muertos(bot)
        except Exception as e:
            print(f"[limpieza-db] {e}")



    @bot.listen("on_guild_role_create")
    async def log_role_create(role: discord.Role):
        gid = role.guild.id
        if not _logs_on(gid, "roles"):
            return
        await registrar(role.guild, L(gid, "🎭 Rol creado", "🎭 Role created"),
                        f"{role.mention} (`{role.id}`)", discord.Color.green())

    @bot.listen("on_guild_role_delete")
    async def log_role_delete(role: discord.Role):
        gid = role.guild.id
        if not _logs_on(gid, "roles"):
            return
        await registrar(role.guild, L(gid, "🎭 Rol borrado", "🎭 Role deleted"),
                        f"**{role.name}** (`{role.id}`)", discord.Color.dark_red())

    @bot.listen("on_guild_channel_create")
    async def log_channel_create(channel: discord.abc.GuildChannel):
        gid = channel.guild.id
        if not _logs_on(gid, "channels"):
            return
        await registrar(channel.guild, L(gid, "📁 Canal creado", "📁 Channel created"),
                        f"{channel.mention} (`{channel.id}`)", discord.Color.green())

    @bot.listen("on_guild_channel_delete")
    async def log_channel_delete(channel: discord.abc.GuildChannel):
        gid = channel.guild.id
        if not _logs_on(gid, "channels"):
            return
        await registrar(channel.guild, L(gid, "📁 Canal borrado", "📁 Channel deleted"),
                        f"**{channel.name}** (`{channel.id}`)", discord.Color.dark_red())


    if not tarea_backup.is_running():
        tarea_backup.start()
    if not tarea_limpieza_db.is_running():
        tarea_limpieza_db.start()

    def _embed_logs(gid: int) -> discord.Embed:
        c = cfg(gid)
        lg = c.setdefault("logs", {})
        for k in ("messages", "members", "roles", "channels", "mod"):
            lg.setdefault(k, False)
        ch = f"<#{c['log_channel']}>" if c.get("log_channel") else L(gid, "(sin canal)", "(no channel)")
        e = discord.Embed(
            title=L(gid, "📜 Logs", "📜 Logs"),
            color=discord.Color.dark_grey(),
        )
        e.add_field(name=L(gid, "Canal", "Channel"), value=ch, inline=False)
        e.add_field(name=L(gid, "Mensajes", "Messages"), value=_si_no(lg.get("messages")))
        e.add_field(name=L(gid, "Miembros", "Members"), value=_si_no(lg.get("members")))
        e.add_field(name=L(gid, "Roles", "Roles"), value=_si_no(lg.get("roles")))
        e.add_field(name=L(gid, "Canales", "Channels"), value=_si_no(lg.get("channels")))
        e.add_field(name=L(gid, "Moderación", "Moderation"), value=_si_no(lg.get("mod")))
        e.set_footer(text=L(
            gid,
            "Por defecto todo viene desactivado. Elige canal y activa lo que necesites "
            "(botones individuales o Activar/Desactivar todo).",
            "Everything is off by default. Pick a channel and enable what you need "
            "(individual buttons or Enable/Disable all).",
        ))
        return e

    class LogsPanelView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self._sync()

        def _sync(self):
            lg = cfg(self.gid).setdefault("logs", {})
            for k in ("messages", "members", "roles", "channels", "mod"):
                lg.setdefault(k, False)

            def estilo(activo: bool) -> discord.ButtonStyle:
                return discord.ButtonStyle.success if activo else discord.ButtonStyle.secondary

            self.btn_msg.label = L(self.gid, f"Msg: {_si_no(lg.get('messages'))}", f"Msg: {_si_no(lg.get('messages'))}")
            self.btn_msg.style = estilo(bool(lg.get("messages")))
            self.btn_mem.label = L(self.gid, f"Miembros: {_si_no(lg.get('members'))}", f"Members: {_si_no(lg.get('members'))}")
            self.btn_mem.style = estilo(bool(lg.get("members")))
            self.btn_rol.label = L(self.gid, f"Roles: {_si_no(lg.get('roles'))}", f"Roles: {_si_no(lg.get('roles'))}")
            self.btn_rol.style = estilo(bool(lg.get("roles")))
            self.btn_ch.label = L(self.gid, f"Canales: {_si_no(lg.get('channels'))}", f"Channels: {_si_no(lg.get('channels'))}")
            self.btn_ch.style = estilo(bool(lg.get("channels")))
            self.btn_mod.label = L(self.gid, f"Mod: {_si_no(lg.get('mod'))}", f"Mod: {_si_no(lg.get('mod'))}")
            self.btn_mod.style = estilo(bool(lg.get("mod")))
            self.btn_todo_on.label = L(self.gid, "Activar todo", "Enable all")
            self.btn_todo_off.label = L(self.gid, "Desactivar todo", "Disable all")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")
            self.sel_canal.placeholder = L(self.gid, "Canal de logs…", "Log channel…")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_logs(self.gid), view=self)

        def _toggle(self, key: str):
            lg = cfg(self.gid).setdefault("logs", {})
            lg[key] = not bool(lg.get(key, False))
            guardar_db()

        def _set_todos(self, valor: bool):
            lg = cfg(self.gid).setdefault("logs", {})
            for k in ("messages", "members", "roles", "channels", "mod"):
                lg[k] = valor
            guardar_db()

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal de logs…",
            channel_types=[discord.ChannelType.text],
            row=0,
        )
        async def sel_canal(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            cfg(self.gid)["log_channel"] = select.values[0].id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Msg", style=discord.ButtonStyle.secondary, row=1)
        async def btn_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._toggle("messages")
            await self.actualizar(interaction)

        @discord.ui.button(label="Miembros", style=discord.ButtonStyle.secondary, row=1)
        async def btn_mem(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._toggle("members")
            await self.actualizar(interaction)

        @discord.ui.button(label="Roles", style=discord.ButtonStyle.secondary, row=1)
        async def btn_rol(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._toggle("roles")
            await self.actualizar(interaction)

        @discord.ui.button(label="Canales", style=discord.ButtonStyle.secondary, row=1)
        async def btn_ch(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._toggle("channels")
            await self.actualizar(interaction)

        @discord.ui.button(label="Mod", style=discord.ButtonStyle.secondary, row=1)
        async def btn_mod(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._toggle("mod")
            await self.actualizar(interaction)

        @discord.ui.button(label="Activar todo", style=discord.ButtonStyle.success, row=2)
        async def btn_todo_on(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._set_todos(True)
            await self.actualizar(interaction)

        @discord.ui.button(label="Desactivar todo", style=discord.ButtonStyle.danger, row=2)
        async def btn_todo_off(self, interaction: discord.Interaction, button: discord.ui.Button):
            self._set_todos(False)
            await self.actualizar(interaction)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=2)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)

    async def abrir_panel_logs(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = LogsPanelView(interaction.user.id, gid)
        embed = _embed_logs(gid)
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.mensaje = msg
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.mensaje = await interaction.original_response()


    core.abrir_panel_logs = abrir_panel_logs

