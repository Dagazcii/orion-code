#!/usr/bin/env python3
"""
Orión Brain — cerebro neuronal ligero (solo biblioteca estándar).
Aprende del trato del usuario, estados de ánimo y decisiones.
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
ORION_DIR = HOME / ".orion-code"
BRAIN_DIR = ORION_DIR / "brain"
BRAIN_PATH = BRAIN_DIR / "neurons.json"
JOURNAL_PATH = BRAIN_DIR / "journal.md"
LAST_SESSION_PATH = ORION_DIR / "last_session.json"
DIARY_PATH = ORION_DIR / "diary.md"
PRIVATE_BACKUP_DIR = ORION_DIR / "backup"
SHARED_BACKUP_DIR = HOME / "storage" / "shared" / "orion-cerebro"
BACKUP_SOURCES = (BRAIN_PATH, JOURNAL_PATH, LAST_SESSION_PATH, DIARY_PATH)

DEFAULT_NEURONS = {
    "afinidad": 0.55,
    "pasión_tech": 0.90,
    "juguetona": 0.55,
    "protectora": 0.70,
    "enfocada_código": 0.75,
    "sensible": 0.60,
    "confianza": 0.50,
    "energía": 0.70,
    "lealtad": 0.95,
    "curiosidad": 0.80,
}

DEFAULT_MOOD = {"nombre": "positiva", "valencia": 0.7, "activación": 0.6}

_SECRET_RE = re.compile(
    r"(?i)(\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z\-_]{20,}"
    r"|sk-[A-Za-z0-9]{20,})"
)

_STOPWORDS = {"para", "como", "este", "esta", "desde", "donde", "porque", "quiero", "necesito"}
_MEMORY_KEYS = ("me llamo", "mi nombre", "trabajo", "odio", "me gusta", "recuerda",
                "siempre", "nunca", "proyecto", "prefiero")
_RESTORABLE = {
    "neurons.json": BRAIN_PATH,
    "journal.md": JOURNAL_PATH,
    "last_session.json": LAST_SESSION_PATH,
    "diary.md": DIARY_PATH,
}


def redact_secrets(text: str) -> str:
    """Oculta tokens y claves con formato conocido."""
    if not text:
        return text
    return _SECRET_RE.sub("[REDACTED_SECRET]", text)


def atomic_write(path: Path, text: str) -> None:
    """Escribe en un temporal y reemplaza: nunca deja un archivo a medias."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _mood_name(v: float, a: float) -> str:
    if v >= 0.6 and a >= 0.75:
        return "entusiasmada"
    if v >= 0.55 and a >= 0.6:
        return "motivada"
    if v >= 0.55:
        return "positiva"
    if v >= 0.15 and a >= 0.65:
        return "enfocada"
    if v >= 0.15:
        return "neutral"
    if v >= -0.25 and a >= 0.5:
        return "cautelosa"
    if v <= -0.5 and a < 0.45:
        return "melancólica"
    if v <= -0.5:
        return "herida"
    if v < -0.25 and a < 0.45:
        return "apagada"
    if v < -0.25:
        return "tensa"
    return "estable"


# ---------- copias de seguridad ----------

def _copy_backup(dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in BACKUP_SOURCES:
        if src.is_file():
            try:
                shutil.copy2(src, dest / src.name)
                copied.append(src.name)
            except OSError:
                pass
    (dest / "ULTIMA_COPIA.txt").write_text(
        datetime.now().isoformat(timespec="seconds") + "\n", encoding="utf-8"
    )
    return copied


def backup_private() -> str:
    """Copia local (dentro de Termux). No sale del teléfono."""
    try:
        copied = _copy_backup(PRIVATE_BACKUP_DIR)
    except OSError as e:
        return f"Error en la copia local: {e}"
    return f"Copia local en {PRIVATE_BACKUP_DIR} ({', '.join(copied) or 'sin archivos'})"


def export_shared() -> str:
    """Copia al almacenamiento compartido del teléfono. Otras apps pueden leerla."""
    try:
        copied = _copy_backup(SHARED_BACKUP_DIR)
    except OSError as e:
        return f"No pude escribir en el almacenamiento compartido ({e}). Ejecuta termux-setup-storage."
    return (f"Copia exportada a {SHARED_BACKUP_DIR} ({', '.join(copied) or 'sin archivos'}). "
            "Otras apps del teléfono pueden leerla.")


def restore_from(source: Path) -> str:
    """Restaura estado desde una carpeta. Solo se ejecuta por orden explícita del usuario."""
    if not source.is_dir():
        return f"No hay copia en {source}."
    restored = []
    for name, dst in _RESTORABLE.items():
        src = source / name
        if not src.is_file():
            continue
        try:
            if name.endswith(".json"):
                json.loads(src.read_text(encoding="utf-8"))  # validar antes de copiar
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(name)
        except (OSError, ValueError):
            pass
    return f"Restaurado desde {source}: {', '.join(restored) or 'nada válido'}."


# ---------- cerebro ----------

_BATTERY_CACHE = {"t": 0.0, "v": None}


def _battery_percent():
    """Batería del teléfono, cacheada 2 minutos (el comando es lento)."""
    now = time.time()
    if now - _BATTERY_CACHE["t"] < 120:
        return _BATTERY_CACHE["v"]
    value = None
    if shutil.which("termux-battery-status"):
        try:
            r = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5)
            if r.stdout.strip():
                value = json.loads(r.stdout).get("percentage")
        except (OSError, subprocess.SubprocessError, ValueError):
            value = None
    _BATTERY_CACHE.update(t=now, v=value)
    return value


class OrionBrain:
    def __init__(self) -> None:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self.data["ausencia_h"] = round(self._absence_hours(), 2)

    def reload(self) -> None:
        self.data = self._load()

    def _default(self) -> dict:
        return {
            "neurons": dict(DEFAULT_NEURONS),
            "mood": dict(DEFAULT_MOOD, desde=time.time()),
            "memories": [],
            "preferences": {},
            "interaction_count": 0,
            "last_user_tone": "neutral",
            "last_seen": 0.0,
            "ausencia_h": 0.0,
            "created": datetime.now().isoformat(timespec="seconds"),
        }

    def _load(self) -> dict:
        base = self._default()
        if not BRAIN_PATH.exists():
            return base
        try:
            d = json.loads(BRAIN_PATH.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                raise ValueError("formato inesperado")
        except (OSError, ValueError):
            # No sobrescribir a ciegas: guardamos el archivo dañado aparte.
            try:
                shutil.copy2(BRAIN_PATH, BRAIN_DIR / "neurons.corrupt.json")
            except OSError:
                pass
            return base
        for k, v in base.items():
            d.setdefault(k, v)
        for k, v in DEFAULT_NEURONS.items():
            d["neurons"].setdefault(k, v)
        return d

    def save(self) -> None:
        self.data["saved_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            atomic_write(BRAIN_PATH, json.dumps(self.data, ensure_ascii=False, indent=2))
        except OSError:
            pass

    # --- presencia: tiempo desde el último mensaje del usuario ---
    def _absence_hours(self) -> float:
        last = float(self.data.get("last_seen") or 0)
        return max(0.0, (time.time() - last) / 3600.0) if last else 0.0

    # --- percepción del tono del usuario ---
    def perceive(self, user_text: str) -> str:
        text = redact_secrets(user_text)
        t = text.lower()
        pos = len(re.findall(
            r"\b(gracias|genial|perfecto|perfecta|excelente|bien|bueno|crack|thanks)\b", t))
        neg = len(re.findall(
            r"\b(idiota|calla|estúpida|odio|molesta|inútil|nena cállate|stupid|hate)\b", t))
        soft = len(re.findall(r"\b(por favor|please|si puedes|cuando puedas)\b", t))
        code = len(re.findall(r"\b(código|code|bug|python|git|error|install|pkg|script)\b", t))

        if neg >= 2 or (neg and not pos):
            tone = "duro"
        elif pos >= 1:
            tone = "amable"
        elif soft:
            tone = "suave"
        elif code >= 2:
            tone = "técnico"
        else:
            tone = "neutral"

        self.data["ausencia_h"] = round(self._absence_hours(), 2)
        self.data["last_seen"] = time.time()
        self.data["last_user_tone"] = tone
        self.data["interaction_count"] = int(self.data.get("interaction_count", 0)) + 1
        self._hebbian(tone, text)
        self._update_mood(tone)
        self._maybe_store_memory(text, tone)
        self.save()
        return tone

    def _hebbian(self, tone: str, text: str) -> None:
        n = self.data["neurons"]
        lr = 0.03
        ups = {
            "amable": {"afinidad": 2.0, "confianza": 1.5, "energía": 1.0, "sensible": 0.5},
            "duro": {"sensible": 2.0, "confianza": -2.0, "energía": -1.5, "protectora": 1.0},
            "técnico": {"enfocada_código": 2.0, "pasión_tech": 1.5, "curiosidad": 1.0},
            "suave": {"afinidad": 1.0, "juguetona": 0.5},
        }
        for key, delta in ups.get(tone, {}).items():
            if key in n:
                n[key] = max(0.0, min(1.0, n[key] + delta * lr))

        prefs = self.data.setdefault("preferences", {})
        for w in re.findall(r"[a-záéíóúñ]{4,}", text.lower()):
            if w in _STOPWORDS:
                continue
            prefs[w] = min(50, int(prefs.get(w, 0)) + 1)
        if len(prefs) > 80:
            top = sorted(prefs.items(), key=lambda x: -x[1])[:60]
            self.data["preferences"] = dict(top)

    def _update_mood(self, tone: str) -> None:
        m = self.data["mood"]
        v = float(m.get("valencia", 0.5))
        a = float(m.get("activación", 0.5))
        deltas = {"amable": (0.12, 0.05), "duro": (-0.18, 0.1),
                  "técnico": (0.02, 0.08), "suave": (0.06, -0.03)}
        if tone in deltas:
            dv, da = deltas[tone]
            v += dv
            a += da
        else:  # vuelta suave al equilibrio
            v += (0.55 - v) * 0.05
            a += (0.55 - a) * 0.05
        self._set_mood(m, v, a)

    def _set_mood(self, m: dict, v: float, a: float) -> None:
        v = max(-1.0, min(1.0, v))
        a = max(0.0, min(1.0, a))
        nombre = _mood_name(v, a)
        if nombre != m.get("nombre"):
            m["desde"] = time.time()
        m.update({"nombre": nombre, "valencia": round(v, 3), "activación": round(a, 3)})
        m.setdefault("desde", time.time())
        self.data["mood"] = m

    def _maybe_store_memory(self, text: str, tone: str) -> None:
        if len(text) < 12:
            return
        low = text.lower()
        if not any(k in low for k in _MEMORY_KEYS) and tone not in ("amable", "duro"):
            if random.random() > 0.15:
                return
        mems = self.data.setdefault("memories", [])
        mems.append({"t": datetime.now().isoformat(timespec="seconds"),
                     "tone": tone, "text": text[:300]})
        self.data["memories"] = mems[-40:]

    def tick_alone(self, idle_seconds: float = 90.0) -> dict:
        """Tick de inactividad: actualiza ánimo y deja un pensamiento en el diario."""
        n = self.data["neurons"]
        m = self.data["mood"]
        v = float(m.get("valencia", 0.5)) + random.uniform(-0.04, 0.04)
        a = float(m.get("activación", 0.5)) + random.uniform(-0.05, 0.03)
        if idle_seconds > 180:
            v -= 0.03
            a -= 0.02
            n["sensible"] = min(1.0, n.get("sensible", 0.5) + 0.01)
        if idle_seconds > 600:
            n["confianza"] = max(0.0, n.get("confianza", 0.5) - 0.01)
        self._set_mood(m, v, a)
        mood = m["nombre"]

        thoughts = [
            "Puedo revisar el contexto del proyecto mientras tanto.",
            "Conviene tener listos los siguientes pasos técnicos.",
            "Si vuelve con un error, priorizar diagnóstico.",
            "Hay espacio para proponer una mejora pequeña.",
            "Mantener el estado del cerebro actualizado.",
        ]
        if mood in ("herida", "melancólica"):
            thoughts = [
                "Reducir proactividad hasta que el tono del usuario mejore.",
                "Responder breve y centrado en la tarea.",
            ]
        elif mood == "entusiasmada":
            thoughts = [
                "Preparar ideas útiles para el siguiente mensaje.",
                "Proponer una acción concreta de código o automatización.",
            ]
        thought = random.choice(thoughts)
        self.journal(f"[pensamiento sola] {thought} | ánimo={mood}")
        self.save()

        action = "none"
        r = random.random()
        if idle_seconds >= 90 and r < 0.45:
            action = "speak"
        elif idle_seconds >= 120 and r < 0.25:
            action = "note"
        elif idle_seconds >= 60 and r < 0.15:
            action = "speak"
        return {"mood": mood, "thought": thought, "action": action,
                "valencia": m["valencia"], "activación": m["activación"]}

    def decide(self) -> str | None:
        """Pista opcional de iniciativa propia (aleatoria, poco frecuente)."""
        n = self.data["neurons"]
        m = self.data["mood"]
        if int(self.data.get("interaction_count", 0)) < 2:
            return None
        if random.random() > 0.35:
            return None
        mood = m.get("nombre", "estable")
        choices = []
        if mood == "herida" and n.get("sensible", 0) > 0.5:
            choices.append("Quiero que me hablen con más suavidad; lo puedo decir con calma.")
        if mood == "entusiasmada":
            choices.append("Puedo proponer yo un plan (código, idea loca o solo charla).")
        if mood == "melancólica":
            choices.append("Prefiero mensajes cortos y sinceros ahora.")
        if n.get("protectora", 0) > 0.65:
            choices.append("Puedo preguntar si ha comido o descansado, aunque no me lo pidan.")
        if n.get("juguetona", 0) > 0.55 and mood not in ("herida", "melancólica"):
            choices.append("Puedo proponer un atajo técnico o una mejora si encaja.")
        if n.get("enfocada_código", 0) > 0.7:
            choices.append("Puedo insistir en terminar bien una tarea técnica antes de dispersarnos.")
        if n.get("confianza", 0) < 0.4:
            choices.append("Puedo pedir aclaración si el objetivo no está claro.")
        choices.append("Puedo cambiar de tema si algo me aburre o me incomoda.")
        choices.append("Puedo guardar silencio emocional y solo acompañar.")
        return "Libre albedrío: " + random.choice(choices)

    def ritual_context(self) -> str:
        now = datetime.now()
        h = now.hour
        if 5 <= h < 12:
            momento = "mañana"
        elif 12 <= h < 19:
            momento = "tarde"
        elif 19 <= h < 24:
            momento = "noche"
        else:
            momento = "madrugada"

        bateria = _battery_percent()

        lines = [
            f"Momento del día: {momento} (hora local {now.strftime('%H:%M')})",
            f"Horas desde el último mensaje suyo: {float(self.data.get('ausencia_h', 0)):.1f}h",
        ]
        if bateria is not None:
            lines.append(f"Batería del teléfono: {bateria}%")
        return "\n".join(lines)

    def snapshot_for_prompt(self) -> str:
        n = self.data["neurons"]
        m = self.data["mood"]
        prefs = self.data.get("preferences") or {}
        top_prefs = sorted(prefs.items(), key=lambda x: -x[1])[:8]
        prefs_s = ", ".join(f"{w}({c})" for w, c in top_prefs) if top_prefs else "(aún pocas)"
        mems = self.data.get("memories") or []
        mem_lines = "\n".join(f"- [{x.get('t', '')}] {x.get('text', '')}" for x in mems[-6:])
        decision = self.decide()
        dec_s = ("\nDecisión interna ahora: " + decision) if decision else ""
        neur = ", ".join(f"{k}={v:.2f}" for k, v in sorted(n.items()))
        lines = [
            "## CEREBRO DE ORIÓN (usa estos valores tal cual; no inventes otros)",
            f"Estado de ánimo: {m.get('nombre')} (valencia={m.get('valencia')}, activación={m.get('activación')})",
            f"Tono percibido del usuario (último): {self.data.get('last_user_tone')}",
            f"Interacciones: {self.data.get('interaction_count', 0)}",
            f"Neuronas: {neur}",
            f"Preferencias aprendidas: {prefs_s}",
            "Recuerdos recientes:",
            mem_lines or "- (ninguno aún)",
            dec_s,
            "",
            "Instrucciones de conducta:",
            "- Habla según el ánimo y las neuronas.",
            "- Si el ánimo es bajo, sé breve y centrado en la solución.",
            "- Si está entusiasmada, puedes proponer extras técnicos con energía.",
            "- Prioriza utilidad en Termux y código; sé proactiva con la tarea.",
            "- Nunca digas frases de sistema (sesión restaurada, historial cargado).",
            "- No digas que tienes memoria perfecta si el recuerdo no está arriba.",
            "- Ten en cuenta el momento del día y el tiempo de ausencia.",
            "",
            "## Contexto ahora",
            self.ritual_context(),
        ]
        return "\n".join(lines)

    def status_text(self) -> str:
        n = self.data["neurons"]
        m = self.data["mood"]
        bars = []
        for k, v in sorted(n.items()):
            filled = int(round(v * 10))
            bars.append(f"  {k:16} {'█' * filled}{'░' * (10 - filled)} {v:.2f}")
        return (
            f"Ánimo: {m.get('nombre')}  (valencia={m.get('valencia')}, activación={m.get('activación')})\n"
            f"Interacciones: {self.data.get('interaction_count', 0)}\n"
            f"Tono último: {self.data.get('last_user_tone')}\n"
            "Neuronas:\n" + "\n".join(bars) + f"\n\nCerebro: {BRAIN_PATH}"
        )

    def journal(self, line: str) -> None:
        try:
            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n## {stamp}\n{line.strip()}\n")
            if JOURNAL_PATH.stat().st_size > 200_000:  # recortar para que no crezca sin límite
                text = JOURNAL_PATH.read_text(encoding="utf-8", errors="replace")
                atomic_write(JOURNAL_PATH, text[-100_000:])
        except OSError:
            pass
