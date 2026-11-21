"""Roles por reacción (emojis/banderas) — muchos roles, como Carl-bot."""
from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

import core
from core import cfg, L, guardar_db, solo_admin, responder, PanelView, pedir_confirmacion


def _emoji_key(emoji: discord.PartialEmoji | discord.Emoji | str) -> str:
    if isinstance(emoji, str):
        return emoji
    if emoji.id:
        return f"{emoji.name}:{emoji.id}"
    return str(emoji)


def _parse_emoji(raw: str) -> str | None:
    """Acepta unicode (🇲🇽) o personalizado <:name:id> / <a:name:id>."""
    raw = raw.strip()
    if not raw:
        return None
    m = re.match(r"<a?:([A-Za-z0-9_]+):(\d+)>$", raw)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    # unicode / bandera
    return raw


def _emoji_for_react(key: str):
    """Objeto o str listo para message.add_reaction."""
    if ":" in key and key.rsplit(":", 1)[-1].isdigit():
        name, eid = key.rsplit(":", 1)
        return discord.PartialEmoji(name=name, id=int(eid))
    return key


def _emoji_shown(key: str) -> str:
    if ":" in key and key.rsplit(":", 1)[-1].isdigit():
        name, eid = key.rsplit(":", 1)
        return f"<:{name}:{eid}>"
    return key


async def setup(bot: commands.Bot):
    core.bot = bot

    def _store(gid: int) -> dict:
        return cfg(gid).setdefault("reaction_roles", {})

    def _embed_publico(gid: int, pairs: dict) -> discord.Embed:
        """Mensaje que ven los miembros: lista + reacciones debajo."""
        lineas = []
        for ek, rid in pairs.items():
            lineas.append(f"{_emoji_shown(ek)} → <@&{rid}>")
        nl = "\n"
        if cfg(gid).get("lang") == "en":
            intro = "React to choose your role." + nl + nl
            empty, title = ("—", "Roles")
        else:
            intro = "Reacciona para elegir tu rol." + nl + nl
            empty, title = ("—", "Roles")
        desc = intro + (nl.join(lineas) if lineas else empty)
        return discord.Embed(title=title, description=desc[:4000], color=discord.Color.blurple())

    async def _aplicar_reacciones(msg: discord.Message, pairs: dict) -> list:
        errores = []
        ya = set()
        for reac in msg.reactions:
            try:
                ya.add(_emoji_key(reac.emoji))
            except Exception:
                pass
        for key in pairs:
            if key in ya:
                continue
            candidatos = [_emoji_for_react(key)]
            # unicode puro por si PartialEmoji falla
            if isinstance(candidatos[0], str) is False:
                pass
            elif ":" not in key:
                candidatos.append(key)
            ok = False
            last_err = None
            for cand in candidatos:
                try:
                    await msg.add_reaction(cand)
                    ok = True
                    break
                except discord.HTTPException as e:
                    last_err = e
            if not ok:
                errores.append(f"{_emoji_shown(key)}: {last_err}")
        return errores

    async def _quitar_reaccion(msg: discord.Message, key: str):
        emoji = _emoji_for_react(key)
        try:
            await msg.clear_reaction(emoji)
        except discord.HTTPException:
            try:
                me = msg.guild.me if msg.guild else None
                if me is not None:
                    await msg.remove_reaction(emoji, me)
            except discord.HTTPException:
                pass

    async def _actualizar_mensaje_publico(guild: discord.Guild, msg_id: str):
        store = _store(guild.id)
        entry = store.get(msg_id)
        if not entry:
            return "no_entry"
        ch = guild.get_channel(entry.get("channel_id"))
        if not isinstance(ch, discord.TextChannel):
            return "no_channel"
        try:
            msg = await ch.fetch_message(int(msg_id))
        except discord.HTTPException:
            return "no_message"
        pairs = entry.get("pairs") or {}
        try:
            await msg.edit(embed=_embed_publico(guild.id, pairs))
        except discord.HTTPException as e:
            return f"edit:{e}"
        errs = await _aplicar_reacciones(msg, pairs)
        if errs:
            return "react:" + "; ".join(errs[:3])
        return None

    async def toggle_role(
        guild: discord.Guild,
        member: discord.Member,
        role_id: int,
        add: bool,
    ) -> str | None:
        rol = guild.get_role(role_id)
        if rol is None:
            return L(guild.id, "Ese rol ya no existe.", "That role no longer exists.")
        if rol.is_default() or rol.managed or rol >= guild.me.top_role:
            return L(guild.id, "No puedo gestionar ese rol.", "I can't manage that role.")
        try:
            if add and rol not in member.roles:
                await member.add_roles(rol, reason="AegisBot reaction role")
            elif not add and rol in member.roles:
                await member.remove_roles(rol, reason="AegisBot reaction role")
        except discord.HTTPException as e:
            return str(e)[:200]
        return None

    @bot.listen("on_raw_reaction_add")
    async def rr_add(payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == bot.user.id:
            return
        store = _store(payload.guild_id)
        entry = store.get(str(payload.message_id))
        if not entry:
            return
        pairs = entry.get("pairs") or {}
        key = _emoji_key(payload.emoji)
        role_id = pairs.get(key)
        if role_id is None:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        await toggle_role(guild, member, int(role_id), True)

    @bot.listen("on_raw_reaction_remove")
    async def rr_remove(payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == bot.user.id:
            return
        store = _store(payload.guild_id)
        entry = store.get(str(payload.message_id))
        if not entry:
            return
        pairs = entry.get("pairs") or {}
        key = _emoji_key(payload.emoji)
        role_id = pairs.get(key)
        if role_id is None:
            return
        guild = bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return
        await toggle_role(guild, member, int(role_id), False)

    # ----- Panel de configuración -----
    def _embed_rr(gid: int, msg_id: str | None) -> discord.Embed:
        store = _store(gid)
        e = discord.Embed(
            title=L(gid, "🏳️ Roles por reacción", "🏳️ Reaction roles"),
            color=discord.Color.blurple(),
        )
        if not msg_id or msg_id not in store:
            e.description = L(
                gid,
                "1. Elige un panel existente o **Nuevo panel**\n"
                "2. Elige el canal y publica el mensaje\n"
                "3. Elige rol y pon el emoji\n\n"
                "Puedes tener varios mensajes de roles a la vez.",
                "1. Pick an existing panel or **New panel**\n"
                "2. Pick the channel and post the message\n"
                "3. Pick role and set emoji\n\n"
                "You can have several role messages at once.",
            )
            return e
        entry = store[msg_id]
        pairs = entry.get("pairs") or {}
        lineas = []
        for ek, rid in list(pairs.items())[:40]:
            if ":" in ek and ek.rsplit(":", 1)[-1].isdigit():
                name, eid = ek.rsplit(":", 1)
                shown = f"<:{name}:{eid}>"
            else:
                shown = ek
            lineas.append(f"{shown} → <@&{rid}>")
        e.description = L(
            gid,
            f"Mensaje: `{msg_id}` · <#{entry.get('channel_id')}>\n"
            f"**{len(pairs)}** emoji(s) configurados:\n" + ("\n".join(lineas) or "—"),
            f"Message: `{msg_id}` · <#{entry.get('channel_id')}>\n"
            f"**{len(pairs)}** emoji(s) set:\n" + ("\n".join(lineas) or "—"),
        )
        if len(pairs) > 40:
            e.set_footer(text=L(gid, f"… y {len(pairs) - 40} más", f"… and {len(pairs) - 40} more"))
        else:
            e.set_footer(text=L(
                gid,
                "Poner/quitar emoji · Limpiar · Eliminar panel.",
                "Set/remove emoji · Clear · Delete panel.",
            ))
        return e



    class EmojiModal(discord.ui.Modal):
        def __init__(self, panel: "RRPanelView"):
            super().__init__(title=L(panel.gid, "Emoji o bandera", "Emoji or flag")[:45])
            self.panel = panel
            self.emoji_in = discord.ui.TextInput(
                label=L(panel.gid, "Emoji o bandera", "Emoji or flag")[:45],
                placeholder="🇲🇽  ·  <:custom:123>",
                max_length=80,
            )
            self.add_item(self.emoji_in)

        async def on_submit(self, interaction: discord.Interaction):
            gid = self.panel.gid
            g = interaction.guild
            nl = chr(10)
            if not self.panel.msg_id:
                await interaction.response.send_message(
                    L(gid, "Primero tienes que publicar el mensaje (botón Publicar mensaje).",
                      "Post the message first (Post message button)."),
                    ephemeral=True,
                )
                return
            if not self.panel.rol_id:
                await interaction.response.send_message(
                    L(gid, "Elige un rol en el menu Elegir rol.",
                      "Pick a role in the Pick role menu."),
                    ephemeral=True,
                )
                return
            key = _parse_emoji(self.emoji_in.value)
            if not key:
                await interaction.response.send_message(
                    L(gid, "Emoji no válido.",
                      "Invalid emoji."),
                    ephemeral=True,
                )
                return
            rol = g.get_role(self.panel.rol_id) if g else None
            if rol is None or rol.is_default() or rol.managed:
                await interaction.response.send_message(
                    L(gid, "No puedo usar ese rol.", "I can't use that role."),
                    ephemeral=True,
                )
                return
            if g and rol >= g.me.top_role:
                await interaction.response.send_message(
                    L(gid, "Ese rol está por encima del bot.",
                      "That role is above the bot."),
                    ephemeral=True,
                )
                return
            store = _store(gid)
            entry = store.get(self.panel.msg_id)
            if not entry:
                await interaction.response.send_message(
                    L(gid, "Mensaje no encontrado. Vuelve a publicar el mensaje.",
                      "Message not found. Post the message again."),
                    ephemeral=True,
                )
                return
            entry.setdefault("pairs", {})[key] = rol.id
            guardar_db()
            err = await _actualizar_mensaje_publico(g, self.panel.msg_id)
            # Actualizar panel config
            try:
                await interaction.response.edit_message(
                    embed=_embed_rr(gid, self.panel.msg_id), view=self.panel
                )
            except discord.HTTPException:
                await interaction.response.send_message("OK", ephemeral=True)
            if err is None:
                texto = f"<:aceptado:1560557801464668240> {self.emoji_in.value} → {rol.mention}"
            else:
                texto = L(
                    gid,
                    f"Guardado, pero no pude añadir la reacción (`{err}`). "
                    f"Revisa permisos del bot en el canal (añadir reacciones).",
                    f"Saved, but couldn't add the reaction (`{err}`). "
                    f"Check the bot can add reactions in that channel.",
                )
            try:
                await interaction.followup.send(texto, ephemeral=True)
            except discord.HTTPException:
                pass

    class RRPanelView(PanelView):
        def __init__(self, autor_id: int, gid: int, msg_id: str | None = None):
            super().__init__(autor_id, gid)
            self.msg_id: str | None = None
            self.canal_id: int | None = None
            self.rol_id: int | None = None
            store = _store(gid)
            if msg_id and msg_id in store:
                self.msg_id = msg_id
                self.canal_id = store[msg_id].get("channel_id")
            elif store:
                self.msg_id = next(iter(store.keys()))
                self.canal_id = store[self.msg_id].get("channel_id")
            self._rellenar_sel_panel()
            self._sync()

        def _rellenar_sel_panel(self):
            """Opciones del selector de paneles (mensajes publicados + Nuevo)."""
            store = _store(self.gid)
            opciones = []
            for mid, entry in list(store.items())[:24]:
                ch = entry.get("channel_id")
                n = len(entry.get("pairs") or {})
                label = L(
                    self.gid,
                    f"Panel …{mid[-6:]} ({n} emoji)",
                    f"Panel …{mid[-6:]} ({n} emoji)",
                )[:100]
                desc = f"#{ch}" if ch else "—"
                opciones.append(discord.SelectOption(
                    label=label,
                    value=mid,
                    description=desc[:100],
                    default=(mid == self.msg_id),
                ))
            opciones.append(discord.SelectOption(
                label=L(self.gid, "＋ Nuevo panel", "＋ New panel")[:100],
                value="__new__",
                description=L(self.gid, "Publicar un mensaje nuevo", "Post a new message")[:100],
                default=(self.msg_id is None and not store),
            ))
            self.sel_panel.options = opciones
            self.sel_panel.placeholder = L(
                self.gid, "Elegir panel (mensaje)…", "Pick panel (message)…"
            )

        def _sync(self):
            self._rellenar_sel_panel()
            self.btn_publicar.label = L(self.gid, "Publicar mensaje", "Post message")
            self.btn_anadir.label = L(self.gid, "Poner emoji", "Set emoji")
            self.btn_quitar.label = L(self.gid, "Quitar emoji", "Remove emoji")
            self.btn_quitar_rol.label = L(self.gid, "Quitar por rol", "Remove by role")
            self.btn_limpiar.label = L(self.gid, "Limpiar todos", "Clear all")
            self.btn_eliminar.label = L(self.gid, "Eliminar panel", "Delete panel")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")
            self.sel_canal.placeholder = L(self.gid, "Canal del mensaje…", "Message channel…")
            self.sel_rol.placeholder = L(self.gid, "Elegir rol…", "Pick role…")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    embed=_embed_rr(self.gid, self.msg_id), view=self
                )
            else:
                await interaction.response.edit_message(
                    embed=_embed_rr(self.gid, self.msg_id), view=self
                )

        @discord.ui.select(
            placeholder="Elegir panel (mensaje)…",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="—", value="__new__")],
            row=0,
        )
        async def sel_panel(self, interaction: discord.Interaction, select: discord.ui.Select):
            val = select.values[0]
            store = _store(self.gid)
            if val == "__new__":
                self.msg_id = None
                self.canal_id = None
                await interaction.response.edit_message(
                    embed=_embed_rr(self.gid, None), view=self
                )
                await interaction.followup.send(
                    L(self.gid, "Modo **nuevo panel**: elige canal y pulsa **Publicar mensaje**.",
                      "Mode **new panel**: pick a channel and tap **Post message**."),
                    ephemeral=True,
                )
                return
            if val not in store:
                await interaction.response.send_message(
                    L(self.gid, "Ese panel ya no existe.", "That panel no longer exists."),
                    ephemeral=True,
                )
                return
            self.msg_id = val
            self.canal_id = store[val].get("channel_id")
            self._sync()
            await interaction.response.edit_message(
                embed=_embed_rr(self.gid, self.msg_id), view=self
            )

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal del mensaje…",
            channel_types=[discord.ChannelType.text],
            row=1,
        )
        async def sel_canal(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            self.canal_id = select.values[0].id
            await interaction.response.defer()
            await interaction.followup.send(
                L(self.gid, f"Canal: <#{self.canal_id}>. Pulsa **Publicar mensaje**.",
                  f"Channel: <#{self.canal_id}>. Tap **Post message**."),
                ephemeral=True,
            )

        @discord.ui.select(
            cls=discord.ui.RoleSelect,
            placeholder="Elegir rol…",
            row=2,
        )
        async def sel_rol(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
            rol = select.values[0]
            self.rol_id = rol.id
            await interaction.response.defer()
            await interaction.followup.send(
                L(self.gid, f"Rol elegido: {rol.mention}. Ahora **Poner emoji**.",
                  f"Role selected: {rol.mention}. Now **Set emoji**."),
                ephemeral=True,
            )

        @discord.ui.button(label="Publicar mensaje", style=discord.ButtonStyle.primary, row=3)
        async def btn_publicar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            if not self.canal_id:
                await interaction.response.send_message(
                    L(gid, "Elige un canal primero.", "Pick a channel first."),
                    ephemeral=True,
                )
                return
            canal = g.get_channel(self.canal_id) if g else None
            if not isinstance(canal, discord.TextChannel):
                await interaction.response.send_message(
                    L(gid, "Canal no válido.", "Invalid channel."), ephemeral=True
                )
                return
            embed = _embed_publico(gid, {})
            try:
                msg = await canal.send(embed=embed)
            except discord.HTTPException as e:
                await interaction.response.send_message(
                    L(gid, f"No pude publicar: {e}", f"Could not post: {e}"),
                    ephemeral=True,
                )
                return
            store = _store(gid)
            store[str(msg.id)] = {"channel_id": canal.id, "pairs": {}}
            self.msg_id = str(msg.id)
            guardar_db()
            await self.actualizar(interaction)
            await interaction.followup.send(
                L(gid, f"Mensaje publicado en {canal.mention}. Elige un rol y pon el emoji.",
                  f"Message posted in {canal.mention}. Pick a role and set the emoji."),
                ephemeral=True,
            )

        @discord.ui.button(label="Poner emoji", style=discord.ButtonStyle.success, row=3)
        async def btn_anadir(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not self.msg_id:
                await interaction.response.send_message(
                    L(self.gid, "Primero publica el mensaje con el botón Publicar mensaje.",
                      "Post the message first with the Post message button."),
                    ephemeral=True,
                )
                return
            if not self.rol_id:
                await interaction.response.send_message(
                    L(self.gid, "Elige un rol en el menú **Elegir rol**.",
                      "Pick a role in the **Pick role** menu."),
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(EmojiModal(self))

        @discord.ui.button(label="Quitar emoji", style=discord.ButtonStyle.danger, row=3)
        async def btn_quitar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            if not self.msg_id:
                await interaction.response.send_message(
                    L(gid, "No hay mensaje configurado.", "No message configured."),
                    ephemeral=True,
                )
                return
            store = _store(gid)
            entry = store.get(self.msg_id) or {}
            pairs = entry.get("pairs") or {}
            if not pairs:
                await interaction.response.send_message(
                    L(gid, "No hay emojis que quitar.", "No emojis to remove."),
                    ephemeral=True,
                )
                return
            options = []
            for ek, rid in list(pairs.items())[:25]:
                shown = _emoji_shown(ek)
                rol = g.get_role(int(rid)) if g else None
                nombre = rol.name if rol else str(rid)
                label = f"{shown} → {nombre}"[:100]
                if not label.strip():
                    label = f"emoji → {nombre}"[:100]
                options.append(discord.SelectOption(
                    label=label,
                    value=ek[:100],
                    description=f"ID {rid}"[:100],
                ))
            view = discord.ui.View(timeout=120)
            sel = discord.ui.Select(
                placeholder=L(gid, "Elige el emoji a quitar…", "Pick emoji to remove…"),
                options=options,
            )

            async def _on_select(inter: discord.Interaction):
                if inter.user.id != self.autor_id:
                    await inter.response.send_message(
                        L(gid, "Este panel no es tuyo.", "This panel is not yours."),
                        ephemeral=True,
                    )
                    return
                key = sel.values[0]
                ent = _store(gid).get(self.msg_id)
                if not ent or key not in (ent.get("pairs") or {}):
                    await inter.response.send_message(
                        L(gid, "Ese emoji ya no está.", "That emoji is gone."),
                        ephemeral=True,
                    )
                    return
                ent["pairs"].pop(key, None)
                guardar_db()
                gg = inter.guild
                if gg:
                    await _actualizar_mensaje_publico(gg, self.msg_id)
                    ch = gg.get_channel(ent.get("channel_id"))
                    if isinstance(ch, discord.TextChannel):
                        try:
                            msg = await ch.fetch_message(int(self.msg_id))
                            await _quitar_reaccion(msg, key)
                        except discord.HTTPException:
                            pass
                await inter.response.edit_message(
                    content=L(
                        gid,
                        f"<:aceptado:1560557801464668240> Quitado: {_emoji_shown(key)}",
                        f"<:aceptado:1560557801464668240> Removed: {_emoji_shown(key)}",
                    ),
                    view=None,
                )
                try:
                    if self.mensaje:
                        await self.mensaje.edit(embed=_embed_rr(gid, self.msg_id), view=self)
                except discord.HTTPException:
                    pass

            sel.callback = _on_select
            view.add_item(sel)
            await interaction.response.send_message(
                L(gid, "¿Qué emoji quieres quitar?", "Which emoji do you want to remove?"),
                view=view,
                ephemeral=True,
            )

        @discord.ui.button(label="Quitar por rol", style=discord.ButtonStyle.danger, row=4)
        async def btn_quitar_rol(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            if not self.msg_id:
                await interaction.response.send_message(
                    L(gid, "No hay mensaje configurado.", "No message configured."),
                    ephemeral=True,
                )
                return
            if not self.rol_id:
                await interaction.response.send_message(
                    L(gid, "Elige primero el rol en el menú **Elegir rol**.",
                      "Pick the role first in the **Pick role** menu."),
                    ephemeral=True,
                )
                return
            store = _store(gid)
            entry = store.get(self.msg_id) or {}
            pairs = entry.get("pairs") or {}
            a_borrar = [ek for ek, rid in pairs.items() if int(rid) == int(self.rol_id)]
            if not a_borrar:
                await interaction.response.send_message(
                    L(gid, "Ese rol no tiene ningún emoji asignado en este mensaje.",
                      "That role has no emoji on this message."),
                    ephemeral=True,
                )
                return
            for ek in a_borrar:
                pairs.pop(ek, None)
            guardar_db()
            if g:
                await _actualizar_mensaje_publico(g, self.msg_id)
                ch = g.get_channel(entry.get("channel_id"))
                if isinstance(ch, discord.TextChannel):
                    try:
                        msg = await ch.fetch_message(int(self.msg_id))
                        for ek in a_borrar:
                            await _quitar_reaccion(msg, ek)
                    except discord.HTTPException:
                        pass
            rol = g.get_role(self.rol_id) if g else None
            nombre = rol.mention if rol else str(self.rol_id)
            await interaction.response.edit_message(
                embed=_embed_rr(gid, self.msg_id), view=self
            )
            try:
                await interaction.followup.send(
                    L(gid, f"<:aceptado:1560557801464668240> Quitados {len(a_borrar)} emoji(s) del rol {nombre}.",
                      f"<:aceptado:1560557801464668240> Removed {len(a_borrar)} emoji(s) from role {nombre}."),
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

        @discord.ui.button(label="Limpiar todos", style=discord.ButtonStyle.danger, row=4)
        async def btn_limpiar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            if not self.msg_id:
                await interaction.response.send_message(
                    L(gid, "No hay mensaje configurado.", "No message configured."),
                    ephemeral=True,
                )
                return
            store = _store(gid)
            entry = store.get(self.msg_id) or {}
            pairs = entry.get("pairs") or {}
            if not pairs:
                await interaction.response.send_message(
                    L(gid, "No hay nada que limpiar.", "Nothing to clear."),
                    ephemeral=True,
                )
                return
            n = len(pairs)
            if not await pedir_confirmacion(interaction, L(
                    gid,
                    f"⚠️ Se quitarán **{n}** emoji(s)/rol(es) de este panel. **No se puede deshacer** desde aquí.",
                    f"⚠️ **{n}** emoji(s)/role(s) will be removed from this panel. **This can't be undone** here.")):
                return
            entry = _store(gid).get(self.msg_id) or {}
            pairs = entry.get("pairs") or {}
            keys = list(pairs.keys())
            entry["pairs"] = {}
            guardar_db()
            if g:
                await _actualizar_mensaje_publico(g, self.msg_id)
                ch = g.get_channel(entry.get("channel_id"))
                if isinstance(ch, discord.TextChannel):
                    try:
                        msg = await ch.fetch_message(int(self.msg_id))
                        for ek in keys:
                            await _quitar_reaccion(msg, ek)
                    except discord.HTTPException:
                        pass
            try:
                if self.mensaje:
                    await self.mensaje.edit(embed=_embed_rr(gid, self.msg_id), view=self)
            except discord.HTTPException:
                pass
            try:
                await interaction.followup.send(
                    L(gid, f"<:aceptado:1560557801464668240> Se quitaron {len(keys)} emoji(s).",
                      f"<:aceptado:1560557801464668240> Removed {len(keys)} emoji(s)."),
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

        @discord.ui.button(label="Eliminar panel", style=discord.ButtonStyle.danger, row=4)
        async def btn_eliminar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            if not self.msg_id:
                await interaction.response.send_message(
                    L(gid, "No hay panel seleccionado.", "No panel selected."),
                    ephemeral=True,
                )
                return
            mid = self.msg_id
            if not await pedir_confirmacion(interaction, L(
                    gid,
                    f"⚠️ Se **borrará el mensaje público** del canal y se eliminará este panel de la base de datos "
                    f"(mensaje `{mid}`). **No se puede deshacer.**",
                    f"⚠️ The **public message** will be deleted and this panel will be removed from the database "
                    f"(message `{mid}`). **This can't be undone.**")):
                return
            store = _store(gid)
            entry = store.pop(mid, None) or {}
            guardar_db()
            # Borrar mensaje público
            if g and entry.get("channel_id"):
                ch = g.get_channel(entry.get("channel_id"))
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    try:
                        msg = await ch.fetch_message(int(mid))
                        await msg.delete()
                    except discord.NotFound:
                        pass
                    except discord.HTTPException as e:
                        try:
                            await interaction.followup.send(
                                L(gid, f"Panel quitado de la config, pero no pude borrar el mensaje: {e}",
                                  f"Panel removed from config, but I couldn't delete the message: {e}"),
                                ephemeral=True,
                            )
                        except discord.HTTPException:
                            pass
            self.msg_id = None
            self.canal_id = None
            self._sync()
            try:
                if self.mensaje:
                    await self.mensaje.edit(embed=_embed_rr(gid, None), view=self)
            except discord.HTTPException:
                pass
            try:
                await interaction.followup.send(
                    L(gid, "<:aceptado:1560557801464668240> Panel eliminado (mensaje + datos).",
                      "<:aceptado:1560557801464668240> Panel deleted (message + data)."),
                    ephemeral=True,
                )
            except discord.HTTPException:
                pass

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=4)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_roles(interaction: discord.Interaction, msg_id: str | None = None):
        gid = interaction.guild_id
        view = RRPanelView(interaction.user.id, gid, msg_id=msg_id)
        embed = _embed_rr(gid, view.msg_id)
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.mensaje = msg
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.mensaje = await interaction.original_response()


    core.abrir_panel_roles = abrir_panel_roles

    # Atajo: añadir un par sin panel (útil para muchas banderas seguidas)
    @bot.tree.command(
        name="rolreaccion",
        description="Añade un emoji+rol a un mensaje de roles por reacción",
    )
    @app_commands.describe(
        mensaje="ID o enlace del mensaje del bot",
        emoji="Emoji o bandera (🇲🇽)",
        rol="Rol a asignar",
    )
    @app_commands.guild_only()
    @solo_admin()
    async def rolreaccion(
        interaction: discord.Interaction,
        mensaje: str,
        emoji: str,
        rol: discord.Role,
    ):
        gid = interaction.guild_id
        g = interaction.guild
        # Parse message id from link or raw id
        m = re.search(r"/messages/(\d+)", mensaje) or re.search(r"^(\d+)$", mensaje.strip())
        if not m:
            await responder(
                interaction,
                L(gid, "Pega el ID del mensaje o el enlace de Discord.",
                  "Paste the message ID or Discord message link."),
                ephemeral=True,
            )
            return
        mid = m.group(1)
        key = _parse_emoji(emoji)
        if not key:
            await responder(interaction, L(gid, "Emoji inválido.", "Invalid emoji."), ephemeral=True)
            return
        if rol.is_default() or rol.managed or rol >= g.me.top_role:
            await responder(
                interaction,
                L(gid, "No puedo usar ese rol.", "I can't use that role."),
                ephemeral=True,
            )
            return
        store = _store(gid)
        entry = store.get(mid)
        if not entry:
            # intentar localizar el mensaje en el canal actual
            ch = interaction.channel
            try:
                msg = await ch.fetch_message(int(mid))
            except (discord.HTTPException, ValueError):
                await responder(
                    interaction,
                    L(gid, "Mensaje no registrado. Usa /rolespanel → Publicar mensaje primero, "
                      "o ejecuta el comando en el canal del mensaje.",
                      "Message not registered. Use /rolespanel → Post message first, "
                      "or run this in the message channel."),
                    ephemeral=True,
                )
                return
            entry = {"channel_id": ch.id, "pairs": {}}
            store[mid] = entry
        entry.setdefault("pairs", {})[key] = rol.id
        guardar_db()
        err = await _actualizar_mensaje_publico(g, mid)
        extra = (f"\n⚠ {err}" if err and str(err).startswith("react:") else "")
        await responder(
            interaction,
            L(gid, f"<:aceptado:1560557801464668240> {emoji} → {rol.mention}{extra}",
              f"<:aceptado:1560557801464668240> {emoji} → {rol.mention}{extra}"),
            ephemeral=True,
        )
