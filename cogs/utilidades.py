"""Giveaways y weather"""
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
    # GIVEAWAYS (GamerPower)
    # ============================================================
    PLATAFORMAS = [
        ("Todas / All", "all"), ("PC", "pc"), ("Steam", "steam"), ("Epic Games", "epic-games-store"),
        ("GOG", "gog"), ("itch.io", "itchio"), ("PS5", "ps5"), ("PS4", "ps4"),
        ("Xbox Series X|S", "xbox-series-xs"), ("Xbox One", "xbox-one"), ("Switch", "switch"),
        ("Android", "android"), ("iOS", "ios"),
    ]
    CHOICES_PLATAFORMA = [app_commands.Choice(name=n, value=v) for n, v in PLATAFORMAS]


    async def obtener_giveaways(plataforma: str, cache: dict | None = None) -> list:
        if cache is not None and plataforma in cache:
            return cache[plataforma]
        params = {"type": "game", "sort-by": "popularity"}
        if plataforma != "all":
            params["platform"] = plataforma
        data = await http_json("https://www.gamerpower.com/api/giveaways", params)
        items = data if isinstance(data, list) else []
        if cache is not None:
            cache[plataforma] = items
        return items


    def embeds_giveaways(items: list, es: bool) -> list[discord.Embed]:
        embeds = []
        for it in items[:8]:
            e = discord.Embed(title=(it.get("title") or "?")[:250],
                              url=it.get("open_giveaway_url") or None, color=discord.Color.green())
            desc = (it.get("description") or "")[:150]
            e.description = (
                f"{desc}\n"
                f"**{'Valor' if es else 'Worth'}:** {it.get('worth', 'N/A')} · "
                f"**{'Plataformas' if es else 'Platforms'}:** {it.get('platforms', '?')}\n"
                f"**{'Termina' if es else 'Ends'}:** {it.get('end_date', 'N/A')}"
            )[:1000]
            if it.get("thumbnail"):
                e.set_thumbnail(url=it["thumbnail"])
            embeds.append(e)
        return embeds


    async def actualizar_tablero(guild_id: int, cache: dict | None = None):
        c = cfg(guild_id)
        gw = c["giveaway"]
        if not gw["channel"]:
            return
        canal = bot.get_channel(gw["channel"])
        if canal is None:
            return
        es = c["lang"] != "en"
        items = await obtener_giveaways(gw["platform"], cache)
        embeds = embeds_giveaways(items, es)
        ahora = int(time.time())
        if embeds:
            contenido = (f"🎁 **{'Juegos gratis' if es else 'Free games'}** · {gw['platform']} · "
                         f"{'actualizado' if es else 'updated'} <t:{ahora}:R>")
        else:
            contenido = (f"🎁 {'No hay giveaways activos ahora mismo.' if es else 'No active giveaways right now.'} "
                         f"· <t:{ahora}:R>")
        msg = None
        if gw["message_id"]:
            try:
                msg = await canal.fetch_message(gw["message_id"])
            except discord.NotFound:
                msg = None
        if msg is not None:
            await msg.edit(content=contenido, embeds=embeds)
        else:
            nuevo = await canal.send(content=contenido, embeds=embeds)
            gw["message_id"] = nuevo.id
            guardar_db()


    @tasks.loop(minutes=15)
    async def tarea_giveaways():
        cache: dict = {}
        for gid, g in list(DB["guilds"].items()):
            if g.get("giveaway", {}).get("channel"):
                try:
                    await actualizar_tablero(int(gid), cache)
                except Exception as e:
                    print(f"[giveaways] {gid}: {e}")


    @tarea_giveaways.before_loop
    async def _antes_giveaways():
        await bot.wait_until_ready()


    @bot.tree.command(name="giveaways", description="Muestra los juegos gratis disponibles ahora (GamerPower)")
    @app_commands.describe(plataforma="Filtrar por plataforma")
    @app_commands.choices(plataforma=CHOICES_PLATAFORMA)
    async def giveaways(interaction: discord.Interaction, plataforma: app_commands.Choice[str] | None = None):
        gid = interaction.guild_id
        await interaction.response.defer(ephemeral=True)
        p = plataforma.value if plataforma else "all"
        try:
            items = await obtener_giveaways(p)
        except Exception as e:
            await interaction.followup.send(L(gid, f"No pude consultar GamerPower: {e}",
                                              f"Could not query GamerPower: {e}"))
            return
        embeds = embeds_giveaways(items, L(gid, "es", "en") == "es")
        if not embeds:
            await interaction.followup.send(L(gid, "No hay giveaways activos para ese filtro.",
                                              "No active giveaways for that filter."))
            return
        await interaction.followup.send(embeds=embeds)


    # ============================================================
    # CLIMA
    # ============================================================
    WMO = {
        0: ("Despejado", "Clear"), 1: ("Mayormente despejado", "Mostly clear"),
        2: ("Parcialmente nublado", "Partly cloudy"), 3: ("Nublado", "Overcast"),
        45: ("Niebla", "Fog"), 48: ("Niebla con escarcha", "Rime fog"),
        51: ("Llovizna ligera", "Light drizzle"), 53: ("Llovizna", "Drizzle"),
        55: ("Llovizna intensa", "Heavy drizzle"), 61: ("Lluvia ligera", "Light rain"),
        63: ("Lluvia", "Rain"), 65: ("Lluvia fuerte", "Heavy rain"),
        71: ("Nieve ligera", "Light snow"), 73: ("Nieve", "Snow"), 75: ("Nieve fuerte", "Heavy snow"),
        77: ("Granizo fino", "Snow grains"), 80: ("Chubascos ligeros", "Light showers"),
        81: ("Chubascos", "Showers"), 82: ("Chubascos fuertes", "Violent showers"),
        85: ("Chubascos de nieve", "Snow showers"), 86: ("Chubascos de nieve fuertes", "Heavy snow showers"),
        95: ("Tormenta", "Thunderstorm"), 96: ("Tormenta con granizo", "Thunderstorm with hail"),
        99: ("Tormenta fuerte con granizo", "Severe thunderstorm with hail"),
    }


    @bot.tree.command(name="weather", description="Clima actual de una ciudad")
    @app_commands.describe(ciudad="Nombre de la ciudad")
    async def weather(interaction: discord.Interaction, ciudad: app_commands.Range[str, 2, 80]):
        gid = interaction.guild_id
        es = L(gid, "es", "en") == "es"
        await interaction.response.defer()
        try:
            geo = await http_json("https://geocoding-api.open-meteo.com/v1/search",
                                  {"name": ciudad, "count": 1, "language": "es" if es else "en"})
            res = geo.get("results") if isinstance(geo, dict) else None
            if not res:
                await interaction.followup.send(L(gid, "No encontré esa ciudad.", "City not found."))
                return
            r = res[0]
            w = await http_json("https://api.open-meteo.com/v1/forecast", {
                "latitude": r["latitude"], "longitude": r["longitude"], "timezone": "auto",
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
                           "weather_code,wind_speed_10m",
            })
            cur = w["current"]
        except Exception as e:
            await interaction.followup.send(L(gid, f"No pude obtener el clima: {e}",
                                              f"Could not get the weather: {e}"))
            return

        cond = WMO.get(cur.get("weather_code"), ("Desconocido", "Unknown"))[0 if es else 1]
        lugar = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        embed = discord.Embed(title=f"🌤️ {lugar}", description=f"**{cond}**", color=discord.Color.blue())
        embed.add_field(name="🌡️ " + ("Temperatura" if es else "Temperature"),
                        value=f"{cur['temperature_2m']} °C")
        embed.add_field(name="🥵 " + ("Sensación" if es else "Feels like"),
                        value=f"{cur['apparent_temperature']} °C")
        embed.add_field(name="💧 " + ("Humedad" if es else "Humidity"),
                        value=f"{cur['relative_humidity_2m']} %")
        embed.add_field(name="💨 " + ("Viento" if es else "Wind"), value=f"{cur['wind_speed_10m']} km/h")
        embed.add_field(name="🌧️ " + ("Precipitación" if es else "Precipitation"),
                        value=f"{cur['precipitation']} mm")
        embed.set_footer(text="Open-Meteo")
        await interaction.followup.send(embed=embed)




    core.actualizar_tablero = actualizar_tablero
    core.CHOICES_PLATAFORMA = CHOICES_PLATAFORMA

    if not tarea_giveaways.is_running():
        tarea_giveaways.start()
