#!/usr/bin/env python3
"""Orión Dashboard v1.2 — panel que LEE el cerebro sin duplicarlo."""
from __future__ import annotations

import datetime
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from orion_brain import DIARY_PATH, OrionBrain
except ImportError:
    OrionBrain = None
    DIARY_PATH = Path.home() / ".orion-code" / "diary.md"


def clear_screen() -> None:
    os.system("clear" if os.name == "posix" else "cls")


def get_battery() -> str:
    if not shutil.which("termux-battery-status"):
        return "No disponible (instala termux-api)"
    try:
        res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=3)
        data = json.loads(res.stdout)
        return f"{data.get('percentage', 'N/A')}% ({data.get('status', 'N/A')})"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "No disponible"


def get_storage() -> dict:
    try:
        total, used, free = shutil.disk_usage(Path.home())
        return {"total": f"{total // (2**30)} GB", "used": f"{used // (2**30)} GB",
                "free": f"{free // (2**30)} GB"}
    except OSError:
        return {"total": "?", "used": "?", "free": "?"}


def check_internet(timeout: float = 3.0) -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout).close()
        return True
    except OSError:
        return False


def uptime_text() -> str:
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
        h, rem = divmod(int(seconds), 3600)
        return f"{h}h {rem // 60}m"
    except (OSError, ValueError, IndexError):
        return "desconocido"


def show_brain(brain) -> None:
    if brain is None:
        print("\n(cerebro no disponible: falta orion_brain.py)")
        return
    print("\n\033[1;35m[ Estado del cerebro ]\033[0m")
    print(brain.status_text())


def pause() -> None:
    input("\nPresiona Enter para continuar...")


def main_menu() -> None:
    brain = OrionBrain() if OrionBrain else None
    while True:
        clear_screen()
        print("\033[1;36m" + "=" * 50 + "\n      ORION CODE - DASHBOARD v1.2\n" + "=" * 50 + "\033[0m")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Fecha/Hora: \033[1;33m{now}\033[0m")
        print(f"Sistema: \033[1;32m{platform.system()} {platform.machine()} ({platform.release()})\033[0m")
        print(f"Batería: \033[1;33m{get_battery()}\033[0m")
        s = get_storage()
        print(f"Almacenamiento: usado {s['used']} / libre {s['free']} (total {s['total']})")
        print("\n\033[1;35m[ Menú principal ]\033[0m")
        print("1. Información del sistema")
        print("2. Listar archivos del directorio actual")
        print("3. Comprobar conexión a Internet")
        print("4. Estado del cerebro de Orión")
        print("5. Ver diario (~/.orion-code/diary.md)")
        print("6. Abrir Orión Code (agente)")
        print("7. Salir")
        try:
            choice = input("\n\033[1;34mElige una opción (1-7): \033[0m").strip()
            if choice == "1":
                print(f"\n{platform.platform()}\nUptime: {uptime_text()}")
                pause()
            elif choice == "2":
                print("\n--- ARCHIVOS EN EL DIRECTORIO ACTUAL ---")
                for name in sorted(os.listdir(".")):
                    print(f" - {name}")
                pause()
            elif choice == "3":
                print("\n--- COMPROBANDO CONEXIÓN ---")
                print("Conectado." if check_internet() else "Sin conexión a Internet.")
                pause()
            elif choice == "4":
                show_brain(brain)
                pause()
            elif choice == "5":
                print(f"\n--- DIARIO ({DIARY_PATH}) ---")
                if DIARY_PATH.is_file():
                    data = DIARY_PATH.read_text(encoding="utf-8", errors="replace")
                    print(data[-4000:])
                else:
                    print("Aún no hay diario.")
                pause()
            elif choice == "6":
                script = Path(__file__).resolve().parent / "orion_code.py"
                if script.is_file():
                    subprocess.run([sys.executable, str(script)])
                else:
                    print("No encuentro orion_code.py junto al dashboard.")
                    pause()
            elif choice == "7":
                break
            else:
                print("\nOpción no válida.")
                pause()
        except (KeyboardInterrupt, EOFError):
            print()
            break
    print("\n¡Hasta luego! Saliendo de Orión Dashboard.")


if __name__ == "__main__":
    main_menu()
