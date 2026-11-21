"""Vigilante de red"""
from __future__ import annotations

import asyncio
import aiohttp
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
    # VIGILANTE DE RED (reconexión automática)
    # ============================================================
    RED_SONDA_SEG = 30     # cada cuánto se prueba internet
    RED_FALLOS_MAX = 3     # fallos seguidos para dar la red por caída (~90 s)
    RED_GRACIA_SEG = 90    # primera espera antes de matar el proceso
    RED_GRACIA_MAX = 900   # tope del backoff: 15 min
    RED_REINICIOS_MAX = 6  # después de estos, discord.py reintenta solo (sin execv)

    RED = {"fallos": 0, "desde": None, "ok_desde": time.time(), "gw_off": None, "aviso_tope": False}


    def _reinicios() -> int:
        try:
            return max(0, int(os.environ.get("AEGIS_REINICIOS", "0")))
        except ValueError:
            return 0


    def _gracia_actual() -> float:
        """90s, 180s, 360s… hasta 15 min. Sobrevive a os.execv porque va en el entorno."""
        return float(min(RED_GRACIA_SEG * (2 ** _reinicios()), RED_GRACIA_MAX))


    def _reset_reinicios():
        if os.environ.get("AEGIS_REINICIOS", "0") != "0":
            os.environ["AEGIS_REINICIOS"] = "0"


    async def hay_internet() -> bool:
        """Sonda TCP a discord.com:443. No gasta rate limit de la API."""
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("discord.com", 443), timeout=5)
        except Exception:
            return False
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass
        return True


    async def renovar_sesion_http():
        """Las conexiones HTTP viejas quedan muertas tras una caída: sesión nueva."""
        try:
            vieja = bot.session
            bot.session = aiohttp.ClientSession()
            await vieja.close()
        except Exception as e:
            print(f"[red] No pude renovar la sesión HTTP: {e}")


    def reiniciar_proceso() -> bool:
        """False si ya se llegó al tope y no se mata el proceso."""
        n = _reinicios()
        if n >= RED_REINICIOS_MAX:
            print(f"[red] Tope de reinicios ({RED_REINICIOS_MAX}). No mato el proceso.")
            return False
        guardar_db()
        os.environ["AEGIS_REINICIOS"] = str(n + 1)
        espera = min(RED_GRACIA_SEG * (2 ** (n + 1)), RED_GRACIA_MAX)
        print(f"[red] Reiniciando el bot (intento {n + 1}/{RED_REINICIOS_MAX}, "
              f"la próxima gracia será de {espera:.0f}s)...")
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable] + sys.argv)
        return True


    async def _vigilar_red():
        ahora = time.time()
        if not await hay_internet():
            RED["fallos"] += 1
            RED["ok_desde"] = None
            if RED["fallos"] >= RED_FALLOS_MAX and RED["desde"] is None:
                RED["desde"] = ahora - RED_SONDA_SEG * (RED["fallos"] - 1)
                print("[red] Sin internet. Esperando a que vuelva...")
            return

        RED["fallos"] = 0
        if RED["ok_desde"] is None:
            RED["ok_desde"] = ahora
        if RED["desde"] is not None:
            duracion = int(ahora - RED["desde"])
            RED["desde"] = None
            print(f"[red] Internet de vuelta tras ~{duracion}s.")
            await renovar_sesion_http()

        # Gateway arriba: todo bien
        if RED["gw_off"] is None:
            return

        # Gateway caído con internet disponible: dar margen a discord.py y, si no, reiniciar.
        # La espera crece en cada reinicio (90s, 3 min, 6 min…) para no martillar el login.
        if ahora - max(RED["gw_off"], RED["ok_desde"]) < _gracia_actual():
            return
        if SILENCIO_CANALES:
            print("[red] Reinicio aplazado: hay una limpieza en curso.")
            return
        if _reinicios() >= RED_REINICIOS_MAX:
            if not RED.get("aviso_tope"):
                print("[red] Tope de reinicios. discord.py sigue reintentando sin matar el proceso.")
                RED["aviso_tope"] = True
            RED["gw_off"] = ahora
            return
        try:
            reiniciar_proceso()
        except Exception as e:
            print(f"[red] No pude reiniciar el proceso: {e!r}. discord.py sigue reintentando.")
            RED["gw_off"] = ahora  # reintenta tras otro período de gracia


    @tasks.loop(seconds=RED_SONDA_SEG)
    async def tarea_red():
        try:
            await _vigilar_red()
        except Exception as e:
            print(f"[red] Error en el vigilante: {e!r}")


    @bot.listen("on_disconnect")
    async def _red_gateway_off():
        if RED["gw_off"] is None:
            RED["gw_off"] = time.time()
        print("[red] Gateway desconectado.")


    @bot.listen("on_ready")
    async def _red_gateway_on():
        RED["gw_off"] = None
        RED["aviso_tope"] = False
        _reset_reinicios()


    @bot.listen("on_resumed")
    async def _red_gateway_resumed():
        RED["gw_off"] = None
        RED["aviso_tope"] = False
        _reset_reinicios()
        print("[red] Sesión reanudada.")

    if not tarea_red.is_running():
        tarea_red.start()
