"""Sistema de sugerencias."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import core
from core import cfg, L, guardar_db, solo_admin, responder, PanelView, _si_no


async def setup(bot: commands.Bot):
    core.bot = bot

    def _sug(gid: int) -> dict:
        return cfg(gid).setdefault(
            "suggestions",
            {"enabled": False, "channel": None, "counter": 0, "anonymous": False},
        )

    class SuggestModal(discord.ui.Modal):
        def __init__(self, gid: int):
            super().__init__(title=L(gid, "Nueva sugerencia", "New suggestion")[:45])
            self.gid = gid
            self.texto = discord.ui.TextInput(
                label=L(gid, "Sugerencia", "Suggestion")[:45],
                style=discord.TextStyle.paragraph,
                required=True,
                max_length=1000,
                placeholder=L(gid, "Describe tu idea…", "Describe your idea…")[:100],
            )
            self.add_item(self.texto)

        async def on_submit(self, interaction: discord.Interaction):
            await publicar_sugerencia(interaction, self.texto.value.strip())

    class SuggestPanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="💡 Sugerir / Suggest",
            style=discord.ButtonStyle.primary,
            custom_id="aegis:suggest:open",
        )
        async def abrir(self, interaction: discord.Interaction, button: discord.ui.Button):
            g = interaction.guild
            if g is None:
                await interaction.response.send_message("Solo en servidores.", ephemeral=True)
                return
            s = _sug(g.id)
            if not s.get("enabled") or not s.get("channel"):
                await interaction.response.send_message(
                    L(g.id, "Las sugerencias no están activas.", "Suggestions are not enabled."),
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(SuggestModal(g.id))

    class SuggestStaffView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="✅",
            style=discord.ButtonStyle.success,
            custom_id="aegis:suggest:ok",
        )
        async def aceptar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await marcar_sugerencia(interaction, "accepted")

        @discord.ui.button(
            label="❌",
            style=discord.ButtonStyle.danger,
            custom_id="aegis:suggest:no",
        )
        async def rechazar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await marcar_sugerencia(interaction, "rejected")

    async def marcar_sugerencia(interaction: discord.Interaction, estado: str):
        g = interaction.guild
        u = interaction.user
        if g is None or not isinstance(u, discord.Member):
            return
        from core import es_mod
        if not (es_mod(u) or u.guild_permissions.manage_messages):
            await interaction.response.send_message(
                L(g.id, "Solo el staff puede hacer esto.", "Staff only."),
                ephemeral=True,
            )
            return
        msg = interaction.message
        if msg is None or not msg.embeds:
            await interaction.response.send_message("—", ephemeral=True)
            return
        emb = msg.embeds[0]
        if estado == "accepted":
            emb.color = discord.Color.green()
            emb.set_footer(text=L(g.id, f"Aceptada por {u}", f"Accepted by {u}"))
        else:
            emb.color = discord.Color.red()
            emb.set_footer(text=L(g.id, f"Rechazada por {u}", f"Rejected by {u}"))
        try:
            await msg.edit(embed=emb, view=None)
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            L(g.id, "Actualizado.", "Updated."), ephemeral=True
        )

    async def publicar_sugerencia(interaction: discord.Interaction, texto: str):
        g = interaction.guild
        u = interaction.user
        if g is None or not isinstance(u, discord.Member):
            await interaction.response.send_message("Solo en servidores.", ephemeral=True)
            return
        gid = g.id
        s = _sug(gid)
        canal = g.get_channel(s["channel"]) if s.get("channel") else None
        if not isinstance(canal, discord.TextChannel):
            await interaction.response.send_message(
                L(gid, "No hay canal de sugerencias.", "No suggestions channel."),
                ephemeral=True,
            )
            return
        s["counter"] = int(s.get("counter") or 0) + 1
        n = s["counter"]
        guardar_db()
        autor = L(gid, "Anónimo", "Anonymous") if s.get("anonymous") else f"{u.mention} (`{u.id}`)"
        emb = discord.Embed(
            title=L(gid, f"💡 Sugerencia #{n}", f"💡 Suggestion #{n}"),
            description=texto[:4000],
            color=discord.Color.gold(),
        )
        emb.add_field(name=L(gid, "Autor", "Author"), value=autor, inline=False)
        try:
            msg = await canal.send(embed=emb, view=SuggestStaffView())
            try:
                await msg.add_reaction("✅")
                await msg.add_reaction("❌")
            except discord.HTTPException:
                pass
        except discord.HTTPException as e:
            await interaction.response.send_message(
                L(gid, f"No pude publicar: {e}", f"Could not post: {e}"),
                ephemeral=True,
            )
            return
        if not interaction.response.is_done():
            await interaction.response.send_message(
                L(gid, f"Sugerencia enviada: {msg.jump_url}",
                  f"Suggestion sent: {msg.jump_url}"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                L(gid, f"Sugerencia enviada: {msg.jump_url}",
                  f"Suggestion sent: {msg.jump_url}"),
                ephemeral=True,
            )

    def _embed_cfg(gid: int) -> discord.Embed:
        s = _sug(gid)
        ch = f"<#{s['channel']}>" if s.get("channel") else "—"
        e = discord.Embed(
            title=L(gid, "💡 Sugerencias", "💡 Suggestions"),
            color=discord.Color.gold(),
        )
        e.add_field(name=L(gid, "Activo", "Enabled"), value=_si_no(s.get("enabled")))
        e.add_field(name=L(gid, "Canal", "Channel"), value=ch)
        e.add_field(name=L(gid, "Anónimo", "Anonymous"), value=_si_no(s.get("anonymous")))
        e.add_field(name=L(gid, "Total", "Total"), value=str(s.get("counter") or 0))
        e.set_footer(text=L(
            gid,
            "Todo desde este panel. Los miembros usan el botón del panel público o /sugerir.",
            "Everything from this panel. Members use the public panel button or /sugerir.",
        ))
        return e

    class SugConfigView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self.pub_channel_id: int | None = None
            self._sync()

        def _sync(self):
            s = _sug(self.gid)
            self.btn_toggle.label = L(
                self.gid,
                "Desactivar" if s.get("enabled") else "Activar",
                "Disable" if s.get("enabled") else "Enable",
            )
            self.btn_toggle.style = (
                discord.ButtonStyle.danger if s.get("enabled") else discord.ButtonStyle.success
            )
            self.btn_anon.label = L(
                self.gid,
                "Anónimo: sí" if s.get("anonymous") else "Anónimo: no",
                "Anonymous: on" if s.get("anonymous") else "Anonymous: off",
            )
            self.btn_pub.label = L(self.gid, "Publicar panel", "Post panel")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")
            self.sel_canal.placeholder = L(self.gid, "Canal de sugerencias…", "Suggestions channel…")
            self.sel_pub.placeholder = L(self.gid, "Canal del panel…", "Panel channel…")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_cfg(self.gid), view=self)

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal de sugerencias…",
            channel_types=[discord.ChannelType.text],
            row=0,
        )
        async def sel_canal(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            _sug(self.gid)["channel"] = select.values[0].id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal del panel…",
            channel_types=[discord.ChannelType.text],
            row=1,
        )
        async def sel_pub(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            self.pub_channel_id = select.values[0].id
            await interaction.response.defer()
            await interaction.followup.send(
                L(self.gid, f"Panel en <#{self.pub_channel_id}>.",
                  f"Panel in <#{self.pub_channel_id}>."),
                ephemeral=True,
            )

        @discord.ui.button(label="Activar", style=discord.ButtonStyle.success, row=2)
        async def btn_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
            s = _sug(self.gid)
            if not s.get("enabled") and not s.get("channel"):
                await interaction.response.send_message(
                    L(self.gid, "Elige un canal primero.", "Pick a channel first."),
                    ephemeral=True,
                )
                return
            s["enabled"] = not s.get("enabled")
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Anónimo: no", style=discord.ButtonStyle.secondary, row=2)
        async def btn_anon(self, interaction: discord.Interaction, button: discord.ui.Button):
            s = _sug(self.gid)
            s["anonymous"] = not s.get("anonymous")
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Publicar panel", style=discord.ButtonStyle.primary, row=2)
        async def btn_pub(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            ch_id = self.pub_channel_id or _sug(gid).get("channel") or interaction.channel_id
            canal = g.get_channel(ch_id) if g else None
            if not isinstance(canal, discord.TextChannel):
                await interaction.response.send_message(
                    L(gid, "Elige un canal de texto.", "Pick a text channel."),
                    ephemeral=True,
                )
                return
            emb = discord.Embed(
                title=L(gid, "💡 Sugerencias", "💡 Suggestions"),
                description=L(
                    gid,
                    "Pulsa el botón para enviar una sugerencia al staff.",
                    "Press the button to send a suggestion to staff.",
                ),
                color=discord.Color.gold(),
            )
            try:
                await canal.send(embed=emb, view=SuggestPanelView())
            except discord.HTTPException as e:
                await interaction.response.send_message(str(e)[:200], ephemeral=True)
                return
            await interaction.response.send_message(
                L(gid, f"Panel publicado en {canal.mention}.",
                  f"Panel posted in {canal.mention}."),
                ephemeral=True,
            )

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=2)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)

    async def abrir_panel_sugerencias(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = SugConfigView(interaction.user.id, gid)
        embed = _embed_cfg(gid)
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.mensaje = msg
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.mensaje = await interaction.original_response()


    core.abrir_panel_sugerencias = abrir_panel_sugerencias

    @bot.tree.command(name="sugerir", description="Envía una sugerencia")
    @app_commands.guild_only()
    async def cmd_sugerir(interaction: discord.Interaction):
        g = interaction.guild
        s = _sug(g.id)
        if not s.get("enabled") or not s.get("channel"):
            await interaction.response.send_message(
                L(g.id, "Las sugerencias no están activas.", "Suggestions are not enabled."),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(SuggestModal(g.id))

    # Vistas persistentes
    bot.add_view(SuggestPanelView())
    bot.add_view(SuggestStaffView())
    core.SuggestPanelView = SuggestPanelView
    core.SuggestStaffView = SuggestStaffView
