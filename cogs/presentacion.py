"""Presentación"""
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
    # CANAL DE PRESENTACIÓN
    # ============================================================

    async def asegurar_rol_pendiente(guild: discord.Guild) -> discord.Role:
        it = cfg(guild.id)["intro"]
        rol = guild.get_role(it["pending_role"]) if it["pending_role"] else None
        if rol is None:
            rol = await guild.create_role(name="Sin presentar", permissions=discord.Permissions.none(),
                                          reason="AegisBot: canal de presentación")
            it["pending_role"] = rol.id
            guardar_db()
        return rol


    async def aplicar_permisos_intro(guild: discord.Guild) -> tuple[int, int]:
        """Oculta todos los canales al rol 'Sin presentar' salvo el de presentación.
        En el canal de presentación: solo el rol pendiente puede escribir; el resto
        (tras presentarse) puede leer pero no enviar mensajes."""
        it = cfg(guild.id)["intro"]
        canal_intro = guild.get_channel(it["channel"]) if it["channel"] else None
        rol = await asegurar_rol_pendiente(guild)
        tocados: list[int] = []
        fallos = 0
        for ch in guild.channels:
            try:
                if canal_intro is not None and ch.id == canal_intro.id:
                    # @everyone: puede ver/leer, no escribir (así al presentarse ya no escribe)
                    await ch.set_permissions(
                        guild.default_role,
                        send_messages=False,
                        reason="AegisBot: canal de presentación (solo pendientes escriben)",
                    )
                    await ch.set_permissions(
                        rol,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        reason="AegisBot: canal de presentación",
                    )
                else:
                    await ch.set_permissions(rol, view_channel=False, reason="AegisBot: canal de presentación")
                tocados.append(ch.id)
            except discord.HTTPException:
                fallos += 1
            await asyncio.sleep(0.4)
        it["applied"] = True
        it["touched"] = tocados
        guardar_db()
        return len(tocados), fallos


    async def restaurar_permisos_intro(guild: discord.Guild) -> int:
        it = cfg(guild.id)["intro"]
        rol = guild.get_role(it["pending_role"]) if it["pending_role"] else None
        n = 0
        if rol is not None:
            for cid in list(it["touched"]):
                ch = guild.get_channel(cid)
                if ch is None:
                    continue
                try:
                    await ch.set_permissions(rol, overwrite=None, reason="AegisBot: restaurar permisos")
                    n += 1
                except discord.HTTPException:
                    pass
                await asyncio.sleep(0.4)
        # Quitar el bloqueo de escritura de @everyone en el canal de presentación
        canal_intro = guild.get_channel(it["channel"]) if it["channel"] else None
        if canal_intro is not None:
            try:
                ow = canal_intro.overwrites_for(guild.default_role)
                if ow.send_messages is False:
                    ow.send_messages = None
                    await canal_intro.set_permissions(
                        guild.default_role,
                        overwrite=None if ow.is_empty() else ow,
                        reason="AegisBot: restaurar permisos del canal de presentación",
                    )
                    n += 1
            except discord.HTTPException:
                pass
        it["applied"] = False
        it["touched"] = []
        guardar_db()
        return n



    def _embed_guia(gid: int) -> discord.Embed:
        it = cfg(gid)["intro"]
        min_c = it.get("min_chars", 1)
        if cfg(gid)["lang"] == "en":
            desc = (
                f"Write a message in this channel (at least **{min_c}** characters) to introduce yourself.\n\n"
                "When your message is valid, the bot will grant you access to the rest of the server.\n"
                "After introducing yourself you **will no longer be able to write** in this channel."
            )
            footer = "If you need help, contact a moderator."
            title = "🪪 How to introduce yourself"
        else:
            desc = (
                f"Escribe un mensaje en este canal (mínimo **{min_c}** caracteres) para presentarte.\n\n"
                "Cuando tu mensaje sea válido, el bot te dará acceso al resto del servidor.\n"
                "Después de presentarte **ya no podrás escribir** en este canal."
            )
            footer = "Si tienes dudas, contacta a un moderador."
            title = "🪪 Cómo presentarte"
        e = discord.Embed(title=title, description=desc, color=discord.Color.blurple())
        e.set_footer(text=footer)
        return e

    async def publicar_guia(guild: discord.Guild) -> str:
        """Publica o actualiza el mensaje guía en el canal de presentación."""
        it = cfg(guild.id)["intro"]
        canal = guild.get_channel(it["channel"]) if it["channel"] else None
        if canal is None:
            return "no_channel"
        embed = _embed_guia(guild.id)
        mid = it.get("guide_message_id")
        if mid:
            try:
                msg = await canal.fetch_message(mid)
                await msg.edit(embed=embed)
                return "updated"
            except (discord.NotFound, discord.HTTPException):
                pass
        try:
            msg = await canal.send(embed=embed)
            it["guide_message_id"] = msg.id
            guardar_db()
            try:
                await msg.pin(reason="AegisBot: guía de presentación")
            except discord.HTTPException:
                pass
            return "posted"
        except discord.HTTPException:
            return "error"

    async def procesar_timeouts_intro():
        """Expulsa o avisa sobre miembros pendientes demasiado tiempo."""
        ahora = time.time()
        for gid_s, gdata in list(DB["guilds"].items()):
            it = gdata.get("intro") or {}
            dias = int(it.get("timeout_days") or 0)
            if not it.get("enabled") or dias <= 0:
                continue
            guild = core.bot.get_guild(int(gid_s))
            if guild is None:
                continue
            pend = guild.get_role(it["pending_role"]) if it.get("pending_role") else None
            if pend is None:
                continue
            limite = dias * 86400
            accion = it.get("timeout_action") or "alert"
            ps = it.setdefault("pending_since", {})
            cambiado = False
            for uid_s, ts in list(ps.items()):
                try:
                    ts = float(ts)
                except (TypeError, ValueError):
                    continue
                if ahora - ts < limite:
                    continue
                member = guild.get_member(int(uid_s))
                if member is None or pend not in member.roles:
                    ps.pop(uid_s, None)
                    cambiado = True
                    continue
                try:
                    if accion == "kick":
                        await member.kick(reason=f"AegisBot: sin presentarse en {dias} día(s)")
                        await registrar(
                            guild,
                            L(guild.id, "🪪 Timeout presentación (kick)", "🪪 Intro timeout (kick)"),
                            f"{member} ({member.id}) — {dias}d",
                            discord.Color.orange(),
                        )
                    else:
                        await alerta(guild, discord.Embed(
                            title=L(guild.id, "🪪 Sin presentarse", "🪪 No introduction"),
                            description=L(
                                guild.id,
                                f"{member.mention} lleva **{dias}+ días** con el rol pendiente.",
                                f"{member.mention} has had the pending role for **{dias}+ days**.",
                            ),
                            color=discord.Color.orange(),
                        ))
                    # evitar spam: reinicia el contador tras alertar; tras kick se limpia
                    if accion == "kick":
                        ps.pop(uid_s, None)
                    else:
                        ps[uid_s] = ahora  # re-alerta en otros N días
                    cambiado = True
                except discord.HTTPException as e:
                    print(f"[intro timeout] {guild.id}/{uid_s}: {e}")
            if cambiado:
                guardar_db()

    async def dar_acceso(member: discord.Member, motivo: str) -> bool:
        """Quita el rol 'Sin presentar' y da el rol de miembro (si está configurado)."""
        g = member.guild
        it = cfg(g.id)["intro"]
        hecho = False
        pend = g.get_role(it["pending_role"]) if it["pending_role"] else None
        if pend is not None and pend in member.roles:
            await member.remove_roles(pend, reason=motivo)
            hecho = True
        rol = g.get_role(it["member_role"]) if it["member_role"] else None
        if rol is not None and rol not in member.roles and rol < g.me.top_role:
            await member.add_roles(rol, reason=motivo)
            hecho = True
        if hecho:
            ps = it.setdefault("pending_since", {})
            if str(member.id) in ps:
                ps.pop(str(member.id), None)
                guardar_db()
        return hecho


    @bot.listen("on_message")
    async def intro_mensaje(message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        it = cfg(message.guild.id)["intro"]
        if not it["enabled"] or message.channel.id != it["channel"]:
            return
        miembro = message.author
        if not isinstance(miembro, discord.Member):
            return
        pend = message.guild.get_role(it["pending_role"]) if it["pending_role"] else None
        if pend is None or pend not in miembro.roles:
            return
        if len(message.content.strip()) < it["min_chars"]:
            return
        await asyncio.sleep(1.5)  # si el AutoMod borra el mensaje, no cuenta como presentación
        try:
            await message.channel.fetch_message(message.id)
        except discord.NotFound:
            return
        except discord.HTTPException:
            pass
        gid = message.guild.id
        try:
            await dar_acceso(miembro, "AegisBot: se presentó")
        except discord.HTTPException as e:
            print(f"[intro] No pude dar acceso a {miembro}: {e}")
            return
        try:
            await message.add_reaction(discord.PartialEmoji(name="aceptado", id=1560557801464668240))
        except discord.HTTPException:
            pass
        await registrar(message.guild, L(gid, "🪪 Presentación completada", "🪪 Introduction completed"),
                        f"{miembro.mention} ({miembro.id})", discord.Color.green())


    @bot.listen("on_guild_channel_create")
    async def intro_canal_nuevo(channel: discord.abc.GuildChannel):
        it = cfg(channel.guild.id)["intro"]
        if not (it["enabled"] and it["applied"] and it["pending_role"]):
            return
        rol = channel.guild.get_role(it["pending_role"])
        if rol is None:
            return
        try:
            await channel.set_permissions(rol, view_channel=False, reason="AegisBot: canal de presentación")
            it["touched"].append(channel.id)
            guardar_db()
        except discord.HTTPException:
            pass


    @bot.tree.command(name="verify", description="Da acceso manual a un miembro pendiente de presentación")
    @app_commands.describe(usuario="Miembro al que dar acceso")
    @app_commands.guild_only()
    @solo_mod()
    async def verify(interaction: discord.Interaction, usuario: discord.Member):
        gid = interaction.guild_id
        await interaction.response.defer(ephemeral=True)
        try:
            hecho = await dar_acceso(usuario, f"AegisBot: /verify por {interaction.user}")
        except discord.HTTPException as e:
            await interaction.followup.send(L(gid, f"No pude dar acceso: {e}", f"Could not grant access: {e}"))
            return
        await interaction.followup.send(
            L(gid, f"<:aceptado:1560557801464668240> {usuario.mention} ya tiene acceso.", f"<:aceptado:1560557801464668240> {usuario.mention} now has access.") if hecho
            else L(gid, "Ese miembro no estaba pendiente.", "That member wasn't pending."))
        if hecho:
            await registrar(interaction.guild, "🪪 /verify", f"{usuario.mention} ({usuario.id})",
                            discord.Color.green(), [("Mod", interaction.user.mention)])


    def _embed_intro(gid: int) -> discord.Embed:
        it = cfg(gid)["intro"]
        canal_txt = f"<#{it['channel']}>" if it["channel"] else L(gid, "(sin canal)", "(no channel)")
        rol_txt = f"<@&{it['member_role']}>" if it["member_role"] else L(gid, "(ninguno)", "(none)")
        pend_txt = f"<@&{it['pending_role']}>" if it["pending_role"] else L(gid, "(se crea al aplicar)", "(created on apply)")
        aplicados = L(gid, "Sí", "Yes") if it["applied"] else L(gid, "No — pulsa «Aplicar permisos»", "No — tap «Apply permissions»")
        e = discord.Embed(
            title=L(gid, "🪪 Presentación · Configuración", "🪪 Introduction · Configuration"),
            color=discord.Color.blurple(),
        )
        e.add_field(name=L(gid, "Estado", "Status"), value=_si_no(it["enabled"]))
        e.add_field(name=L(gid, "Canal", "Channel"), value=canal_txt)
        e.add_field(name=L(gid, "Mín. caracteres", "Min. characters"), value=str(it["min_chars"]))
        e.add_field(name=L(gid, "Rol al presentarse", "Role on intro"), value=rol_txt)
        e.add_field(name=L(gid, "Rol pendiente", "Pending role"), value=pend_txt)
        e.add_field(name=L(gid, "Permisos aplicados", "Permissions applied"), value=aplicados, inline=False)
        dias = int(it.get("timeout_days") or 0)
        if dias <= 0:
            to_txt = L(gid, "Desactivado", "Off")
        else:
            acc = it.get("timeout_action") or "alert"
            acc_txt = L(gid, "expulsar", "kick") if acc == "kick" else L(gid, "avisar mods", "alert mods")
            to_txt = f"{dias}d · {acc_txt}"
        e.add_field(name=L(gid, "Timeout pendientes", "Pending timeout"), value=to_txt)
        guia = L(gid, "Publicado", "Posted") if it.get("guide_message_id") else L(gid, "No publicado", "Not posted")
        e.add_field(name=L(gid, "Mensaje guía", "Guide message"), value=guia)
        e.set_footer(text=L(
            gid,
            "Guía en el canal + timeout de pendientes. Se cierra en 3 min.",
            "Channel guide + pending timeout. Closes in 3 min.",
        ))
        return e


    PanelView = getattr(core, "PanelView", None)
    NumeroModal = getattr(core, "NumeroModal", None)
    if PanelView is None or NumeroModal is None:
        raise RuntimeError("PanelView/NumeroModal no disponibles en core")

    class IntroPanelView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self._sync()

        def _sync(self):
            it = cfg(self.gid)["intro"]
            self.btn_toggle.label = L(self.gid, "Desactivar" if it["enabled"] else "Activar",
                                      "Disable" if it["enabled"] else "Enable")
            self.btn_toggle.style = (discord.ButtonStyle.danger if it["enabled"]
                                     else discord.ButtonStyle.success)
            self.btn_minimo.label = L(self.gid, f"Mín. caracteres: {it['min_chars']}",
                                      f"Min. chars: {it['min_chars']}")
            self.btn_aplicar.label = L(self.gid, "Aplicar permisos", "Apply permissions")
            self.btn_restaurar.label = L(self.gid, "Restaurar permisos", "Restore permissions")
            self.btn_quitar_rol.label = L(self.gid, "Quitar rol miembro", "Clear member role")
            self.btn_guia.label = L(self.gid, "Publicar guía", "Post guide")
            dias = int(it.get("timeout_days") or 0)
            self.btn_timeout.label = L(
                self.gid,
                f"Timeout: {dias}d" if dias else "Timeout: off",
                f"Timeout: {dias}d" if dias else "Timeout: off",
            )
            acc = it.get("timeout_action") or "alert"
            self.btn_timeout_acc.label = L(
                self.gid,
                "Acción: expulsar" if acc == "kick" else "Acción: avisar",
                "Action: kick" if acc == "kick" else "Action: alert",
            )
            self.sel_canal.placeholder = L(self.gid, "Canal de presentación…", "Introduction channel…")
            self.sel_rol.placeholder = L(self.gid, "Rol al presentarse (opcional)…", "Role on intro (optional)…")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_intro(self.gid), view=self)

        # Selectors first so they are visible without scrolling (row 0–1)
        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal de presentación…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )
        async def sel_canal(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            gid = self.gid
            g = interaction.guild
            canal = select.values[0].resolve()
            if canal is None:
                await interaction.response.send_message(L(
                    gid, "No encuentro ese canal en el servidor. Inténtalo de nuevo.",
                    "I can't find that channel on the server. Please try again."), ephemeral=True)
                return
            perms = canal.permissions_for(g.me)
            if not (perms.view_channel and perms.send_messages and perms.add_reactions):
                await interaction.response.send_message(L(
                    gid, "No tengo permisos en ese canal (ver, escribir y reaccionar).",
                    "I lack permissions in that channel (view, send and react)."), ephemeral=True)
                return
            it = cfg(gid)["intro"]
            cambiado = it["channel"] != canal.id
            it["channel"] = canal.id
            if cambiado and it["applied"]:
                it["applied"] = False  # hay que volver a aplicar
            guardar_db()
            await self.actualizar(interaction)
            if cambiado:
                await interaction.followup.send(L(
                    gid, "Canal actualizado. Pulsa **Aplicar permisos** para ocultar el resto de canales.",
                    "Channel updated. Tap **Apply permissions** to hide the other channels."), ephemeral=True)

        @discord.ui.select(
            cls=discord.ui.RoleSelect,
            placeholder="Rol al presentarse (opcional)…",
            min_values=1,
            max_values=1,
            row=1,
        )
        async def sel_rol(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
            gid = self.gid
            g = interaction.guild
            rol = select.values[0]
            if rol >= g.me.top_role or rol.is_default() or rol.managed:
                await interaction.response.send_message(L(
                    gid, "No puedo asignar ese rol (está por encima del mío o es de sistema).",
                    "I can't assign that role (above mine or managed)."), ephemeral=True)
                return
            cfg(gid)["intro"]["member_role"] = rol.id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.success, row=2)
        async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            it = cfg(gid)["intro"]
            if not it["enabled"]:
                if not it["channel"] or (g and g.get_channel(it["channel"]) is None):
                    await interaction.response.send_message(
                        L(gid, "Primero elige un canal de presentación.",
                          "Pick an introduction channel first."), ephemeral=True)
                    return
                try:
                    await asegurar_rol_pendiente(g)
                except discord.HTTPException as e:
                    await interaction.response.send_message(L(
                        gid, f"No pude crear el rol 'Sin presentar' (me falta Manage Roles): {e}",
                        f"Could not create the 'Sin presentar' role (missing Manage Roles): {e}"),
                        ephemeral=True)
                    return
                it["enabled"] = True
            else:
                it["enabled"] = False
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Mín. caracteres", style=discord.ButtonStyle.secondary, row=2)
        async def btn_minimo(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Caracteres mínimos", "Minimum characters"),
                ("Cantidad (1-500)", "Amount (1-500)"), 1, 500,
                lambda g: cfg(g)["intro"]["min_chars"],
                lambda g, v: cfg(g)["intro"].__setitem__("min_chars", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Quitar rol miembro", style=discord.ButtonStyle.secondary, row=2)
        async def btn_quitar_rol(self, interaction: discord.Interaction, button: discord.ui.Button):
            cfg(self.gid)["intro"]["member_role"] = None
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Aplicar permisos", style=discord.ButtonStyle.primary, row=3)
        async def btn_aplicar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            it = cfg(gid)["intro"]
            if not it["channel"] or g.get_channel(it["channel"]) is None:
                await interaction.response.send_message(
                    L(gid, "Primero elige un canal de presentación.",
                      "Pick an introduction channel first."), ephemeral=True)
                return
            if not await pedir_confirmacion(interaction, L(
                    gid,
                    "⚠️ Esto crea el rol de pendientes, oculta el resto de canales a quien no se presentó "
                    "y deja escribir solo en el canal de presentación. Puede tardar. **¿Continuar?**",
                    "⚠️ This creates the pending role, hides other channels from those who have not introduced "
                    "themselves, and only allows writing in the intro channel. It may take a while. **Continue?**")):
                return
            try:
                await asegurar_rol_pendiente(g)
                n, fallos = await aplicar_permisos_intro(g)
            except discord.HTTPException as e:
                await interaction.followup.send(L(gid, f"Error al aplicar permisos: {e}",
                                                  f"Error applying permissions: {e}"), ephemeral=True)
                return
            self._sync()
            try:
                if self.mensaje:
                    await self.mensaje.edit(embed=_embed_intro(gid), view=self)
            except discord.HTTPException:
                pass
            await interaction.followup.send(L(
                gid,
                f"<:aceptado:1560557801464668240> Listo: {n} canales configurados ({fallos} con error). "
                f"Los nuevos solo verán <#{it['channel']}> hasta presentarse; al presentarse ya no podrán "
                f"escribir ahí. Los miembros actuales no cambian.",
                f"<:aceptado:1560557801464668240> Done: {n} channels configured ({fallos} failed). "
                f"New members will only see <#{it['channel']}> until they introduce themselves; after that "
                f"they can no longer write there. Current members are unaffected.",
            ), ephemeral=True)

        @discord.ui.button(label="Restaurar permisos", style=discord.ButtonStyle.secondary, row=3)
        async def btn_restaurar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            if not await pedir_confirmacion(interaction, L(
                    gid,
                    "⚠️ Se desharán los permisos aplicados por la presentación en los canales tocados. **¿Continuar?**",
                    "⚠️ Permission changes applied by the introduction module will be undone. **Continue?**")):
                return
            n = await restaurar_permisos_intro(g)
            self._sync()
            try:
                if self.mensaje:
                    await self.mensaje.edit(embed=_embed_intro(gid), view=self)
            except discord.HTTPException:
                pass
            await interaction.followup.send(L(
                gid,
                f"<:aceptado:1560557801464668240> Permisos restaurados en {n} canal(es). "
                f"Quienes tengan el rol 'Sin presentar' vuelven a ver todo y se puede volver a escribir "
                f"en el canal de presentación.",
                f"<:aceptado:1560557801464668240> Permissions restored in {n} channel(s). "
                f"Anyone with the 'Sin presentar' role sees everything again and writing in the "
                f"introduction channel is allowed again.",
            ), ephemeral=True)

        @discord.ui.button(label="Publicar guía", style=discord.ButtonStyle.primary, row=3)
        async def btn_guia(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            it = cfg(gid)["intro"]
            if not it["channel"] or g.get_channel(it["channel"]) is None:
                await interaction.response.send_message(
                    L(gid, "Primero elige un canal de presentación.",
                      "Pick an introduction channel first."), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            res = await publicar_guia(g)
            self._sync()
            try:
                await interaction.edit_original_response(embed=_embed_intro(gid), view=self)
            except discord.HTTPException:
                pass
            msgs = {
                "posted": L(gid, "<:aceptado:1560557801464668240> Guía publicada y fijada en el canal.",
                            "<:aceptado:1560557801464668240> Guide posted and pinned in the channel."),
                "updated": L(gid, "<:aceptado:1560557801464668240> Guía actualizada.",
                             "<:aceptado:1560557801464668240> Guide updated."),
                "no_channel": L(gid, "No hay canal configurado.", "No channel configured."),
                "error": L(gid, "No pude publicar la guía (permisos).", "Could not post the guide (permissions)."),
            }
            await interaction.followup.send(msgs.get(res, res), ephemeral=True)

        @discord.ui.button(label="Timeout: off", style=discord.ButtonStyle.secondary, row=4)
        async def btn_timeout(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Días sin presentarse", "Days without intro"),
                ("0 = desactivar, máx. 30", "0 = off, max 30"), 0, 30,
                lambda g: int(cfg(g)["intro"].get("timeout_days") or 0),
                lambda g, v: cfg(g)["intro"].__setitem__("timeout_days", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Acción: avisar", style=discord.ButtonStyle.secondary, row=4)
        async def btn_timeout_acc(self, interaction: discord.Interaction, button: discord.ui.Button):
            it = cfg(self.gid)["intro"]
            it["timeout_action"] = "kick" if (it.get("timeout_action") or "alert") == "alert" else "alert"
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=4)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_intro(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = IntroPanelView(interaction.user.id, gid)
        embed = _embed_intro(gid)
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.mensaje = msg
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.mensaje = await interaction.original_response()






    core.abrir_panel_intro = abrir_panel_intro

    @tasks.loop(hours=1)
    async def tarea_intro_timeout():
        try:
            await procesar_timeouts_intro()
        except Exception as e:
            print(f"[intro timeout task] {e}")

    if not tarea_intro_timeout.is_running():
        tarea_intro_timeout.start()
