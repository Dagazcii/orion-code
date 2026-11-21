"""Red de reportes"""
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
    # RED GLOBAL DE REPORTES
    # ============================================================

    def reportes_aprobados(uid: int) -> list:
        # Sin "status" no cuenta como aprobado. Los viejos se migran al cargar la DB.
        return [r for r in DB["reports"].get(str(uid), []) if r.get("status") == "approved"]


    def buscar_reporte(uid: int, gid: int):
        for r in DB["reports"].get(str(uid), []):
            if r["guild_id"] == gid:
                return r
        return None


    async def notificar_decision(r: dict, uid: int, estado: str):
        g = bot.get_guild(r["guild_id"])
        if g is None:
            return
        if estado == "approved":
            titulo = L(g.id, "<:aceptado:1560557801464668240> Reporte aprobado", "<:aceptado:1560557801464668240> Report approved")
            color = discord.Color.green()
        elif estado == "rejected":
            titulo = L(g.id, "<:X_:1560557532836270101> Reporte rechazado", "<:X_:1560557532836270101> Report rejected")
            color = discord.Color.red()
        else:
            titulo = L(g.id, "🗑️ Reporte eliminado", "🗑️ Report removed")
            color = discord.Color.greyple()
        await registrar(g, titulo, f"<@{uid}> ({uid})", color)


    class ReporteBoton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r"aegis:rep:(?P<accion>ok|no):(?P<uid>\d+):(?P<gid>\d+)"):
        def __init__(self, accion: str, uid: int, gid: int):
            super().__init__(discord.ui.Button(
                label="Aprobar" if accion == "ok" else "Rechazar",
                emoji="<:aceptado:1560557801464668240>" if accion == "ok" else "<:X_:1560557532836270101>",
                style=discord.ButtonStyle.success if accion == "ok" else discord.ButtonStyle.danger,
                custom_id=f"aegis:rep:{accion}:{uid}:{gid}"))
            self.accion = accion
            self.uid = uid
            self.gid = gid

        @classmethod
        async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match):
            return cls(match["accion"], int(match["uid"]), int(match["gid"]))

        async def callback(self, interaction: discord.Interaction):
            if not await bot.is_owner(interaction.user):
                await interaction.response.send_message("Solo el dueño del bot puede revisar reportes.", ephemeral=True)
                return
            r = buscar_reporte(self.uid, self.gid)
            if r is None:
                await interaction.response.edit_message(content="Reporte ya no existe.", view=None)
                return
            estado = "approved" if self.accion == "ok" else "rejected"
            r["status"] = estado
            guardar_db()
            await interaction.response.edit_message(
                content=f"{'<:aceptado:1560557801464668240> Aprobado' if estado == 'approved' else '<:X_:1560557532836270101> Rechazado'} por {interaction.user}", view=None)
            await notificar_decision(r, self.uid, estado)


    @bot.tree.command(name="report", description="Reporta a un usuario malicioso (lo revisa el dueño del bot)")
    @app_commands.describe(
        usuario="Usuario a reportar", motivo="Motivo del reporte (mín. 5 caracteres)",
        enlace="Link a la evidencia: captura, video o mensaje de Discord")
    @app_commands.guild_only()
    @solo_mod()
    async def report(interaction: discord.Interaction, usuario: discord.User,
                     motivo: app_commands.Range[str, 5, 300], enlace: app_commands.Range[str, 8, 500]):
        # Responder primero: Discord da solo 3 segundos antes de "la aplicación no ha respondido"
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild_id
        print(f"[report] {interaction.user} reporta a {usuario} en {interaction.guild.name}")

        async def error(es: str, en: str):
            await interaction.followup.send(L(gid, es, en), ephemeral=True)

        if usuario.bot or usuario.id == interaction.user.id:
            await error("No puedes reportar a ese usuario.", "You can't report that user.")
            return
        enlace = enlace.strip()
        if not enlace.lower().startswith(("http://", "https://")):
            await error("El enlace debe empezar con http:// o https://.",
                        "The link must start with http:// or https://.")
            return

        lista = DB["reports"].setdefault(str(usuario.id), [])
        lista[:] = [r for r in lista if r["guild_id"] != gid]
        entrada = {"guild_id": gid, "guild_name": interaction.guild.name, "reason": motivo,
                   "evidence": enlace, "ts": int(time.time()), "status": "pending", "review_msg": None}
        lista.append(entrada)
        guardar_db()

        canal = None
        if REVIEW_CHANNEL_ID:
            canal = bot.get_channel(REVIEW_CHANNEL_ID)
            if canal is None:
                try:
                    canal = await bot.fetch_channel(REVIEW_CHANNEL_ID)
                except discord.HTTPException as e:
                    print(f"[reportes] No encuentro REVIEW_CHANNEL_ID: {e}")

        enviado = False
        if canal is not None:
            embed = discord.Embed(title="🚨 Nuevo reporte", color=discord.Color.orange(),
                                  timestamp=discord.utils.utcnow())
            embed.add_field(name="Usuario", value=f"{usuario.mention} ({usuario.id})", inline=False)
            embed.add_field(name="Servidor", value=f"{interaction.guild.name} ({gid})", inline=False)
            embed.add_field(name="Reportado por", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            embed.add_field(name="Motivo", value=motivo, inline=False)
            embed.add_field(name="Evidencia", value=enlace[:1000], inline=False)
            view = discord.ui.View(timeout=None)
            view.add_item(ReporteBoton("ok", usuario.id, gid))
            view.add_item(ReporteBoton("no", usuario.id, gid))
            try:
                msg = await canal.send(embed=embed, view=view)
                entrada["review_msg"] = msg.jump_url
                guardar_db()
                enviado = True
            except Exception as e:
                print(f"[reportes] No se pudo enviar a revisión: {e}")

        if enviado or not REVIEW_CHANNEL_ID:
            aviso = L(gid, f"📨 Reporte de {usuario} enviado a revisión. Se activará en la red cuando sea aprobado.",
                      f"📨 Report on {usuario} sent for review. It will activate in the network once approved.")
        else:
            aviso = L(gid, f"⚠️ Reporte de {usuario} guardado, pero no pude enviarlo al canal de revisión. "
                           f"El dueño del bot puede verlo con /reportadmin.",
                      f"⚠️ Report on {usuario} saved, but I couldn't send it to the review channel. "
                      f"The bot owner can see it with /reportadmin.")
        await interaction.followup.send(aviso, ephemeral=True)
        await registrar(interaction.guild, "🚨 Report (pendiente / pending)", f"{usuario.mention} ({usuario.id})",
                        discord.Color.orange(), [("Mod", interaction.user.mention), ("Motivo / Reason", motivo)])


    @bot.tree.command(name="reportinfo", description="Consulta los reportes aprobados de un usuario")
    @app_commands.describe(usuario="Usuario a consultar")
    @app_commands.guild_only()
    @solo_mod()
    async def reportinfo(interaction: discord.Interaction, usuario: discord.User):
        gid = interaction.guild_id
        lista = reportes_aprobados(usuario.id)
        propio = buscar_reporte(usuario.id, gid)
        if not lista and not (propio and propio.get("status") == "pending"):
            await responder(interaction, L(gid, "Sin reportes aprobados para ese usuario.",
                                           "No approved reports for that user."), ephemeral=True)
            return
        embed = discord.Embed(title=f"🚨 {usuario}", color=discord.Color.red(),
                              description=L(gid, f"{len(lista)} reporte(s) aprobado(s) en la red.",
                                            f"{len(lista)} approved report(s) in the network."))
        for r in lista[:10]:
            embed.add_field(name=f"{r['guild_name']} · <t:{r['ts']}:d>", value=r["reason"][:1000], inline=False)
        if propio and propio.get("status") == "pending":
            embed.set_footer(text=L(gid, "Tu servidor tiene un reporte pendiente de revisión.",
                                    "Your server has a report pending review."))
        await responder(interaction, embed=embed, ephemeral=True)


    @bot.tree.command(name="reportremove", description="Retira el reporte que este servidor hizo a un usuario")
    @app_commands.describe(usuario="Usuario a retirar")
    @app_commands.guild_only()
    @solo_mod()
    async def reportremove(interaction: discord.Interaction, usuario: discord.User):
        gid = interaction.guild_id
        lista = DB["reports"].get(str(usuario.id), [])
        nueva = [r for r in lista if r["guild_id"] != gid]
        if len(nueva) == len(lista):
            await responder(interaction, L(gid, "Este servidor no tiene un reporte de ese usuario.",
                                           "This server has no report on that user."), ephemeral=True)
            return
        if nueva:
            DB["reports"][str(usuario.id)] = nueva
        else:
            DB["reports"].pop(str(usuario.id), None)
        guardar_db()
        await responder(interaction, L(gid, "<:aceptado:1560557801464668240> Reporte retirado.", "<:aceptado:1560557801464668240> Report removed."), ephemeral=True)


    @bot.tree.command(name="reportadmin", description="(Dueño del bot) Gestiona la red global de reportes")
    @app_commands.describe(accion="Qué hacer", usuario="Usuario (no hace falta en 'pendientes')",
                           servidor_id="Opcional: solo el reporte de ese servidor")
    @app_commands.choices(accion=[
        app_commands.Choice(name="pendientes", value="list"),
        app_commands.Choice(name="aprobar", value="approve"),
        app_commands.Choice(name="rechazar", value="reject"),
        app_commands.Choice(name="eliminar", value="delete"),
    ])
    async def reportadmin(interaction: discord.Interaction, accion: app_commands.Choice[str],
                          usuario: discord.User | None = None, servidor_id: str | None = None):
        if not await bot.is_owner(interaction.user):
            await interaction.response.send_message("Solo el dueño del bot.", ephemeral=True)
            return

        if accion.value == "list":
            lineas = []
            for uid, lista in DB["reports"].items():
                for r in lista:
                    if r.get("status") == "pending":
                        link = f" · [revisión]({r['review_msg']})" if r.get("review_msg") else ""
                        ev = f" · {r['evidence']}" if r.get("evidence") else ""
                        lineas.append(f"<@{uid}> ({uid}) · {r['guild_name']} ({r['guild_id']}) · {r['reason'][:80]}{ev}{link}")
            texto = "\n".join(lineas[:20]) or "Sin reportes pendientes."
            await interaction.response.send_message(texto[:1900], ephemeral=True)
            return

        if usuario is None:
            await interaction.response.send_message("Indica el usuario.", ephemeral=True)
            return
        gid_filtro = None
        if servidor_id:
            try:
                gid_filtro = int(servidor_id.strip())
            except ValueError:
                await interaction.response.send_message("servidor_id inválido.", ephemeral=True)
                return

        lista = DB["reports"].get(str(usuario.id), [])
        objetivo = [r for r in lista if gid_filtro is None or r["guild_id"] == gid_filtro]
        if not objetivo:
            await interaction.response.send_message("No hay reportes que coincidan.", ephemeral=True)
            return
        for r in objetivo:
            if accion.value == "delete":
                lista.remove(r)
                estado = "deleted"
            else:
                estado = "approved" if accion.value == "approve" else "rejected"
                r["status"] = estado
            await notificar_decision(r, usuario.id, estado)
        if not lista:
            DB["reports"].pop(str(usuario.id), None)
        guardar_db()
        await interaction.response.send_message(f"<:aceptado:1560557801464668240> {len(objetivo)} reporte(s) actualizado(s).", ephemeral=True)




    core.ReporteBoton = ReporteBoton
    core.reportes_aprobados = reportes_aprobados

