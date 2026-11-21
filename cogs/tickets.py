"""Tickets potentes: motivo al abrir, reclamar, auto-cierre por inactividad."""
from __future__ import annotations

import asyncio
import io
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import core
from core import (
    DB, cfg, L, guardar_db,
    es_mod, solo_admin,
    responder, registrar,
    TICKET_LOCKS, _lock_tickets, _si_no,
    PanelView, NumeroModal,
)


async def setup(bot: commands.Bot):
    core.bot = bot
    config = core.config_group

    class TicketReasonModal(discord.ui.Modal):
        def __init__(self, title: str):
            super().__init__(title=title)
            self.motivo = discord.ui.TextInput(
                label="Motivo / Reason",
                style=discord.TextStyle.paragraph,
                placeholder="Describe brevemente tu problema…",
                required=True,
                max_length=500,
            )
            self.add_item(self.motivo)

        async def on_submit(self, interaction: discord.Interaction):
            await crear_ticket(interaction, self.motivo.value.strip(), prioridad="normal")

    class TicketReasonSelectView(discord.ui.View):
        def __init__(self, reasons: list[str], gid: int):
            super().__init__(timeout=120)
            self.gid = gid
            opts = []
            for i, r in enumerate(reasons[:25]):
                opts.append(discord.SelectOption(label=r[:100], value=str(i)))
            sel = discord.ui.Select(
                placeholder=L(gid, "Elige el motivo…", "Pick a reason…"),
                options=opts,
            )

            async def _cb(interaction: discord.Interaction):
                idx = int(sel.values[0])
                motivo = reasons[idx]
                await crear_ticket(interaction, motivo, prioridad="normal")

            sel.callback = _cb
            self.add_item(sel)

    class TicketPanelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="🎫 Abrir ticket / Open ticket",
            style=discord.ButtonStyle.primary,
            custom_id="aegis:ticket:open",
        )
        async def abrir(self, interaction: discord.Interaction, button: discord.ui.Button):
            g = interaction.guild
            if g is None:
                await interaction.response.send_message("Solo en servidores.", ephemeral=True)
                return
            tk = cfg(g.id)["tickets"]
            reasons = [r for r in (tk.get("reasons") or []) if r]
            if reasons:
                await interaction.response.send_message(
                    L(g.id, "Elige el motivo del ticket:", "Pick the ticket reason:"),
                    view=TicketReasonSelectView(reasons, g.id),
                    ephemeral=True,
                )
            elif tk.get("require_reason", True):
                await interaction.response.send_modal(
                    TicketReasonModal(L(g.id, "Abrir ticket", "Open ticket"))
                )
            else:
                await crear_ticket(interaction, None, prioridad="normal")

    class TicketCloseReasonModal(discord.ui.Modal):
        def __init__(self, gid: int):
            super().__init__(title=L(gid, "Cerrar ticket", "Close ticket")[:45])
            self.motivo = discord.ui.TextInput(
                label=L(gid, "Motivo del cierre", "Close reason")[:45],
                style=discord.TextStyle.short,
                required=False,
                max_length=200,
                placeholder=L(gid, "Opcional…", "Optional…")[:80],
            )
            self.add_item(self.motivo)

        async def on_submit(self, interaction: discord.Interaction):
            await cerrar_ticket(interaction, cierre_motivo=self.motivo.value.strip() or None)

    class TicketControlsView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="🙋 Reclamar / Claim",
            style=discord.ButtonStyle.success,
            custom_id="aegis:ticket:claim",
        )
        async def reclamar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await reclamar_ticket(interaction)

        @discord.ui.button(
            label="⬆️ Prioridad",
            style=discord.ButtonStyle.secondary,
            custom_id="aegis:ticket:prio",
        )
        async def prioridad(self, interaction: discord.Interaction, button: discord.ui.Button):
            await cambiar_prioridad(interaction)

        @discord.ui.button(
            label="🔒 Cerrar / Close",
            style=discord.ButtonStyle.danger,
            custom_id="aegis:ticket:close",
        )
        async def cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            g = interaction.guild
            if g is None:
                await interaction.response.send_message("Solo en servidores.", ephemeral=True)
                return
            await interaction.response.send_modal(TicketCloseReasonModal(g.id))

    # Compat: vista antigua solo-cerrar
    class TicketCloseView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="🔒 Cerrar / Close",
            style=discord.ButtonStyle.danger,
            custom_id="aegis:ticket:close",
        )
        async def cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await cerrar_ticket(interaction)

    async def crear_ticket(interaction: discord.Interaction, motivo: str | None, prioridad: str = "normal"):
        g = interaction.guild
        u = interaction.user
        if g is None or not isinstance(u, discord.Member):
            await interaction.response.send_message("Solo en servidores.", ephemeral=True)
            return
        gid = g.id
        tk = cfg(gid)["tickets"]
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        marca = f"aegis-ticket:{u.id}"
        categoria = g.get_channel(tk["category"]) if tk["category"] else None
        if not isinstance(categoria, discord.CategoryChannel):
            categoria = None
        rol = g.get_role(tk["support_role"]) if tk["support_role"] else None

        overwrites = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            u: discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True,
            ),
            g.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True,
                read_message_history=True, embed_links=True, attach_files=True,
            ),
        }
        if rol:
            overwrites[rol] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True,
            )

        async with _lock_tickets(gid):
            for ch in g.text_channels:
                if ch.topic == marca:
                    await interaction.followup.send(
                        L(gid, f"Ya tienes un ticket abierto: {ch.mention}",
                          f"You already have an open ticket: {ch.mention}"),
                        ephemeral=True,
                    )
                    return
            tk["counter"] = int(tk.get("counter") or 0) + 1
            numero = tk["counter"]
            guardar_db()
            try:
                canal = await g.create_text_channel(
                    name=f"ticket-{numero:04d}",
                    category=categoria,
                    overwrites=overwrites,
                    topic=marca,
                    reason=f"Ticket de {u}",
                )
            except discord.HTTPException as e:
                await interaction.followup.send(
                    L(gid, f"No pude crear el ticket: {e}", f"Could not create the ticket: {e}"),
                    ephemeral=True,
                )
                return

        active = tk.setdefault("active", {})
        prio = prioridad if prioridad in ("low", "normal", "high") else "normal"
        active[str(canal.id)] = {
            "opener": u.id,
            "claimed_by": None,
            "last_activity": time.time(),
            "reason": motivo or "",
            "number": numero,
            "priority": prio,
        }
        st = tk.setdefault("stats", {"opened": 0, "closed": 0})
        st["opened"] = int(st.get("opened") or 0) + 1
        guardar_db()

        desc = L(
            gid,
            f"Hola {u.mention}. Describe tu consulta y te responderemos aquí.",
            f"Hi {u.mention}. Describe your request and we'll reply here.",
        )
        embed = discord.Embed(
            title=L(gid, f"🎫 Ticket #{numero:04d}", f"🎫 Ticket #{numero:04d}"),
            description=desc,
            color=discord.Color.blurple(),
        )
        if motivo:
            embed.add_field(
                name=L(gid, "Motivo", "Reason"),
                value=motivo[:1000],
                inline=False,
            )
        embed.add_field(
            name=L(gid, "Prioridad", "Priority"),
            value=prio,
            inline=True,
        )
        try:
            await canal.send(
                content=u.mention + (f" {rol.mention}" if rol else ""),
                embed=embed,
                view=TicketControlsView(),
                allowed_mentions=discord.AllowedMentions(users=True, roles=True),
            )
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            L(gid, f"<:aceptado:1560557801464668240> Ticket creado: {canal.mention}",
              f"<:aceptado:1560557801464668240> Ticket created: {canal.mention}"),
            ephemeral=True,
        )

    async def reclamar_ticket(interaction: discord.Interaction):
        canal = interaction.channel
        g = interaction.guild
        u = interaction.user
        if g is None or not isinstance(canal, discord.TextChannel) or not isinstance(u, discord.Member):
            await interaction.response.send_message("Solo en servidores.", ephemeral=True)
            return
        gid = g.id
        tk = cfg(gid)["tickets"]
        topic = canal.topic or ""
        if not topic.startswith("aegis-ticket:"):
            await interaction.response.send_message(
                L(gid, "Este canal no es un ticket.", "This channel is not a ticket."),
                ephemeral=True,
            )
            return
        es_staff = (
            es_mod(u)
            or u.guild_permissions.manage_channels
            or (tk.get("support_role") and any(r.id == tk["support_role"] for r in u.roles))
        )
        if not es_staff:
            await interaction.response.send_message(
                L(gid, "Solo el staff puede reclamar tickets.",
                  "Only staff can claim tickets."),
                ephemeral=True,
            )
            return
        info = tk.setdefault("active", {}).get(str(canal.id), {})
        claimed = info.get("claimed_by")
        if claimed and claimed != u.id:
            await interaction.response.send_message(
                L(gid, f"Ya lo reclamó <@{claimed}>.", f"Already claimed by <@{claimed}>."),
                ephemeral=True,
            )
            return
        info["claimed_by"] = u.id
        info["last_activity"] = time.time()
        tk["active"][str(canal.id)] = info
        guardar_db()
        # Responder YA (el rename puede ir rate-limited y tardar minutos)
        await interaction.response.send_message(
            L(gid, f"🙋 {u.mention} reclamó este ticket.",
              f"🙋 {u.mention} claimed this ticket."),
        )

        async def _rename_claim():
            try:
                if not canal.name.startswith("claimed-"):
                    await canal.edit(name=f"claimed-{canal.name.replace('ticket-', '')}"[:100])
            except (discord.HTTPException, asyncio.TimeoutError):
                pass

        asyncio.create_task(_rename_claim())


    async def cambiar_prioridad(interaction: discord.Interaction):
        canal = interaction.channel
        g = interaction.guild
        u = interaction.user
        if g is None or not isinstance(canal, discord.TextChannel) or not isinstance(u, discord.Member):
            await interaction.response.send_message("Solo en servidores.", ephemeral=True)
            return
        gid = g.id
        topic = canal.topic or ""
        if not topic.startswith("aegis-ticket:"):
            await interaction.response.send_message(
                L(gid, "Este canal no es un ticket.", "This channel is not a ticket."),
                ephemeral=True,
            )
            return
        tk = cfg(gid)["tickets"]
        es_staff = (
            es_mod(u)
            or u.guild_permissions.manage_channels
            or (tk.get("support_role") and any(r.id == tk["support_role"] for r in u.roles))
        )
        if not es_staff:
            await interaction.response.send_message(
                L(gid, "Solo el staff puede cambiar la prioridad.",
                  "Only staff can change priority."),
                ephemeral=True,
            )
            return
        info = tk.setdefault("active", {}).get(str(canal.id), {})
        orden = ["low", "normal", "high"]
        actual = info.get("priority") or "normal"
        if actual not in orden:
            actual = "normal"
        nueva = orden[(orden.index(actual) + 1) % 3]
        info["priority"] = nueva
        info["last_activity"] = time.time()
        tk["active"][str(canal.id)] = info
        guardar_db()
        pref = {"low": "low", "normal": "n", "high": "high"}[nueva]
        # renombrar manteniendo número si existe
        base = canal.name
        for p in ("low-", "n-", "high-", "claimed-"):
            if base.startswith(p):
                base = base[len(p):]
        if base.startswith("ticket-"):
            nuevo_nombre = f"{pref}-{base}"
        else:
            nuevo_nombre = f"{pref}-{base}"
        labels = {
            "low": L(gid, "baja", "low"),
            "normal": L(gid, "normal", "normal"),
            "high": L(gid, "alta", "high"),
        }
        await interaction.response.send_message(
            L(gid, f"Prioridad: **{labels[nueva]}**", f"Priority: **{labels[nueva]}**"),
        )

        async def _rename_prio():
            try:
                if len(nuevo_nombre) <= 100 and canal.name != nuevo_nombre[:100]:
                    await canal.edit(name=nuevo_nombre[:100])
            except (discord.HTTPException, asyncio.TimeoutError):
                pass

        asyncio.create_task(_rename_prio())

    async def generar_transcript(canal: discord.TextChannel) -> str:
        lineas = [f"Transcript #{canal.name} - {canal.guild.name}", "=" * 40]
        async for m in canal.history(limit=None, oldest_first=True):
            ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            linea = f"[{ts}] {m.author} ({m.author.id}): {m.clean_content or ''}"
            extras = [a.url for a in m.attachments]
            if m.embeds:
                extras.append(f"[{len(m.embeds)} embed(s)]")
            if extras:
                linea += " " + " ".join(extras)
            lineas.append(linea)
        return "\n".join(lineas)

    async def cerrar_ticket(interaction: discord.Interaction, cierre_motivo: str | None = None):
        canal = interaction.channel
        g = interaction.guild
        u = interaction.user
        if g is None or not isinstance(canal, discord.TextChannel) or not isinstance(u, discord.Member):
            await interaction.response.send_message("Solo en servidores.", ephemeral=True)
            return
        gid = g.id
        topic = canal.topic or ""
        if not topic.startswith("aegis-ticket:"):
            await interaction.response.send_message(
                L(gid, "Este canal no es un ticket.", "This channel is not a ticket."),
                ephemeral=True,
            )
            return
        try:
            opener_id = int(topic.split(":", 1)[1])
        except ValueError:
            opener_id = 0
        tk = cfg(gid)["tickets"]
        permitido = (
            u.id == opener_id
            or es_mod(u)
            or u.guild_permissions.manage_channels
            or (tk.get("support_role") and any(r.id == tk["support_role"] for r in u.roles))
        )
        if not permitido:
            await interaction.response.send_message(
                L(gid, "No puedes cerrar este ticket.", "You can't close this ticket."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            texto = await generar_transcript(canal)
        except discord.HTTPException as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return

        def nuevo_archivo():
            return discord.File(
                io.BytesIO(texto.encode("utf-8")),
                filename=f"transcript-{canal.name}.txt",
            )

        destino_id = tk.get("log_channel") or cfg(gid)["log_channel"]
        destino = g.get_channel(destino_id) if destino_id else None
        info = tk.get("active", {}).get(str(canal.id), {})
        claimed = info.get("claimed_by")
        resumen = L(
            gid,
            f"Ticket **{canal.name}** cerrado por {u.mention}.",
            f"Ticket **{canal.name}** closed by {u.mention}.",
        )
        if claimed:
            resumen += f" · Claimed: <@{claimed}>"
        if info.get("reason"):
            resumen += f"\nMotivo apertura: {info['reason'][:200]}"
        if cierre_motivo:
            resumen += f"\nMotivo cierre: {cierre_motivo[:200]}"
        if info.get("priority"):
            resumen += f"\nPrioridad: {info.get('priority')}"
        st = tk.setdefault("stats", {"opened": 0, "closed": 0})
        st["closed"] = int(st.get("closed") or 0) + 1
        guardado = False
        if destino is not None:
            try:
                await destino.send(
                    resumen + f"\nOpener: <@{opener_id}>",
                    file=nuevo_archivo(),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                guardado = True
            except discord.HTTPException:
                pass
        try:
            miembro = g.get_member(opener_id) or await g.fetch_member(opener_id)
            await miembro.send(
                L(gid, f"Tu ticket en **{g.name}** fue cerrado. Aquí está el transcript:",
                  f"Your ticket in **{g.name}** was closed. Here is the transcript:"),
                file=nuevo_archivo(),
            )
        except Exception:
            pass

        tk.get("active", {}).pop(str(canal.id), None)
        guardar_db()

        aviso = L(gid, "🔒 Cerrando el ticket en 5 segundos...", "🔒 Closing the ticket in 5 seconds...")
        if not guardado and destino is None:
            aviso += L(
                gid,
                "\n(No hay canal de logs: transcript solo por DM.)",
                "\n(No log channel: transcript only via DM.)",
            )
        try:
            await canal.send(aviso)
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            L(gid, "Transcript guardado.", "Transcript saved."), ephemeral=True
        )
        await asyncio.sleep(5)
        try:
            await canal.delete(reason=f"Ticket cerrado por {u}")
        except discord.HTTPException:
            pass

    @bot.listen("on_message")
    async def ticket_activity(message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        topic = message.channel.topic or ""
        if not topic.startswith("aegis-ticket:"):
            return
        tk = cfg(message.guild.id)["tickets"]
        active = tk.setdefault("active", {})
        key = str(message.channel.id)
        if key not in active:
            try:
                opener = int(topic.split(":", 1)[1])
            except ValueError:
                opener = 0
            active[key] = {
                "opener": opener,
                "claimed_by": None,
                "last_activity": time.time(),
                "reason": "",
                "number": 0,
            }
        else:
            active[key]["last_activity"] = time.time()
        # no guardar_db cada mensaje: solo memoria; el loop de autoclose usa esto
        # persistimos cada ~5 min en la tarea

    @tasks.loop(minutes=15)
    async def tarea_autoclose_tickets():
        ahora = time.time()
        for gid_s, gdata in list(DB.get("guilds", {}).items()):
            tk = gdata.get("tickets") or {}
            horas = float(tk.get("autoclose_hours") or 0)
            if horas <= 0:
                continue
            guild = core.bot.get_guild(int(gid_s))
            if guild is None:
                continue
            limite = horas * 3600
            active = tk.setdefault("active", {})
            for cid, info in list(active.items()):
                last = float(info.get("last_activity") or 0)
                if last and ahora - last < limite:
                    continue
                ch = guild.get_channel(int(cid))
                if not isinstance(ch, discord.TextChannel):
                    active.pop(cid, None)
                    continue
                try:
                    await ch.send(
                        L(int(gid_s),
                          f"⏰ Cierre automático: sin actividad en {int(horas)} h.",
                          f"⏰ Auto-close: no activity for {int(horas)} h.")
                    )
                except discord.HTTPException:
                    pass
                try:
                    texto = await generar_transcript(ch)
                    destino_id = tk.get("log_channel") or gdata.get("log_channel")
                    destino = guild.get_channel(destino_id) if destino_id else None
                    if destino:
                        await destino.send(
                            f"Auto-close ticket **{ch.name}**",
                            file=discord.File(
                                io.BytesIO(texto.encode("utf-8")),
                                filename=f"transcript-{ch.name}.txt",
                            ),
                        )
                except Exception:
                    pass
                try:
                    await ch.delete(reason="AegisBot: ticket auto-close inactivity")
                except discord.HTTPException:
                    pass
                active.pop(cid, None)
            guardar_db()

    if not tarea_autoclose_tickets.is_running():
        tarea_autoclose_tickets.start()


    def _embed_tickets_cfg(gid: int) -> discord.Embed:
        tk = cfg(gid)["tickets"]
        cat = f"<#{tk['category']}>" if tk.get("category") else L(gid, "(sin categoría)", "(no category)")
        rol = f"<@&{tk['support_role']}>" if tk.get("support_role") else L(gid, "(ninguno)", "(none)")
        logs = f"<#{tk['log_channel']}>" if tk.get("log_channel") else L(gid, "(usa log global)", "(uses global log)")
        e = discord.Embed(
            title=L(gid, "🎫 Tickets · Configuración", "🎫 Tickets · Configuration"),
            color=discord.Color.blurple(),
        )
        e.add_field(name=L(gid, "Categoría", "Category"), value=cat)
        e.add_field(name=L(gid, "Rol soporte", "Support role"), value=rol)
        e.add_field(name=L(gid, "Canal transcripts", "Transcript channel"), value=logs)
        e.add_field(
            name=L(gid, "Pedir motivo", "Require reason"),
            value=_si_no(tk.get("require_reason", True)),
        )
        e.add_field(
            name=L(gid, "Auto-cierre", "Auto-close"),
            value=L(
                gid,
                f"{tk.get('autoclose_hours', 0)} h (0 = off)",
                f"{tk.get('autoclose_hours', 0)} h (0 = off)",
            ),
        )
        reasons = tk.get("reasons") or []
        e.add_field(
            name=L(gid, "Motivos predefinidos", "Preset reasons"),
            value=(", ".join(reasons[:8]) if reasons else L(gid, "(ninguno = texto libre)", "(none = free text)"))[:1024],
            inline=False,
        )
        st = tk.get("stats") or {}
        e.add_field(
            name=L(gid, "Estadísticas", "Stats"),
            value=L(
                gid,
                f"Abiertos: {st.get('opened', 0)} · Cerrados: {st.get('closed', 0)} · Activos: {len(tk.get('active') or {})}",
                f"Opened: {st.get('opened', 0)} · Closed: {st.get('closed', 0)} · Active: {len(tk.get('active') or {})}",
            ),
            inline=False,
        )
        e.set_footer(text=L(
            gid,
            "Todo se configura en este panel. Prioridad y cierre con motivo en cada ticket.",
            "Everything is configured in this panel. Priority and close-reason on each ticket.",
        ))
        return e



    class MotivosModal(discord.ui.Modal):
        def __init__(self, panel: "TicketsConfigView"):
            super().__init__(title=L(panel.gid, "Motivos predefinidos", "Preset reasons")[:45])
            self.panel = panel
            actuales = cfg(panel.gid)["tickets"].get("reasons") or []
            self.campo = discord.ui.TextInput(
                label=L(panel.gid, "Motivos (separados por |)", "Reasons (separated by |)")[:45],
                style=discord.TextStyle.paragraph,
                required=False,
                max_length=500,
                default="|".join(actuales)[:500] if actuales else None,
                placeholder="Soporte|Reporte|Apelación|Otro",
            )
            self.add_item(self.campo)

        async def on_submit(self, interaction: discord.Interaction):
            raw = (self.campo.value or "").strip()
            lista = [m.strip()[:100] for m in raw.split("|") if m.strip()][:25]
            cfg(self.panel.gid)["tickets"]["reasons"] = lista
            guardar_db()
            await self.panel.actualizar(interaction)

    class TicketsConfigView(PanelView):
        def __init__(self, autor_id: int, gid: int):
            super().__init__(autor_id, gid)
            self.pub_channel_id: int | None = None
            self._sync()

        def _sync(self):
            tk = cfg(self.gid)["tickets"]
            self.btn_motivo.label = L(
                self.gid,
                "Motivo: sí" if tk.get("require_reason", True) else "Motivo: no",
                "Reason: on" if tk.get("require_reason", True) else "Reason: off",
            )
            h = int(tk.get("autoclose_hours") or 0)
            self.btn_autoclose.label = L(
                self.gid, f"Auto-cierre: {h}h", f"Auto-close: {h}h"
            )
            nmot = len(tk.get("reasons") or [])
            self.btn_motivos.label = L(
                self.gid, f"Motivos ({nmot})", f"Reasons ({nmot})"
            )
            self.btn_publicar.label = L(self.gid, "Publicar panel", "Post panel")
            self.btn_cerrar.label = L(self.gid, "Cerrar", "Close")
            self.sel_cat.placeholder = L(self.gid, "Categoría de tickets…", "Ticket category…")
            self.sel_rol.placeholder = L(self.gid, "Rol de soporte…", "Support role…")
            self.sel_logs.placeholder = L(self.gid, "Canal de transcripts…", "Transcript channel…")
            self.sel_pub.placeholder = L(self.gid, "Canal donde publicar el panel…", "Channel to post panel…")

        async def actualizar(self, interaction: discord.Interaction):
            self._sync()
            await interaction.response.edit_message(embed=_embed_tickets_cfg(self.gid), view=self)

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Categoría de tickets…",
            channel_types=[discord.ChannelType.category],
            row=0,
        )
        async def sel_cat(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            cfg(self.gid)["tickets"]["category"] = select.values[0].id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.select(
            cls=discord.ui.RoleSelect,
            placeholder="Rol de soporte…",
            row=1,
        )
        async def sel_rol(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
            cfg(self.gid)["tickets"]["support_role"] = select.values[0].id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal de transcripts…",
            channel_types=[discord.ChannelType.text],
            row=2,
        )
        async def sel_logs(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            cfg(self.gid)["tickets"]["log_channel"] = select.values[0].id
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.select(
            cls=discord.ui.ChannelSelect,
            placeholder="Canal donde publicar el panel…",
            channel_types=[discord.ChannelType.text],
            row=3,
        )
        async def sel_pub(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
            self.pub_channel_id = select.values[0].id
            await interaction.response.defer()
            await interaction.followup.send(
                L(self.gid, f"Panel se publicará en <#{self.pub_channel_id}>. Pulsa **Publicar panel**.",
                  f"Panel will post in <#{self.pub_channel_id}>. Tap **Post panel**."),
                ephemeral=True,
            )

        @discord.ui.button(label="Motivos (0)", style=discord.ButtonStyle.primary, row=4)
        async def btn_motivos(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(MotivosModal(self))

        @discord.ui.button(label="Motivo: sí", style=discord.ButtonStyle.secondary, row=4)
        async def btn_motivo(self, interaction: discord.Interaction, button: discord.ui.Button):
            tk = cfg(self.gid)["tickets"]
            tk["require_reason"] = not tk.get("require_reason", True)
            guardar_db()
            await self.actualizar(interaction)

        @discord.ui.button(label="Auto-cierre: 0h", style=discord.ButtonStyle.secondary, row=4)
        async def btn_autoclose(self, interaction: discord.Interaction, button: discord.ui.Button):
            modal = NumeroModal(
                self,
                ("Horas auto-cierre", "Auto-close hours"),
                ("0 = desactivar, máx. 168", "0 = off, max 168"),
                0, 168,
                lambda g: int(cfg(g)["tickets"].get("autoclose_hours") or 0),
                lambda g, v: cfg(g)["tickets"].__setitem__("autoclose_hours", v),
            )
            await interaction.response.send_modal(modal)

        @discord.ui.button(label="Publicar panel", style=discord.ButtonStyle.primary, row=4)
        async def btn_publicar(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid = self.gid
            g = interaction.guild
            ch_id = self.pub_channel_id or interaction.channel_id
            canal = g.get_channel(ch_id) if g else None
            if not isinstance(canal, discord.TextChannel):
                await interaction.response.send_message(
                    L(gid, "Elige un canal de texto para publicar el panel.",
                      "Pick a text channel to post the panel."),
                    ephemeral=True,
                )
                return
            embed = discord.Embed(
                title=L(gid, "🎫 Soporte", "🎫 Support"),
                description=L(
                    gid,
                    "Pulsa el botón para abrir un ticket privado con el staff.",
                    "Press the button to open a private ticket with staff.",
                ),
                color=discord.Color.blurple(),
            )
            try:
                await canal.send(embed=embed, view=TicketPanelView())
            except discord.HTTPException as e:
                await interaction.response.send_message(
                    L(gid, f"No pude publicar: {e}", f"Could not post: {e}"),
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                L(gid, f"<:aceptado:1560557801464668240> Panel publicado en {canal.mention}.",
                  f"<:aceptado:1560557801464668240> Panel posted in {canal.mention}."),
                ephemeral=True,
            )

        @discord.ui.button(label="Cerrar", style=discord.ButtonStyle.grey, row=4)
        async def btn_cerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(view=None)


    async def abrir_panel_tickets(interaction: discord.Interaction):
        gid = interaction.guild_id
        view = TicketsConfigView(interaction.user.id, gid)
        embed = _embed_tickets_cfg(gid)
        if interaction.response.is_done():
            msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            view.mensaje = msg
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            view.mensaje = await interaction.original_response()


    core.TicketPanelView = TicketPanelView
    core.TicketCloseView = TicketCloseView
    core.TicketClaimCloseView = TicketControlsView
    core.abrir_panel_tickets = abrir_panel_tickets
