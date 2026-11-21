#!/usr/bin/env python3
"""Orion Code TUI — chat a pantalla completa con Textual."""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from rich.markdown import Markdown
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Input, RichLog, Static

import orion_code as oc

COMMANDS = ["/", "/clear", "/config", "/git", "/help", "/image", "/model",
            "/proyecto", "/quit", "/red", "/restaurar", "/backup", "/diario", "/compact"]


class TouchLog(RichLog):
    """Chat que se desplaza arrastrando con el dedo (o con la rueda del ratón)."""

    can_focus = False  # tocar el chat no debe quitarle el foco a la barra de entrada
    _drag_y: int | None = None

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._drag_y = event.screen_y
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag_y is None:
            return
        dy = event.screen_y - self._drag_y
        if dy:
            self._drag_y = event.screen_y
            # El dedo sube (dy < 0) => el contenido sube => bajamos en el historial.
            self.scroll_relative(y=-dy, animate=False)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._drag_y = None
        self.release_mouse()


class OrionTUI(App):
    CSS = """
    Screen { background: $background; }
    #topbar { height: 1; background: $surface; }
    #brand { width: 1fr; height: 1; padding: 0 1; background: $surface; color: $accent; text-style: bold; }
    #svg { width: 7; min-width: 0; height: 1; border: none; margin: 0; padding: 0; background: $primary; color: $text; }
    #chat { height: 1fr; border: none; padding: 0 1; overflow-x: hidden; scrollbar-size: 0 0; }
    #stream { display: none; height: auto; max-height: 10; padding: 0 1; }
    #stream.visible { display: block; }
    #hint { display: none; height: auto; padding: 0 1; background: $boost; }
    #hint.visible { display: block; }
    #status { height: 1; padding: 0 1; background: $surface; }
    #input { border: none; height: 1; margin: 0; padding: 0 1; background: $surface; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Salir"),
        Binding("ctrl+q", "quit", "Salir"),
        Binding("f1", "help", "Ayuda"),
        Binding("ctrl+s", "save_svg", "SVG"),
        Binding("pageup", "scroll_up", "Subir", show=False),
        Binding("pagedown", "scroll_down", "Bajar", show=False),
        Binding("end", "scroll_end", "Final", show=False),
    ]

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__()
        self.brain = oc.OrionBrain()
        self.sess = oc.Session(api_key, model, self.brain)
        history, self._saved_at = oc.auto_load_history()
        self.sess.history = oc.sanitize_history(history)
        self._busy = False
        self._stream_parts: list[str] = []
        self._confirm: dict | None = None
        self._busy_text = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="brand")
            yield Button("SVG", id="svg")
        yield TouchLog(id="chat", wrap=True, markup=False, highlight=False)
        yield Static(id="stream")
        yield Static(id="hint")
        yield Static(id="status")
        yield Input(placeholder="Escribe un mensaje o / para comandos", id="input")

    # ----- utilidades de UI -----

    @property
    def _chatlog(self) -> RichLog:
        return self.query_one("#chat", RichLog)

    def _say(self, text: str, style: str = "") -> None:
        self._chatlog.write(Text(str(text), style=style))
        self._chatlog.scroll_end(animate=False)

    def _say_agent(self, answer: str) -> None:
        """Respuesta del agente con Markdown renderizado (negritas, listas, bloques de código)."""
        self._chatlog.write(Text(f"{oc.agent_label()}:", style="bold green"))
        self._chatlog.write(Markdown(oc.redact_secrets(str(answer or "")).strip() or " "))
        self._chatlog.scroll_end(animate=False)

    def _ui(self, fn, *args) -> None:
        """Ejecuta fn en el hilo de la UI (seguro desde el worker)."""
        try:
            self.call_from_thread(fn, *args)
        except RuntimeError:
            fn(*args)

    def _stream_add(self, token: str) -> None:
        self._stream_parts.append(token)
        box = self.query_one("#stream", Static)
        box.update(Text("".join(self._stream_parts), style="italic"))
        box.add_class("visible")

    def _stream_end(self, text: str) -> None:
        """Un paso de texto terminó antes de una herramienta: se deja fijado en el chat."""
        self._stream_clear()
        if text and text.strip():
            self._chatlog.write(Markdown(oc.redact_secrets(text).strip()))
            self._chatlog.scroll_end(animate=False)

    def _stream_clear(self) -> None:
        self._stream_parts = []
        box = self.query_one("#stream", Static)
        box.update("")
        box.remove_class("visible")

    def _set_busy(self, text: str) -> None:
        self._busy_text = text
        self._refresh_status()

    def _refresh_status(self, busy: str | None = None) -> None:
        if busy is not None:
            self._busy_text = busy
        cwd = os.getcwd()
        if len(cwd) > 36:
            cwd = "…" + cwd[-35:]
        branch = oc.current_branch()
        extra = f" · git:{branch}" if branch else ""
        text = f" {self.sess.model} · {cwd}{extra}"
        if self._busy_text:
            text += f" · {self._busy_text}"
        self.query_one("#status", Static).update(Text(text))

    def _hide_hint(self) -> None:
        hint = self.query_one("#hint", Static)
        hint.update("")
        hint.remove_class("visible")

    # ----- hooks para el núcleo (llamados desde el worker) -----

    def _confirm_from_worker(self, action: str) -> bool:
        pending = {"event": threading.Event(), "answer": False}
        self._confirm = pending
        self._ui(self._say, f"¿Permitir {action}? Responde s / n", "bold yellow")
        pending["event"].wait(timeout=300)
        self._confirm = None
        return bool(pending["answer"])

    # ----- ciclo de vida -----

    def on_mount(self) -> None:
        oc.UI_HOOKS.update({
            "note": lambda m: self._ui(self._say, m, "dim"),
            "shell_line": lambda m: self._ui(self._say, m, "dim"),
            "stream_token": lambda t: self._ui(self._stream_add, t),
            "stream_end": lambda t: self._ui(self._stream_end, t),
            "status": lambda t: self._ui(self._set_busy, t),
            "confirm": self._confirm_from_worker,
        })
        self.query_one("#brand", Static).update(
            Text(f"  {oc.agent_label()} Code · {self.sess.model}", style="bold"))
        self._say("Orion Code TUI — PgUp/PgDn desplazar · End final · F1 ayuda", "cyan")
        if self.sess.history:
            self._say(f"Sesión restaurada ({self._saved_at}), mensajes: {len(self.sess.history)}", "dim")
        open_line = oc.proactive_open_line(self.sess.history)
        self._say(f"{oc.agent_label()}: {open_line}", "bold green")
        if not self.sess.history:
            self.sess.history.append({"role": "user", "parts": [{"text": "(inicio de sesión)"}]})
        self.sess.history.append({"role": "model", "parts": [{"text": open_line}]})
        self.sess.history[:] = oc.ensure_api_history(self.sess.history)
        oc.auto_save_history(self.sess.history)
        self._refresh_status()
        self.query_one("#input", Input).focus()

    def on_unmount(self) -> None:
        oc.UI_HOOKS.clear()

    # ----- entrada -----

    def on_input_changed(self, event: Input.Changed) -> None:
        val = (event.value or "").lower()
        hint = self.query_one("#hint", Static)
        if val.startswith("/") and len(val) < 20:
            matches = [c for c in COMMANDS if c.startswith(val)]
            if matches:
                hint.update(Text("  ".join(matches), style="dim"))
                hint.add_class("visible")
                return
        self._hide_hint()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        self._hide_hint()
        if not text:
            return

        # Respuesta a una petición de permiso pendiente.
        if self._confirm is not None:
            ok = text.lower() in oc.YES_WORDS
            self._confirm["answer"] = ok
            self._confirm["event"].set()
            self._say("→ permitido" if ok else "→ denegado", "dim")
            return

        if self._busy:
            self._say("Espera a que termine la respuesta actual.", "dim")
            return

        low = text.lower()
        shown = re.sub(r"^(/config\s+key\s+)\S+", r"\1****", text, flags=re.IGNORECASE)
        if low in ("/quit", "/exit", "/salir"):
            self.action_quit()
            return
        if low in ("/clear", "/limpiar"):
            self.sess.history.clear()
            self._chatlog.clear()
            self._say("Chat limpiado.", "dim")
            return
        if low.startswith(("/image", "/imagen")):
            self._say(f"tú> {shown}", "bold blue")
            part, question = oc.image_turn_args(text)
            if part is None:
                self._say(question, "red")
                return
            self._start_turn(question, extra_parts=[part])
            return
        if text.startswith("/"):
            self._say(f"tú> {shown}", "bold blue")
            self._say(oc.run_command(text, self.sess))
            self._refresh_status()
            return

        self._say(f"tú> {text}", "bold blue")
        self._start_turn(text)

    # ----- turnos (en segundo plano) -----

    def _start_turn(self, raw: str, extra_parts=None) -> None:
        self._busy = True
        self._stream_clear()
        self._refresh_status("pensando…")
        self._run_turn(raw, extra_parts)

    @work(thread=True, exclusive=True)
    def _run_turn(self, raw: str, extra_parts) -> None:
        try:
            answer, _streamed = oc.process_message(self.sess, raw, extra_parts=extra_parts)
        except oc.GeminiError as e:
            self._ui(self._finish_turn, None, str(e))
        except Exception as e:
            self._ui(self._finish_turn, None, f"Error inesperado: {e}")
        else:
            self._ui(self._finish_turn, answer, None)

    def _finish_turn(self, answer, error) -> None:
        self._stream_clear()
        if error:
            self._say(f"Error: {error}", "red")
        else:
            self._say_agent(answer)
        self._busy = False
        self._refresh_status()
        self.query_one("#input", Input).focus()

    # ----- acciones -----

    def action_help(self) -> None:
        self._say(oc.HELP_TEXT)

    def action_quit(self) -> None:
        oc.finish_session(self.sess)
        oc.UI_HOOKS.clear()
        self.exit()

    def action_scroll_up(self) -> None:
        self._chatlog.scroll_page_up(animate=False)

    def action_scroll_down(self) -> None:
        self._chatlog.scroll_page_down(animate=False)

    def action_scroll_end(self) -> None:
        self._chatlog.scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "svg":
            self.action_save_svg()

    def action_save_svg(self) -> None:
        from datetime import datetime

        candidates = [
            Path.home() / "storage" / "shared" / "Download",
            Path.home() / "storage" / "downloads",
            Path("/storage/emulated/0/Download"),
            ORION_HOME,
            Path.cwd(),
        ]
        folder = None
        for c in candidates:
            try:
                c.mkdir(parents=True, exist_ok=True)
                if c.is_dir():
                    folder = c
                    break
            except OSError:
                continue
        if folder is None:
            self._say("No hay carpeta escribible para el SVG.", "red")
            return
        path = folder / f"orion-tui-{datetime.now().strftime('%Y%m%d-%H%M%S')}.svg"
        try:
            self.save_screenshot(filename=str(path))
            self._say(f"SVG guardado: {path}", "green")
        except Exception as e:
            self._say(f"No se pudo guardar el SVG: {e}", "yellow")


ORION_HOME = Path.home() / ".orion-code"


def main(api_key: str | None = None, model: str | None = None) -> None:
    api_key = api_key or oc.load_api_key()
    model = model or oc.load_saved_model(oc.DEFAULT_MODEL)
    OrionTUI(api_key, model).run()


if __name__ == "__main__":
    main()
