"""Config y paneles"""
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
    # /config (panel centralizado)
    # ============================================================
    config = core.config_group

    async def _enviar_panel(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View):
        """Abre un panel aunque la interaction ya haya respondido (p.ej. desde /config panel)."""
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            msg = await interaction.original_response()
        view.mensaje = msg
        return msg

    def _si_no(v) -> str:
        return "<:aceptado:1560557801464668240>" if v else "<:X_:1560557532836270101>"


    @config.command(name="view", description="Muestra la configuración actual")
    @solo_admin()
    async def cfg_view(interaction: discord.Interaction):
        g = interaction.guild
        c = cfg(g.id)
        es = c["lang"] != "en"

        def canal(i):
            return f"<#{i}>" if i else "—"

        roles_mod = " ".join(f"<@&{r}>" for r in c["mod_roles"]) or "—"
        am, sp, ar = c["automod"], c["antispam"], c["antiraid"]
        tk, gw = c["tickets"], c["giveaway"]
        e = discord.Embed(title="⚙️ AegisBot · Config", color=discord.Color.blurple())
        e.add_field(name="🌍 " + ("Idioma" if es else "Language"), value="Español" if es else "English")
        e.add_field(name="🛡️ " + ("Roles mod" if es else "Mod roles"), value=roles_mod)
        e.add_field(name="📜 Logs", value=canal(c["log_channel"]))
        e.add_field(name="👋 " + ("Bienvenida" if es else "Welcome"),
                    value=f"{_si_no(c['welcome_enabled'])} {canal(c['welcome_channel'])}")
        e.add_field(name="🆕 " + ("Cuentas nuevas" if es else "New accounts"),
                    value=f"{_si_no(c['newacc_enabled'])} < {c['newacc_days']}d")
        e.add_field(name="<:Automod:1561610638055309312> AutoMod",
                    value=(f"{_si_no(am['enabled'])} · words: {len(am['words'])} · links {_si_no(am['block_links'])} · "
                           f"invites {_si_no(am['block_invites'])} · caps {_si_no(am['caps'])} "
                           f"({am['caps_threshold']}%) · emojis {_si_no(am['emojis'])} ({am['emoji_limit']})"),
                    inline=False)
        e.add_field(name="🚫 Anti-spam",
                    value=f"{_si_no(sp['enabled'])} {sp['messages']} msg / {sp['seconds']}s → {sp['action']}",
                    inline=False)
        e.add_field(name="🚨 Anti-raid",
                    value=f"{_si_no(ar['enabled'])} {ar['joins']} joins / {ar['seconds']}s → "
                          f"lockdown {ar['lockdown_minutes']} min", inline=False)
        cat_txt = f"<#{tk['category']}>" if tk["category"] else "—"
        rol_txt = f"<@&{tk['support_role']}>" if tk["support_role"] else "—"
        e.add_field(name="🎫 Tickets",
                    value=f"cat: {cat_txt} · role: {rol_txt} · log: {canal(tk['log_channel'])}",
                    inline=False)
        w, lg = c["warns"], c["logs"]
        e.add_field(name="⚠️ Warns", value=f"{w['threshold']} → {w['action']} ({w['minutes']} min)")
        e.add_field(name="📋 Logs", value=f"msg {_si_no(lg['messages'])} · members {_si_no(lg['members'])}")
        e.add_field(name="🎭 Autorole", value=f"<@&{c['autorole']}>" if c["autorole"] else "—")
        ip = c["intro"]
        rol_intro = f"<@&{ip['member_role']}>" if ip["member_role"] else "—"
        e.add_field(name="🪪 " + ("Presentación" if es else "Intro"),
                    value=(f"{_si_no(ip['enabled'])} {canal(ip['channel'])} · min {ip['min_chars']} · "
                           f"rol {rol_intro} · " + ("aplicado" if ip["applied"] else "sin aplicar")),
                    inline=False)
        cf = c["confess"]
        e.add_field(name="💬 Confess", value=f"{_si_no(cf['enabled'])} {canal(cf['channel'])}")
        e.add_field(name="🎁 Giveaways", value=f"{canal(gw['channel'])} · {gw['platform']}", inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


    @config.command(name="language", description="Cambia el idioma del bot en este servidor")
    @app_commands.choices(idioma=[
        app_commands.Choice(name="Español", value="es"),
        app_commands.Choice(name="English", value="en"),
    ])
    @solo_admin()
    async def cfg_language(interaction: discord.Interaction, idioma: app_commands.Choice[str]):
        cfg(interaction.guild_id)["lang"] = idioma.value
        guardar_db()
        await interaction.response.send_message(
            "<:aceptado:1560557801464668240> Idioma: Español" if idioma.value == "es" else "<:aceptado:1560557801464668240> Language: English", ephemeral=True)


    @config.command(name="modrole", description="Agrega o quita un rol de moderador")
    @app_commands.choices(accion=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ])
    @solo_admin()
    async def cfg_modrole(interaction: discord.Interaction, accion: app_commands.Choice[str], rol: discord.Role):
        gid = interaction.guild_id
        c = cfg(gid)
        if accion.value == "add":
            if rol.id not in c["mod_roles"]:
                c["mod_roles"].append(rol.id)
        else:
            if rol.id in c["mod_roles"]:
                c["mod_roles"].remove(rol.id)
        guardar_db()
        await interaction.response.send_message(
            L(gid, f"<:aceptado:1560557801464668240> Roles mod actualizados ({len(c['mod_roles'])}).",
              f"<:aceptado:1560557801464668240> Mod roles updated ({len(c['mod_roles'])})."), ephemeral=True)


    @config.command(name="logchannel", description="Define el canal de logs y alertas")
    @solo_admin()
    async def cfg_logchannel(interaction: discord.Interaction, canal: discord.TextChannel):
        gid = interaction.guild_id
        perms = canal.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message(
                L(gid, "No tengo permisos para escribir embeds en ese canal.",
                  "I can't send embeds in that channel."), ephemeral=True)
            return
        cfg(gid)["log_channel"] = canal.id
        guardar_db()
        await interaction.response.send_message(
            L(gid, f"<:aceptado:1560557801464668240> Logs en {canal.mention}.", f"<:aceptado:1560557801464668240> Logs set to {canal.mention}."), ephemeral=True)


    @config.command(name="words", description="Gestiona el filtro de vocabulario")
    @app_commands.describe(accion="add / remove / list", palabras="Palabra(s), separadas por coma")
    @app_commands.choices(accion=[
        app_commands.Choice(name="add", value="add"),
        app_commands.Choice(name="remove", value="remove"),
        app_commands.Choice(name="list", value="list"),
    ])
    @solo_admin()
    async def cfg_words(interaction: discord.Interaction, accion: app_commands.Choice[str],
                        palabras: app_commands.Range[str, 1, 500] | None = None):
        gid = interaction.guild_id
        am = cfg(gid)["automod"]
        if accion.value == "list":
            txt = ", ".join(am["words"]) or "—"
            await interaction.response.send_message(f"```{txt[:1900]}```", ephemeral=True)
            return
        if not palabras:
            await interaction.response.send_message(L(gid, "Indica al menos una palabra.",
                                                      "Provide at least one word."), ephemeral=True)
            return
        nuevas = [core.normalizar(p).strip() for p in palabras.split(",")]
        nuevas = [p for p in nuevas if p]
        if accion.value == "add":
            for p in nuevas:
                if p not in am["words"]:
                    am["words"].append(p)
        else:
            am["words"] = [p for p in am["words"] if p not in nuevas]
        guardar_db()
        await interaction.response.send_message(
            L(gid, f"<:aceptado:1560557801464668240> Lista actualizada ({len(am['words'])} palabras).",
              f"<:aceptado:1560557801464668240> List updated ({len(am['words'])} words)."), ephemeral=True)



    # ============================================================
    # PANELES DE CONFIG (antispam / antiraid)
    # ============================================================

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


    def _embed_antispam(gid: int) -> discord.Embed:
        sp = cfg(gid)["antispam"]
        e = discord.Embed(title=L(gid, "🚫 Anti-spam · Configuración", "🚫 Anti-spam · Configuration"),
                          color=discord.Color.blurple())
        e.add_field(name=L(gid, "Estado", "Status"), value=_si_no(sp["enabled"]))
        e.add_field(name=L(gid, "Mensajes", "Messages"), value=str(sp["messages"]))
        e.add_field(name=L(gid, "Ventana", "Window"), value=f"{sp['seconds']}s")
        e.add_field(name=L(gid, "Acción", "Action"), value=sp["action"])
        e.add_field(name=L(gid, "Avisar primero", "Warn first"), value=_si_no(sp["warn_first"]))
        e.set_footer(text=L(gid, "Toca un botón para cambiarlo. Se cierra solo en 3 min.",
                            "Tap a button to change it. Closes by itself in 3 min."))
        return e


    class AntispamPanelView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self._sync()

        def _sync(self):
            sp = cfg(self.gid)["antispam"]
            self.btn_toggle.label = L(self.gid, "Desactivar" if sp["enabled"] else "Activar",
                                      "Disable" if sp["enabled"] else "Enable")
            self.btn_toggle.style = discord.ButtonStyle.danger if sp["enabled"] else discord.ButtonStyle.success
            self.btn_mensajes.label = L(self.gid, "Mensajes", "Messages")
            self.btn_segundos.label = L(self.gid, "Ventana", "Window")
            self.btn_accion.label = L(self.gid, f"Acción: {sp['action']}", f"Action: {sp['action']}")
            self.btn_avisar.label = L(
                self.gid, "Avisar primero: Sí" if sp["warn_first"] else "Avisar primero: No",
                "Warn first: On" if sp["warn_first"] else "Warn first: Off")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_antispam(self.gid), view=self)

        @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.success, row=0)
        async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
            sp = cfg(self.gid)["antispam"]
            sp["enabled"] = not sp["enabled"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Mensajes", style=discord.ButtonStyle.secondary, row=0)
        async def btn_mensajes(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Mensajes para disparar", "Messages to trigger"),
                ("Cantidad (2-20)", "Amount (2-20)"), 2, 20,
                lambda g: cfg(g)["antispam"]["messages"],
                lambda g, v: cfg(g)["antispam"].__setitem__("messages", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Ventana", style=discord.ButtonStyle.secondary, row=0)
        async def btn_segundos(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Ventana en segundos", "Window in seconds"),
                ("Segundos (2-60)", "Seconds (2-60)"), 2, 60,
                lambda g: cfg(g)["antispam"]["seconds"],
                lambda g, v: cfg(g)["antispam"].__setitem__("seconds", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Acción", style=discord.ButtonStyle.secondary, row=1)
        async def btn_accion(self, interaction: discord.Interaction, button: discord.ui.Button):
            sp = cfg(self.gid)["antispam"]
            sp["action"] = "mute" if sp["action"] == "kick" else "kick"
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Avisar primero", style=discord.ButtonStyle.secondary, row=1)
        async def btn_avisar(self, interaction: discord.Interaction, button: discord.ui.Button):
            sp = cfg(self.gid)["antispam"]
            sp["warn_first"] = not sp["warn_first"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=2)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_antispam(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = AntispamPanelView(interaction.user.id, gid)
        await _enviar_panel(interaction, _embed_antispam(gid), view)


    def _embed_antiraid(gid: int) -> discord.Embed:
        ar = cfg(gid)["antiraid"]
        e = discord.Embed(title=L(gid, "🚨 Anti-raid · Configuración", "🚨 Anti-raid · Configuration"),
                          color=discord.Color.blurple())
        e.add_field(name=L(gid, "Estado", "Status"), value=_si_no(ar["enabled"]))
        e.add_field(name=L(gid, "Entradas", "Joins"), value=str(ar["joins"]))
        e.add_field(name=L(gid, "Ventana", "Window"), value=f"{ar['seconds']}s")
        e.add_field(name=L(gid, "Lockdown", "Lockdown"), value=f"{ar['lockdown_minutes']} min")
        e.set_footer(text=L(gid, "Toca un botón para cambiarlo. Se cierra solo en 3 min.",
                            "Tap a button to change it. Closes by itself in 3 min."))
        return e


    class AntiraidPanelView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self._sync()

        def _sync(self):
            ar = cfg(self.gid)["antiraid"]
            self.btn_toggle.label = L(self.gid, "Desactivar" if ar["enabled"] else "Activar",
                                      "Disable" if ar["enabled"] else "Enable")
            self.btn_toggle.style = discord.ButtonStyle.danger if ar["enabled"] else discord.ButtonStyle.success
            self.btn_entradas.label = L(self.gid, "Entradas", "Joins")
            self.btn_segundos.label = L(self.gid, "Ventana", "Window")
            self.btn_lockdown.label = L(self.gid, "Duración lockdown", "Lockdown length")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_antiraid(self.gid), view=self)

        @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.success, row=0)
        async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
            ar = cfg(self.gid)["antiraid"]
            ar["enabled"] = not ar["enabled"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Entradas", style=discord.ButtonStyle.secondary, row=0)
        async def btn_entradas(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Entradas para disparar", "Joins to trigger"),
                ("Cantidad (3-50)", "Amount (3-50)"), 3, 50,
                lambda g: cfg(g)["antiraid"]["joins"],
                lambda g, v: cfg(g)["antiraid"].__setitem__("joins", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Ventana", style=discord.ButtonStyle.secondary, row=0)
        async def btn_segundos(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Ventana en segundos", "Window in seconds"),
                ("Segundos (3-120)", "Seconds (3-120)"), 3, 120,
                lambda g: cfg(g)["antiraid"]["seconds"],
                lambda g, v: cfg(g)["antiraid"].__setitem__("seconds", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Duración lockdown", style=discord.ButtonStyle.secondary, row=1)
        async def btn_lockdown(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Duración del lockdown (min)", "Lockdown length (min)"),
                ("Minutos (1-1440)", "Minutes (1-1440)"), 1, 1440,
                lambda g: cfg(g)["antiraid"]["lockdown_minutes"],
                lambda g, v: cfg(g)["antiraid"].__setitem__("lockdown_minutes", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=2)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_antiraid(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = AntiraidPanelView(interaction.user.id, gid)
        await _enviar_panel(interaction, _embed_antiraid(gid), view)



    # ============================================================
    # PANELES DE CONFIG (automod / welcome)
    # ============================================================

    class TextoModal(discord.ui.Modal):
        """Modal genérico para editar un valor de texto largo (ej. mensaje de bienvenida)."""

        def __init__(self, panel: PanelView, titulo: tuple, etiqueta: tuple,
                    maximo: int, obtener, guardar_valor):
            super().__init__(title=L(panel.gid, *titulo)[:45])
            self.panel = panel
            self.guardar_valor = guardar_valor
            self.campo = discord.ui.TextInput(
                label=L(panel.gid, *etiqueta)[:45], default=obtener(panel.gid),
                max_length=maximo, style=discord.TextStyle.paragraph, required=True)
            self.add_item(self.campo)

        async def on_submit(self, interaction: discord.Interaction):
            gid = self.panel.gid
            self.guardar_valor(gid, str(self.campo.value))
            guardar_db()
            await self.panel.actualizar(interaction)


    def _embed_automod(gid: int) -> discord.Embed:
        am = cfg(gid)["automod"]
        e = discord.Embed(title=L(gid, "<:Automod:1561610638055309312> AutoMod · Configuración", "<:Automod:1561610638055309312> AutoMod · Configuration"),
                          color=discord.Color.blurple())
        e.add_field(name=L(gid, "Estado", "Status"), value=_si_no(am["enabled"]))
        e.add_field(name=L(gid, "Links bloqueados", "Links blocked"), value=_si_no(am["block_links"]))
        e.add_field(name=L(gid, "Invitaciones bloqueadas", "Invites blocked"), value=_si_no(am["block_invites"]))
        e.add_field(name=L(gid, "Mayúsculas", "Caps"),
                   value=f"{_si_no(am['caps'])} ({am['caps_threshold']}%)")
        e.add_field(name=L(gid, "Emojis", "Emojis"),
                   value=f"{_si_no(am['emojis'])} (máx {am['emoji_limit']})" if gid and cfg(gid)["lang"] != "en"
                   else f"{_si_no(am['emojis'])} (max {am['emoji_limit']})")
        e.add_field(name=L(gid, "Vocabulario", "Vocabulary"), value=f"{len(am['words'])}")
        e.set_footer(text=L(
            gid, "El vocabulario se gestiona con /config words. Toca un botón para cambiar esto.",
            "Vocabulary is managed with /config words. Tap a button to change this."))
        return e


    class AutomodPanelView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self._sync()

        def _sync(self):
            am = cfg(self.gid)["automod"]
            self.btn_toggle.label = L(self.gid, "Desactivar AutoMod" if am["enabled"] else "Activar AutoMod",
                                      "Disable AutoMod" if am["enabled"] else "Enable AutoMod")
            self.btn_toggle.style = discord.ButtonStyle.danger if am["enabled"] else discord.ButtonStyle.success
            self.btn_links.label = L(
                self.gid, "Links: bloqueados" if am["block_links"] else "Links: permitidos",
                "Links: blocked" if am["block_links"] else "Links: allowed")
            self.btn_invites.label = L(
                self.gid, "Invitaciones: bloqueadas" if am["block_invites"] else "Invitaciones: permitidas",
                "Invites: blocked" if am["block_invites"] else "Invites: allowed")
            self.btn_caps.label = L(self.gid, "Mayúsculas: ON" if am["caps"] else "Mayúsculas: OFF",
                                    "Caps: ON" if am["caps"] else "Caps: OFF")
            self.btn_caps_pct.label = L(self.gid, f"% Mayúsculas: {am['caps_threshold']}",
                                        f"Caps %: {am['caps_threshold']}")
            self.btn_emojis.label = L(self.gid, "Emojis: ON" if am["emojis"] else "Emojis: OFF",
                                      "Emojis: ON" if am["emojis"] else "Emojis: OFF")
            self.btn_emoji_limite.label = L(self.gid, f"Límite emojis: {am['emoji_limit']}",
                                            f"Emoji limit: {am['emoji_limit']}")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_automod(self.gid), view=self)

        @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.success, row=0)
        async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
            am = cfg(self.gid)["automod"]
            am["enabled"] = not am["enabled"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Links", style=discord.ButtonStyle.secondary, row=0)
        async def btn_links(self, interaction: discord.Interaction, button: discord.ui.Button):
            am = cfg(self.gid)["automod"]
            am["block_links"] = not am["block_links"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Invitaciones", style=discord.ButtonStyle.secondary, row=0)
        async def btn_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
            am = cfg(self.gid)["automod"]
            am["block_invites"] = not am["block_invites"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Mayúsculas", style=discord.ButtonStyle.secondary, row=1)
        async def btn_caps(self, interaction: discord.Interaction, button: discord.ui.Button):
            am = cfg(self.gid)["automod"]
            am["caps"] = not am["caps"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="% Mayúsculas", style=discord.ButtonStyle.secondary, row=1)
        async def btn_caps_pct(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("% de mayúsculas", "Caps percentage"),
                ("Porcentaje (30-100)", "Percentage (30-100)"), 30, 100,
                lambda g: cfg(g)["automod"]["caps_threshold"],
                lambda g, v: cfg(g)["automod"].__setitem__("caps_threshold", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Emojis", style=discord.ButtonStyle.secondary, row=1)
        async def btn_emojis(self, interaction: discord.Interaction, button: discord.ui.Button):
            am = cfg(self.gid)["automod"]
            am["emojis"] = not am["emojis"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Límite de emojis", style=discord.ButtonStyle.secondary, row=2)
        async def btn_emoji_limite(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self, ("Límite de emojis por mensaje", "Emoji limit per message"),
                ("Cantidad (1-50)", "Amount (1-50)"), 1, 50,
                lambda g: cfg(g)["automod"]["emoji_limit"],
                lambda g, v: cfg(g)["automod"].__setitem__("emoji_limit", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=2)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_automod(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = AutomodPanelView(interaction.user.id, gid)
        await _enviar_panel(interaction, _embed_automod(gid), view)


    def _nombre_fuente(gid: int, font_id: str | None) -> str:
        fuentes = getattr(core, "FUENTES_BIENVENIDA", {})
        fid = font_id if font_id in fuentes else "blackgold"
        info = fuentes.get(fid) or {}
        es = cfg(gid)["lang"] != "en"
        return info.get("label_es" if es else "label_en", fid)

    def _embed_welcome(gid: int) -> discord.Embed:
        c = cfg(gid)
        canal_txt = f"<#{c['welcome_channel']}>" if c["welcome_channel"] else L(gid, "(sin canal)", "(no channel)")
        e = discord.Embed(title=L(gid, "👋 Bienvenida · Configuración", "👋 Welcome · Configuration"),
                          color=discord.Color.blurple())
        e.add_field(name=L(gid, "Estado", "Status"), value=_si_no(c["welcome_enabled"]))
        e.add_field(name=L(gid, "Canal", "Channel"), value=canal_txt)
        e.add_field(name=L(gid, "Tipografía", "Font"), value=_nombre_fuente(gid, c.get("welcome_font")))
        e.add_field(name=L(gid, "Mensaje", "Message"), value=c["welcome_message"][:1000], inline=False)
        e.set_footer(text=L(
            gid, "Variables: {user} {server} {count}. Elige tipografía y pulsa Probar.",
            "Variables: {user} {server} {count}. Pick a font and tap Test."))
        return e


    class WelcomePanelView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self._sync()

        def _sync(self):
            c = cfg(self.gid)
            self.btn_toggle.label = L(self.gid, "Desactivar" if c["welcome_enabled"] else "Activar",
                                      "Disable" if c["welcome_enabled"] else "Enable")
            self.btn_toggle.style = (discord.ButtonStyle.danger if c["welcome_enabled"]
                                     else discord.ButtonStyle.success)
            self.btn_mensaje.label = L(self.gid, "Mensaje", "Message")
            self.btn_probar.label = L(self.gid, "Probar", "Test")
            self.sel_canal.placeholder = L(self.gid, "Elegir canal de bienvenida", "Pick welcome channel")
            self.sel_fuente.placeholder = L(self.gid, "Tipografía de la tarjeta…", "Card font…")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_welcome(self.gid), view=self)

        @discord.ui.button(label="Activar/Desactivar", style=discord.ButtonStyle.success, row=0)
        async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
            c = cfg(self.gid)
            c["welcome_enabled"] = not c["welcome_enabled"]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Mensaje", style=discord.ButtonStyle.secondary, row=0)
        async def btn_mensaje(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = TextoModal(
                self, ("Mensaje de bienvenida", "Welcome message"),
                ("Texto. {user} {server} {count}", "Text. {user} {server} {count}"), 500,
                lambda g: cfg(g)["welcome_message"],
                lambda g, v: cfg(g).__setitem__("welcome_message", v))
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Probar", style=discord.ButtonStyle.secondary, row=0)
        async def btn_probar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            if not cfg(gid)["welcome_channel"]:
                await interaction.response.send_message(
                    L(gid, "Primero elige un canal.", "Pick a channel first."), ephemeral=True)
                return
            await core.enviar_bienvenida(interaction.user, probar=True)
            await interaction.response.send_message(
                L(gid, "<:aceptado:1560557801464668240> Bienvenida de prueba enviada.",
                  "<:aceptado:1560557801464668240> Test welcome sent."), ephemeral=True)

        @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="Elegir canal de bienvenida",
                           channel_types=[discord.ChannelType.text], row=1)
        async def sel_canal(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            cfg(self.gid)["welcome_channel"] = select.values[0].id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.select(
            placeholder="Tipografía de la tarjeta…",
            min_values=1,
            max_values=1,
            row=2,
            options=[
                discord.SelectOption(label="Sistema (clara)", value="default", emoji="🔤"),
                discord.SelectOption(label="Black Gold", value="blackgold", emoji="✨"),
                discord.SelectOption(label="Black Gold cursiva", value="blackgold_italic", emoji="✒️"),
                discord.SelectOption(label="Retro Space", value="retro", emoji="🚀"),
                discord.SelectOption(label="Mojangles", value="mojangles", emoji="🎮"),
            ],
        )
        async def sel_fuente(self, interaction: discord.Interaction, select: discord.ui.Select):
            cfg(self.gid)["welcome_font"] = select.values[0]
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=3)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_welcome(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = WelcomePanelView(interaction.user.id, gid)
        await _enviar_panel(interaction, _embed_welcome(gid), view)


    @config.command(name="newaccounts", description="Alerta de cuentas nuevas")
    @app_commands.describe(activar="Activar alerta", dias="Edad mínima de cuenta en días (1-90)")
    @solo_admin()
    async def cfg_newaccounts(interaction: discord.Interaction, activar: bool | None = None,
                              dias: app_commands.Range[int, 1, 90] | None = None):
        gid = interaction.guild_id
        c = cfg(gid)
        if activar is not None:
            c["newacc_enabled"] = activar
        if dias is not None:
            c["newacc_days"] = dias
        guardar_db()
        await interaction.response.send_message(L(gid, "<:aceptado:1560557801464668240> Alerta de cuentas nuevas actualizada.",
                                                  "<:aceptado:1560557801464668240> New account alert updated."), ephemeral=True)


    @config.command(name="giveaway", description="Configura el tablero de juegos gratis (se actualiza cada 15 min)")
    @app_commands.describe(canal="Canal del tablero", plataforma="Filtro de plataforma",
                           desactivar="Desactivar el tablero")
    @app_commands.choices(plataforma=core.CHOICES_PLATAFORMA)
    @solo_admin()
    async def cfg_giveaway(interaction: discord.Interaction, canal: discord.TextChannel | None = None,
                           plataforma: app_commands.Choice[str] | None = None, desactivar: bool = False):
        gid = interaction.guild_id
        await interaction.response.defer(ephemeral=True)
        gw = cfg(gid)["giveaway"]
        if desactivar:
            gw["channel"] = None
            gw["message_id"] = None
            guardar_db()
            await interaction.followup.send(L(gid, "<:aceptado:1560557801464668240> Tablero desactivado.", "<:aceptado:1560557801464668240> Board disabled."))
            return
        if canal is not None:
            if gw["channel"] != canal.id:
                gw["message_id"] = None
            gw["channel"] = canal.id
        if plataforma is not None:
            gw["platform"] = plataforma.value
        guardar_db()
        if not gw["channel"]:
            await interaction.followup.send(L(gid, "Indica un canal.", "Provide a channel."))
            return
        try:
            await core.actualizar_tablero(gid)
        except Exception as e:
            await interaction.followup.send(L(gid, f"Config guardada, pero falló la actualización: {e}",
                                              f"Saved, but the update failed: {e}"))
            return
        await interaction.followup.send(L(gid, f"<:aceptado:1560557801464668240> Tablero activo en <#{gw['channel']}> ({gw['platform']}).",
                                          f"<:aceptado:1560557801464668240> Board active in <#{gw['channel']}> ({gw['platform']})."))





    # ----- Panel unificado /config panel -----
    def _embed_hub(gid: int) -> discord.Embed:
        e = discord.Embed(
            title=L(gid, "⚙️ Configuración del servidor", "⚙️ Server configuration"),
            description=L(
                gid,
                "**Menú principal de configuración de AegisBot.**\n\n"
                "Elige una sección para abrir su panel:\n"
                "seguridad, bienvenida, logs, presentación, tickets, sugerencias o roles por reacción.\n\n"
                "Atajos que siguen en `/config`: idioma, rol de moderador, canal de logs, palabras, etc.",
                "**Main AegisBot configuration menu.**\n\n"
                "Pick a section to open its panel:\n"
                "security, welcome, logs, introduction, tickets, suggestions or reaction roles.\n\n"
                "Shortcuts still under `/config`: language, mod role, log channel, words, etc.",
            ),
            color=discord.Color.blurple(),
        )
        e.add_field(
            name=L(gid, "Secciones", "Sections"),
            value=L(
                gid,
                "🛡️ AutoMod · 🔇 Anti-spam · 🚨 Anti-raid\n"
                "👋 Bienvenida · 📜 Logs · 🪪 Presentación\n"
                "🎫 Tickets · 💡 Sugerencias · 🏳️ Roles por reacción",
                "🛡️ AutoMod · 🔇 Anti-spam · 🚨 Anti-raid\n"
                "👋 Welcome · 📜 Logs · 🪪 Introduction\n"
                "🎫 Tickets · 💡 Suggestions · 🏳️ Reaction roles",
            ),
            inline=False,
        )
        return e

    class ConfigHubView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self.sel_seccion.placeholder = L(gid, "Elige una sección…", "Pick a section…")
            self.btn_cerrar.label = L(gid, "Cerrar", "Close")

        @discord.ui.select(
            placeholder="Elige una sección…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="AutoMod", value="automod", emoji="🛡️"),
                discord.SelectOption(label="Anti-spam", value="antispam", emoji="🔇"),
                discord.SelectOption(label="Anti-raid", value="antiraid", emoji="🚨"),
                discord.SelectOption(label="Bienvenida / Welcome", value="welcome", emoji="👋"),
                discord.SelectOption(label="Logs", value="logs", emoji="📜"),
                discord.SelectOption(label="Presentación / Intro", value="intro", emoji="🪪"),
                discord.SelectOption(label="Tickets", value="tickets", emoji="🎫"),
                discord.SelectOption(label="Sugerencias / Suggestions", value="sugerencias", emoji="💡"),
                discord.SelectOption(label="Roles por reacción", value="roles", emoji="🏳️"),
            ],
            row=0,
        )
        async def sel_seccion(self, interaction: discord.Interaction, select: discord.ui.Select):
            mapa = {
                "automod": "abrir_panel_automod",
                "antispam": "abrir_panel_antispam",
                "antiraid": "abrir_panel_antiraid",
                "welcome": "abrir_panel_welcome",
                "logs": "abrir_panel_logs",
                "intro": "abrir_panel_intro",
                "tickets": "abrir_panel_tickets",
                "sugerencias": "abrir_panel_sugerencias",
                "roles": "abrir_panel_roles",
            }
            attr = mapa.get(select.values[0])
            fn = getattr(core, attr, None) if attr else None
            if fn is None:
                await interaction.response.send_message(
                    L(self.gid, "Ese panel aún no está disponible (¿cog sin cargar?).",
                      "That panel is not available yet (cog not loaded?)."),
                    ephemeral=True,
                )
                return
            try:
                await interaction.response.edit_message(view=None)
            except discord.HTTPException:
                if not interaction.response.is_done():
                    await interaction.response.defer()
            await fn(interaction)

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=1)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)

    @config.command(name="panel", description="Configurar el servidor: seguridad, logs, tickets, bienvenida, roles…")
    @solo_admin()
    async def cfg_panel(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = ConfigHubView(interaction.user.id, gid)
        await interaction.response.send_message(embed=_embed_hub(gid), view=view, ephemeral=True)
        view.mensaje = await interaction.original_response()


    core.abrir_panel_antispam = abrir_panel_antispam
    core.abrir_panel_antiraid = abrir_panel_antiraid
    core.abrir_panel_automod = abrir_panel_automod
    core.abrir_panel_welcome = abrir_panel_welcome
    core.PanelView = PanelView
    core.NumeroModal = NumeroModal

