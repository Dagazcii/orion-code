"""
/help de AegisBot: cómo usar cada comando (solo administradores), en el idioma del servidor.

Va en la misma carpeta que bot.py. bot.py lo carga con load_extension("ayuda")
y le da bot.idioma_de(guild_id) -> "es" | "en". No importa nada de bot.py.

Agregar un comando nuevo a la ayuda: una llamada a _cmd() en la sección
correspondiente, con los textos en es y en. Al cargar se valida que no falte nada.
"""

import discord
from discord import app_commands
from discord.ext import commands

IDIOMAS = ("es", "en")

TEXTOS = {
    "es": {
        "titulo": "📖 AegisBot · Ayuda",
        "inicio": ("Elige una categoría en el primer menú y después un comando en el segundo "
                   "para ver cómo se usa.\n"
                   "Atajo: `/help comando:ban`.\n"
                   "Solo administradores. Idioma del bot: **Español** (`/config language`)."),
        "uso": "Uso",
        "permiso": "Permiso",
        "pasos": "Paso a paso",
        "nota": "Nota",
        "opcional": "Lo que va entre [ ] es opcional.",
        "elige_cat": "Categoría…",
        "elige_cmd": "Comando…",
        "inicio_btn": "Inicio",
        "n_cmds": "{n} comandos",
        "no_existe": "No encontré el comando `/{c}`.",
        "parecidos": "Parecidos: {s}",
        "usa_help": "Usa `/help` y elígelo de la lista.",
        "solo_autor": "Este menú es de quien ejecutó `/help`. Abre el tuyo con `/help`.",
        "pie_cat": "Elige un comando en el segundo menú.",
    },
    "en": {
        "titulo": "📖 AegisBot · Help",
        "inicio": ("Pick a category in the first menu, then a command in the second one "
                   "to see how to use it.\n"
                   "Shortcut: `/help comando:ban`.\n"
                   "Administrators only. Bot language: **English** (`/config language`)."),
        "uso": "Usage",
        "permiso": "Permission",
        "pasos": "Step by step",
        "nota": "Note",
        "opcional": "Anything inside [ ] is optional.",
        "elige_cat": "Category…",
        "elige_cmd": "Command…",
        "inicio_btn": "Home",
        "n_cmds": "{n} commands",
        "no_existe": "I couldn't find the command `/{c}`.",
        "parecidos": "Similar: {s}",
        "usa_help": "Use `/help` and pick it from the list.",
        "solo_autor": "This menu belongs to whoever ran `/help`. Open your own with `/help`.",
        "pie_cat": "Pick a command in the second menu.",
    },
}

CATEGORIAS = {
    "limpieza": {"icono": "🧹", "es": "Limpieza de canales", "en": "Channel cleanup"},
    "mod": {"icono": "🔨", "es": "Moderación", "en": "Moderation"},
    "warns": {"icono": "⚠️", "es": "Advertencias (warns)", "en": "Warnings (warns)"},
    "reportes": {"icono": "🚨", "es": "Red global de reportes", "en": "Global report network"},
    "tickets": {"icono": "🎫", "es": "Tickets", "en": "Tickets"},
    "sugerencias": {"icono": "💡", "es": "Sugerencias", "en": "Suggestions"},
    "extras": {"icono": "🎮", "es": "Utilidades y comunidad", "en": "Utilities and community"},
    "config_gen": {"icono": "⚙️", "es": "Config · General", "en": "Config · General"},
    "config_seg": {"icono": "🛡️", "es": "Config · Seguridad", "en": "Config · Security"},
    "config_mod": {"icono": "🧩", "es": "Config · Módulos", "en": "Config · Modules"},
}

COMANDOS: dict[str, dict] = {}


def _cmd(clave, cat, uso, perm, desc, pasos, nota=None):
    """perm, desc y nota son tuplas (es, en); pasos es ([es...], [en...])."""
    COMANDOS[clave] = {
        "cat": cat,
        "uso": uso,
        "perm": dict(zip(IDIOMAS, perm)),
        "desc": dict(zip(IDIOMAS, desc)),
        "pasos": dict(zip(IDIOMAS, pasos)),
        "nota": dict(zip(IDIOMAS, nota)) if nota else None,
    }


P_ADMIN = ("Administrador", "Administrator")
P_TODOS = ("Cualquier miembro", "Any member")
P_MOD = ("Moderador: Administrar servidor, Administrar mensajes o un rol mod (`/config modrole`)",
         "Moderator: Manage Server, Manage Messages or a mod role (`/config modrole`)")
P_MSG = ("Administrar mensajes o Administrador (un rol mod no alcanza)",
         "Manage Messages or Administrator (a mod role is not enough)")


def _p_rol(es, en):
    return (f"{es}, o un rol mod (`/config modrole`)", f"{en}, or a mod role (`/config modrole`)")


# ------------------------------------------------------------
# Limpieza
# ------------------------------------------------------------
_cmd("clear", "limpieza", "/clear", P_MSG,
     ("Borra todo el canal menos los mensajes con link o video.",
      "Deletes the whole channel except messages with a link or video."),
     ([
         "Entra al canal que quieres limpiar y ejecuta `/clear`.",
         "El bot te muestra un aviso (solo lo ves tú) con los botones Confirmar y Cancelar. Tienes 30 segundos.",
         "Al confirmar, borra por lotes los mensajes de menos de 14 días. Conserva los que tengan un link, "
         "un embed de link/imagen/video o un video adjunto.",
         "Después revisa los de más de 14 días y los borra uno por uno (límite de Discord, ~1 por segundo). "
         "En canales grandes puede tardar horas; avisa el progreso cada 50 mensajes revisados.",
         "Al terminar recibes el resumen: recientes borrados, antiguos borrados y conservados.",
     ], [
         "Go to the channel you want to clean and run `/clear`.",
         "The bot shows a notice (only you see it) with Confirm and Cancel buttons. You have 30 seconds.",
         "On confirm, it bulk-deletes messages newer than 14 days. It keeps the ones with a link, "
         "a link/image/video embed or an attached video.",
         "Then it goes through messages older than 14 days and deletes them one by one (Discord limit, "
         "~1 per second). In big channels this can take hours; it reports progress every 50 messages checked.",
         "When done you get the summary: recent deleted, old deleted and kept.",
     ]),
     ("Mientras limpia, esos borrados no se mandan al canal de logs.",
      "While it runs, those deletions are not sent to the log channel."))

_cmd("clearuser", "limpieza", "/clearuser usuario [cantidad]", P_MSG,
     ("Borra los mensajes de una persona en este canal.",
      "Deletes one person's messages in this channel."),
     ([
         "Ejecuta `/clearuser` en el canal donde están los mensajes y elige `usuario` (mención o ID).",
         "Opcional: `cantidad` (1 a 100) para borrar solo sus N mensajes más recientes.",
         "Con `cantidad` borra directo, sin confirmación. Sin `cantidad` pide confirmación con botones (30 s) "
         "y borra todos sus mensajes del canal.",
         "Primero borra por lotes los de menos de 14 días. Si con `cantidad` no llega al número, sigue con "
         "los más antiguos, uno por uno.",
         "Avisa el progreso cada 50 mensajes antiguos y el total al final.",
     ], [
         "Run `/clearuser` in the channel where the messages are and pick `usuario` (mention or ID).",
         "Optional: `cantidad` (1 to 100) to delete only their N most recent messages.",
         "With `cantidad` it deletes right away, no confirmation. Without it, it asks for confirmation with "
         "buttons (30 s) and deletes all their messages in the channel.",
         "It bulk-deletes the ones newer than 14 days first. If `cantidad` isn't reached, it continues with "
         "older ones, one by one.",
         "It reports progress every 50 old messages and the total at the end.",
     ]),
     ("Solo actúa en el canal donde lo ejecutas.", "It only acts on the channel where you run it."))

_cmd("clearall", "limpieza", "/clearall", P_MSG,
     ("Vacía el canal por completo, sin excepciones.", "Empties the channel completely, no exceptions."),
     ([
         "Ejecuta `/clearall` en el canal que quieres vaciar.",
         "Confirma con el botón (30 s). El aviso te recuerda que se borra todo: texto, links, videos, fotos y "
         "adjuntos de cualquier persona.",
         "Borra por lotes lo de menos de 14 días y después lo más antiguo, uno por uno (lento).",
         "Recibes el resumen con el total eliminado.",
     ], [
         "Run `/clearall` in the channel you want to empty.",
         "Confirm with the button (30 s). The notice reminds you everything goes: text, links, videos, photos "
         "and attachments from anyone.",
         "It bulk-deletes what is newer than 14 days, then the older messages one by one (slow).",
         "You get the summary with the total deleted.",
     ]),
     ("A diferencia de `/clear`, no conserva links ni videos.",
      "Unlike `/clear`, it does not keep links or videos."))

_cmd("purge", "limpieza", "/purge cantidad [usuario]", _p_rol("Administrar mensajes", "Manage Messages"),
     ("Borra hasta 500 mensajes recientes (menos de 14 días).",
      "Deletes up to 500 recent messages (under 14 days old)."),
     ([
         "Ejecuta `/purge` con `cantidad` (1 a 500). Opcional: `usuario` para borrar solo los suyos.",
         "Confirma con el botón (30 s).",
         "Toma los mensajes más recientes del canal, solo de menos de 14 días, hasta completar la cantidad y "
         "los borra por lotes. Los fijados no se tocan.",
         "Si hay menos mensajes de los pedidos, borra los que haya.",
         "Recibes el total borrado y queda registro en el canal de logs.",
     ], [
         "Run `/purge` with `cantidad` (1 to 500). Optional: `usuario` to delete only theirs.",
         "Confirm with the button (30 s).",
         "It takes the most recent messages in the channel, only under 14 days old, until the amount is "
         "reached and bulk-deletes them. Pinned messages are left alone.",
         "If there are fewer messages than requested, it deletes what there is.",
         "You get the total deleted and it is recorded in the log channel.",
     ]),
     ("Para mensajes de más de 14 días usa `/clear`, `/clearuser` o `/clearall`.",
      "For messages older than 14 days use `/clear`, `/clearuser` or `/clearall`."))

# ------------------------------------------------------------
# Moderación
# ------------------------------------------------------------
_cmd("ban", "mod", "/ban usuario [motivo] [borrar_dias]", _p_rol("Banear miembros", "Ban Members"),
     ("Banea a un usuario del servidor.", "Bans a user from the server."),
     ([
         "Ejecuta `/ban` y elige `usuario`. Puede ser alguien que ya no esté en el servidor.",
         "Opcional: `motivo` y `borrar_dias` (0 a 7) para borrar sus mensajes recientes.",
         "El bot valida la jerarquía: no puedes banearte a ti, al dueño del servidor ni a alguien con un rol "
         "igual o superior al tuyo o al del bot.",
         "Te pide confirmación con botones (30 s).",
         "Aplica el ban con el motivo en el registro de auditoría de Discord y lo anota en el canal de logs.",
     ], [
         "Run `/ban` and pick `usuario`. It can be someone who is no longer in the server.",
         "Optional: `motivo` and `borrar_dias` (0 to 7) to delete their recent messages.",
         "The bot checks the hierarchy: you can't ban yourself, the server owner or anyone with a role equal "
         "to or higher than yours or the bot's.",
         "It asks for confirmation with buttons (30 s).",
         "It applies the ban with the reason in Discord's audit log and records it in the log channel.",
     ]))

_cmd("unban", "mod", "/unban usuario_id [motivo]", _p_rol("Banear miembros", "Ban Members"),
     ("Quita el ban a un usuario por ID.", "Removes a user's ban by ID."),
     ([
         "Consigue la ID del usuario baneado: aparece en la lista de baneos del servidor y, con el modo "
         "desarrollador activo, la puedes copiar.",
         "Ejecuta `/unban` con `usuario_id` y, si quieres, `motivo`.",
         "Si esa persona no está baneada, el bot te lo dice. Si lo está, la desbanea al instante (sin "
         "confirmación) y queda en el canal de logs.",
     ], [
         "Get the banned user's ID: it shows in the server's ban list and, with developer mode on, you can "
         "copy it.",
         "Run `/unban` with `usuario_id` and, optionally, `motivo`.",
         "If that person isn't banned, the bot tells you. If they are, it unbans them right away (no "
         "confirmation) and it is recorded in the log channel.",
     ]))

_cmd("kick", "mod", "/kick usuario [motivo]", _p_rol("Expulsar miembros", "Kick Members"),
     ("Expulsa a un miembro del servidor.", "Kicks a member from the server."),
     ([
         "Ejecuta `/kick` y elige un miembro (tiene que estar en el servidor). Opcional: `motivo`.",
         "Valida la jerarquía igual que `/ban`.",
         "Pide confirmación con botones (30 s).",
         "Lo expulsa y lo anota en el canal de logs. Puede volver a entrar con una invitación.",
     ], [
         "Run `/kick` and pick a member (they must be in the server). Optional: `motivo`.",
         "It checks the hierarchy the same way as `/ban`.",
         "It asks for confirmation with buttons (30 s).",
         "It kicks them and records it in the log channel. They can rejoin with an invite.",
     ]))

_cmd("mute", "mod", "/mute usuario [minutos] [motivo]",
     _p_rol("Aislar temporalmente a miembros", "Timeout Members"),
     ("Silencia (timeout) a un miembro.", "Mutes (timeout) a member."),
     ([
         "Ejecuta `/mute` y elige un miembro.",
         "`minutos`: de 1 a 40320 (28 días); por defecto 10. Opcional: `motivo`.",
         "Valida la jerarquía y aplica el aislamiento (timeout) de Discord. No pide confirmación.",
         "Queda en el canal de logs. La persona no puede escribir, reaccionar ni hablar en voz hasta que pase "
         "el tiempo o hagas `/unmute`.",
     ], [
         "Run `/mute` and pick a member.",
         "`minutos`: from 1 to 40320 (28 days); default 10. Optional: `motivo`.",
         "It checks the hierarchy and applies Discord's timeout. No confirmation.",
         "It is recorded in the log channel. The person can't write, react or speak in voice until the time "
         "passes or you run `/unmute`.",
     ]))

_cmd("unmute", "mod", "/unmute usuario", _p_rol("Aislar temporalmente a miembros", "Timeout Members"),
     ("Quita el silencio a un miembro.", "Removes a member's mute."),
     ([
         "Ejecuta `/unmute` y elige al miembro.",
         "El bot le quita el aislamiento de inmediato y lo anota en el canal de logs.",
     ], [
         "Run `/unmute` and pick the member.",
         "The bot removes the timeout immediately and records it in the log channel.",
     ]))

_cmd("lock", "mod", "/lock [canal]", _p_rol("Gestionar canales", "Manage Channels"),
     ("Bloquea un canal: nadie puede escribir.", "Locks a channel: nobody can write."),
     ([
         "Ejecuta `/lock` en el canal a bloquear, o indica `canal`.",
         "El bot le quita a @everyone el permiso de escribir en ese canal.",
         "Solo funciona en canales de texto. Los roles con permiso explícito de escribir ahí (por ejemplo "
         "mods) siguen pudiendo.",
         "Queda en el canal de logs. Para revertirlo usa `/unlock`.",
     ], [
         "Run `/lock` in the channel to lock, or set `canal`.",
         "The bot removes @everyone's permission to write in that channel.",
         "Text channels only. Roles with an explicit permission to write there (mods, for example) can "
         "still do it.",
         "It is recorded in the log channel. To undo it use `/unlock`.",
     ]))

_cmd("unlock", "mod", "/unlock [canal]", _p_rol("Gestionar canales", "Manage Channels"),
     ("Desbloquea un canal.", "Unlocks a channel."),
     ([
         "Ejecuta `/unlock` en el canal bloqueado, o indica `canal`.",
         "El bot quita el bloqueo de escritura de @everyone y deja el permiso como estaba (heredado). Si el "
         "overwrite queda vacío, lo elimina.",
         "Queda en el canal de logs.",
     ], [
         "Run `/unlock` in the locked channel, or set `canal`.",
         "The bot removes @everyone's write block and leaves the permission as it was (inherited). If the "
         "overwrite ends up empty, it deletes it.",
         "It is recorded in the log channel.",
     ]))

_cmd("lockdown", "mod", "/lockdown accion [minutos]", _p_rol("Gestionar canales", "Manage Channels"),
     ("Activa o desactiva el bloqueo total de canales.", "Turns the server-wide channel lock on or off."),
     ([
         "`/lockdown accion:activar` bloquea la escritura de @everyone en **todos** los canales de texto. "
         "`minutos` (1 a 1440, por defecto 10) define cuánto dura.",
         "Los canales que ya estaban bloqueados no se tocan; el bot guarda el estado anterior de los demás "
         "para restaurarlos.",
         "Termina solo al pasar el tiempo. Si reinicias el bot, el fin se reprograma al arrancar.",
         "`/lockdown accion:desactivar` lo levanta antes de tiempo. Si ya hay uno activo, el bot lo avisa.",
     ], [
         "`/lockdown accion:activar` blocks @everyone from writing in **all** text channels. `minutos` "
         "(1 to 1440, default 10) sets how long it lasts.",
         "Channels that were already locked are left alone; the bot saves the previous state of the rest to "
         "restore them.",
         "It ends by itself when the time is up. If you restart the bot, the end is rescheduled on startup.",
         "`/lockdown accion:desactivar` lifts it early. If one is already active, the bot says so.",
     ]),
     ("El anti-raid lo activa solo; mira `/config antiraid`.",
      "The anti-raid turns it on by itself; see `/config antiraid`."))

_cmd("slowmode", "mod", "/slowmode segundos [canal]", _p_rol("Gestionar canales", "Manage Channels"),
     ("Cambia el modo lento de un canal.", "Changes a channel's slowmode."),
     ([
         "Ejecuta `/slowmode` con `segundos` (0 a 21600). `0` lo quita.",
         "Opcional: `canal`; por defecto el actual (solo canales de texto).",
         "Discord limita cuánto escribe cada persona: un mensaje cada N segundos.",
     ], [
         "Run `/slowmode` with `segundos` (0 to 21600). `0` removes it.",
         "Optional: `canal`; defaults to the current one (text channels only).",
         "Discord limits how often each person can write: one message every N seconds.",
     ]))

_cmd("userinfo", "mod", "/userinfo [usuario]", P_MOD,
     ("Información de un miembro.", "Information about a member."),
     ([
         "Ejecuta `/userinfo` y elige un miembro; sin parámetro, te muestra a ti.",
         "Verás: ID, creación de la cuenta, cuándo entró, roles (hasta 15), cantidad de warns y reportes "
         "aprobados en la red global.",
         "La respuesta solo la ves tú.",
     ], [
         "Run `/userinfo` and pick a member; without a parameter it shows you.",
         "You'll see: ID, account creation, when they joined, roles (up to 15), number of warns and approved "
         "reports in the global network.",
         "Only you see the reply.",
     ]))

_cmd("verify", "mod", "/verify usuario", P_MOD,
     ("Da acceso manual a un miembro pendiente de presentación.",
      "Manually grants access to a member pending introduction."),
     ([
         "Sirve cuando el canal de presentación está activo (`/presentacion`).",
         "Ejecuta `/verify` y elige al miembro que sigue con el rol \"Sin presentar\".",
         "El bot le quita ese rol y le da el rol de miembro si lo configuraste. Al dejar de tener el rol "
         "pendiente, ya no puede escribir en el canal de presentación.",
         "Si el miembro no estaba pendiente, el bot lo dice y no cambia nada.",
     ], [
         "It applies when the introduction channel is on (`/introduction`).",
         "Run `/verify` and pick the member who still has the \"Sin presentar\" role.",
         "The bot removes that role and gives the member role if you set one. Once they lose the pending "
         "role, they can no longer write in the introduction channel.",
         "If the member wasn't pending, the bot says so and changes nothing.",
     ]))

_cmd("audit", "mod", "/audit [canal]", P_ADMIN,
     ("Revisa quién tiene acceso a canales privados.", "Checks who has access to private channels."),
     ([
         "Ejecuta `/audit` sin parámetros para revisar todos los canales privados, o con `canal` para uno "
         "en concreto.",
         "Un canal cuenta como privado si @everyone tiene \"Ver canal\" denegado.",
         "Por cada canal lista quién puede entrar: roles y usuarios con permiso explícito, y roles con "
         "Administrador (que ignoran los permisos del canal).",
         "Compara con los roles autorizados de `/config auditroles`. Si no configuraste ninguno, usa la "
         "lista fija del código (ALLOWED_ROLE_IDS).",
         "Responde con un embed por canal con \"Acceso inesperado\" (usuarios con permiso individual y roles "
         "no autorizados) y \"Acceso esperado\" como referencia. Los canales sin anomalías no aparecen.",
     ], [
         "Run `/audit` with no parameters to check every private channel, or with `canal` for a specific one.",
         "A channel counts as private if @everyone has \"View Channel\" denied.",
         "For each channel it lists who can get in: roles and users with an explicit permission, and roles "
         "with Administrator (which ignore channel permissions).",
         "It compares against the authorized roles from `/config auditroles`. If you set none, it uses the "
         "fixed list in the code (ALLOWED_ROLE_IDS).",
         "It replies with one embed per channel showing \"Unexpected access\" (users with an individual "
         "permission and unauthorized roles) and \"Expected access\" as reference. Channels with no "
         "anomalies are not listed.",
     ]))

# ------------------------------------------------------------
# Warns
# ------------------------------------------------------------
_cmd("warn", "warns", "/warn usuario motivo", _p_rol("Aislar temporalmente a miembros", "Timeout Members"),
     ("Advierte a un miembro; al llegar al umbral hay sanción automática.",
      "Warns a member; reaching the threshold triggers an automatic penalty."),
     ([
         "Ejecuta `/warn` con `usuario` (miembro) y `motivo`.",
         "Valida la jerarquía y guarda el warn con fecha y moderador.",
         "Si llega al umbral de `/config warns` (por defecto 3), aplica la sanción automática (mute o kick) "
         "y reinicia sus warns a cero.",
         "La persona recibe un DM con el motivo (si los tiene cerrados, el bot sigue igual) y queda en el "
         "canal de logs con el total, por ejemplo 2/3.",
     ], [
         "Run `/warn` with `usuario` (member) and `motivo`.",
         "It checks the hierarchy and saves the warn with date and moderator.",
         "If it reaches the `/config warns` threshold (default 3), it applies the automatic penalty (mute or "
         "kick) and resets their warns to zero.",
         "The person gets a DM with the reason (if their DMs are closed, the bot carries on) and it is "
         "recorded in the log channel with the total, e.g. 2/3.",
     ]))

_cmd("warns", "warns", "/warns usuario", _p_rol("Aislar temporalmente a miembros", "Timeout Members"),
     ("Muestra los warns de un miembro.", "Shows a member's warns."),
     ([
         "Ejecuta `/warns` y elige un usuario.",
         "Muestra la lista numerada con fecha, moderador y motivo.",
         "Ese número es el que usas en `/unwarn`.",
     ], [
         "Run `/warns` and pick a user.",
         "It shows the numbered list with date, moderator and reason.",
         "That number is the one you use in `/unwarn`.",
     ]))

_cmd("unwarn", "warns", "/unwarn usuario numero", _p_rol("Aislar temporalmente a miembros", "Timeout Members"),
     ("Quita un warn específico.", "Removes one specific warn."),
     ([
         "Mira el número del warn con `/warns`.",
         "Ejecuta `/unwarn usuario numero`.",
         "El warn se elimina y los siguientes suben una posición; vuelve a mirar `/warns` antes de borrar otro.",
     ], [
         "Check the warn's number with `/warns`.",
         "Run `/unwarn usuario numero`.",
         "The warn is removed and the following ones move up one position; check `/warns` again before "
         "removing another.",
     ]))

_cmd("clearwarns", "warns", "/clearwarns usuario",
     _p_rol("Aislar temporalmente a miembros", "Timeout Members"),
     ("Borra todos los warns de un usuario.", "Clears all of a user's warns."),
     ([
         "Ejecuta `/clearwarns` y elige al usuario.",
         "Borra todos sus warns sin pedir confirmación.",
     ], [
         "Run `/clearwarns` and pick the user.",
         "It clears all their warns without asking for confirmation.",
     ]))

# ------------------------------------------------------------
# Red de reportes
# ------------------------------------------------------------
_cmd("report", "reportes", "/report usuario motivo enlace", P_MOD,
     ("Reporta a un usuario malicioso a la red global.", "Reports a malicious user to the global network."),
     ([
         "Ejecuta `/report` con `usuario`, `motivo` (mínimo 5 caracteres) y `enlace` a la evidencia "
         "(captura, video o mensaje de Discord, empezando con http:// o https://).",
         "No puedes reportar bots ni a ti mismo. Cada servidor tiene un solo reporte por usuario: uno nuevo "
         "reemplaza al anterior.",
         "El reporte queda pendiente y le llega al dueño del bot, en su canal de revisión, con botones "
         "Aprobar y Rechazar.",
         "Solo cuando se aprueba entra en la red: si ese usuario se une a cualquier servidor con el bot, "
         "ese servidor recibe una alerta (canal de logs o DM al dueño).",
         "Cuando el dueño decide, tu servidor recibe el resultado en su canal de logs.",
     ], [
         "Run `/report` with `usuario`, `motivo` (at least 5 characters) and a `enlace` to the evidence "
         "(screenshot, video or Discord message, starting with http:// or https://).",
         "You can't report bots or yourself. Each server has one report per user: a new one replaces the "
         "previous one.",
         "The report stays pending and reaches the bot owner in their review channel, with Approve and "
         "Reject buttons.",
         "Only once approved does it enter the network: if that user joins any server with the bot, that "
         "server gets an alert (log channel or DM to the owner).",
         "When the owner decides, your server gets the result in its log channel.",
     ]))

_cmd("reportinfo", "reportes", "/reportinfo usuario", P_MOD,
     ("Consulta los reportes aprobados de un usuario.", "Looks up a user's approved reports."),
     ([
         "Ejecuta `/reportinfo` y elige al usuario.",
         "Muestra hasta 10 reportes aprobados: servidor, fecha y motivo.",
         "Si tu servidor tiene un reporte pendiente de ese usuario, también te lo indica.",
     ], [
         "Run `/reportinfo` and pick the user.",
         "It shows up to 10 approved reports: server, date and reason.",
         "If your server has a pending report on that user, it tells you too.",
     ]))

_cmd("reportremove", "reportes", "/reportremove usuario", P_MOD,
     ("Retira el reporte que este servidor hizo a un usuario.",
      "Withdraws the report this server made on a user."),
     ([
         "Ejecuta `/reportremove` y elige al usuario.",
         "El bot borra el reporte de tu servidor sobre esa persona, esté pendiente o aprobado.",
         "Los reportes de otros servidores no se tocan. Si tu servidor no tiene uno, te lo dice.",
     ], [
         "Run `/reportremove` and pick the user.",
         "The bot deletes your server's report on that person, pending or approved.",
         "Other servers' reports are untouched. If your server has none, it tells you.",
     ]))

_cmd("reportadmin", "reportes", "/reportadmin accion [usuario] [servidor_id]",
     ("Solo el dueño del bot", "Bot owner only"),
     ("(Dueño del bot) Gestiona la red global de reportes.", "(Bot owner) Manages the global report network."),
     ([
         "`/reportadmin accion:pendientes` lista hasta 20 reportes pendientes, con link al mensaje de revisión.",
         "`aprobar`, `rechazar` o `eliminar` requieren `usuario`. `servidor_id` limita la acción al reporte "
         "de ese servidor; sin él se aplica a todos los de ese usuario.",
         "Aprobar o rechazar también se puede con los botones del mensaje de revisión.",
         "Cada decisión se avisa en el canal de logs del servidor que reportó.",
     ], [
         "`/reportadmin accion:pendientes` lists up to 20 pending reports, with a link to the review message.",
         "`aprobar`, `rechazar` or `eliminar` require `usuario`. `servidor_id` limits the action to that "
         "server's report; without it, it applies to all of that user's reports.",
         "Approving or rejecting can also be done with the buttons on the review message.",
         "Each decision is announced in the log channel of the server that reported.",
     ]))

# ------------------------------------------------------------
# Tickets
# ------------------------------------------------------------



_cmd("confess", "extras", "/confess mensaje", P_TODOS,
     ("Envía una confesión anónima al canal de confesiones.", "Sends an anonymous confession to the confessions channel."),
     ([
         "Un admin la activa antes con `/config confess`.",
         "Ejecuta `/confess mensaje` (hasta 1500 caracteres) solo en el canal de confesiones.",
         "Se rechaza si contiene palabras del filtro del AutoMod o invitaciones de Discord. Hay un enfriamiento "
         "de 30 segundos por persona.",
         "El bot publica un embed \"Confesión #N\" sin tu nombre; la respuesta del comando solo la ves tú.",
     ], [
         "An admin turns it on first with `/config confess`.",
         "Run `/confess mensaje` (up to 1500 characters) only in the confessions channel.",
         "It is rejected if it contains words from the AutoMod filter or Discord invites. There is a "
         "30-second cooldown per person.",
         "The bot posts a \"Confession #N\" embed without your name; the command's reply is only visible to you.",
     ]),
     ("Es anónima para los demás miembros,"
      "().",
      "It is anonymous to other members,"
      "()."))

_cmd("giveaways", "extras", "/giveaways [plataforma]", P_TODOS,
     ("Muestra los juegos gratis disponibles ahora (GamerPower).", "Shows the free games available right now (GamerPower)."),
     ([
         "Ejecuta `/giveaways`. Opcional: `plataforma` (PC, Steam, Epic Games, GOG, itch.io, PS5, PS4, Xbox, "
         "Switch, Android, iOS); sin ella muestra todas.",
         "El bot consulta GamerPower y muestra hasta 8 juegos por popularidad: valor, plataformas y fecha de "
         "fin, con link para reclamarlo.",
         "La respuesta solo la ves tú.",
     ], [
         "Run `/giveaways`. Optional: `plataforma` (PC, Steam, Epic Games, GOG, itch.io, PS5, PS4, Xbox, "
         "Switch, Android, iOS); without it, it shows all.",
         "The bot queries GamerPower and shows up to 8 games by popularity: worth, platforms and end date, "
         "with a link to claim it.",
         "Only you see the reply.",
     ]),
     ("Un admin puede dejar un tablero que se actualiza solo con `/config giveaway`.",
      "An admin can set up a self-updating board with `/config giveaway`."))

_cmd("weather", "extras", "/weather ciudad", P_TODOS,
     ("Clima actual de una ciudad.", "Current weather for a city."),
     ([
         "Ejecuta `/weather` con `ciudad` (2 a 80 caracteres).",
         "El bot busca la ciudad en Open-Meteo y usa el primer resultado.",
         "Responde con condición, temperatura, sensación térmica, humedad, viento y precipitación.",
         "La respuesta es pública. Si no es la ciudad que querías, prueba con otro nombre.",
     ], [
         "Run `/weather` with `ciudad` (2 to 80 characters).",
         "The bot looks the city up on Open-Meteo and uses the first result.",
         "It replies with conditions, temperature, feels-like, humidity, wind and precipitation.",
         "The reply is public. If it isn't the city you meant, try another name.",
     ]))

_cmd("ping", "extras", "/ping", P_TODOS,
     ("Prueba que el bot responde.", "Tests that the bot responds."),
     ([
         "Ejecuta `/ping`.",
         "El bot responde con su latencia en milisegundos. Solo lo ves tú.",
     ], [
         "Run `/ping`.",
         "The bot replies with its latency in milliseconds. Only you see it.",
     ]))

_cmd("help", "extras", "/help [comando]", P_ADMIN,
     ("Cómo usar cada comando del bot (solo administradores).",
      "How to use each bot command (administrators only)."),
     ([
         "Ejecuta `/help` y elige una categoría en el primer menú.",
         "Elige un comando en el segundo menú para ver el uso, el permiso y el paso a paso.",
         "Atajo: `/help comando:ban` abre directo ese comando (el campo autocompleta).",
         "Solo lo ven los administradores. Los menús expiran a los 3 minutos.",
     ], [
         "Run `/help` and pick a category in the first menu.",
         "Pick a command in the second menu to see usage, permission and step by step.",
         "Shortcut: `/help comando:ban` opens that command directly (the field autocompletes).",
         "Administrators only. Menus expire after 3 minutes.",
     ]))


_cmd("config panel", "config_gen", "/config panel", P_ADMIN,
     ("Menú principal de configuración del servidor (seguridad, logs, tickets, bienvenida, roles…).",
      "Main server configuration menu (security, logs, tickets, welcome, roles…)."),
     ([
         "Ejecuta `/config panel` — es el único menú para abrir paneles de configuración.",
         "Elige una sección: AutoMod, anti-spam, anti-raid, bienvenida, logs, presentación, tickets, sugerencias o roles por reacción.",
         "Se abre el panel de esa sección. No hace falta memorizar otros comandos de panel.",
         "Atajos que siguen: `/config language`, `/config modrole`, `/config logchannel`, `/config words`, etc.",
     ], [
         "Run `/config panel` — the only menu to open configuration panels.",
         "Pick a section: AutoMod, anti-spam, anti-raid, welcome, logs, introduction, tickets, suggestions or reaction roles.",
         "That section's panel opens. You don't need other panel commands.",
         "Shortcuts that remain: `/config language`, `/config modrole`, `/config logchannel`, `/config words`, etc.",
     ]))

_cmd("config language", "config_gen", "/config language idioma", P_ADMIN,
     ("Cambia el idioma del bot en este servidor.", "Changes the bot's language in this server."),
     ([
         "Ejecuta `/config language` y elige Español o English.",
         "Desde ese momento los mensajes, avisos, la tarjeta de bienvenida y este `/help` salen en ese idioma.",
         "Aplica a todo el servidor, no solo a ti.",
     ], [
         "Run `/config language` and pick Español or English.",
         "From then on messages, notices, the welcome card and this `/help` come out in that language.",
         "It applies to the whole server, not just you.",
     ]))

_cmd("config modrole", "config_gen", "/config modrole accion rol", P_ADMIN,
     ("Agrega o quita un rol de moderador.", "Adds or removes a moderator role."),
     ([
         "Ejecuta `/config modrole`, elige `add` o `remove` y el `rol`.",
         "Quien tenga ese rol puede usar los comandos de moderación sin tener el permiso real de Discord "
         "(ban, kick, mute, warns, lock, purge, report, userinfo, verify…) y puede cerrar tickets.",
         "Además queda exento del AutoMod y del anti-spam.",
         "No da acceso a `/config`, `/audit`, `/tickets` ni a `/clear`, `/clearuser`, `/clearall`.",
     ], [
         "Run `/config modrole`, pick `add` or `remove` and the `rol`.",
         "Anyone with that role can use the moderation commands without the real Discord permission "
         "(ban, kick, mute, warns, lock, purge, report, userinfo, verify…) and can close tickets.",
         "They are also exempt from AutoMod and anti-spam.",
         "It doesn't grant access to `/config`, `/audit`, `/tickets` or `/clear`, `/clearuser`, `/clearall`.",
     ]),
     ("El bot sigue necesitando los permisos reales para ejecutar la acción.",
      "The bot still needs the real permissions to carry out the action."))

_cmd("config logchannel", "config_gen", "/config logchannel canal", P_ADMIN,
     ("Define el canal de logs y alertas.", "Sets the log and alert channel."),
     ([
         "Ejecuta `/config logchannel` y elige el `canal`.",
         "El bot comprueba que pueda ver, escribir y mandar embeds ahí; si no, no lo guarda.",
         "Ahí llegan: sanciones, AutoMod, anti-spam, anti-raid, cuentas nuevas, entradas y salidas, mensajes "
         "borrados y editados, resultados de reportes y transcripts de tickets (si no hay canal de "
         "transcripts).",
         "Sin canal de logs, las alertas importantes (raid, usuarios reportados) van por DM al dueño del servidor.",
     ], [
         "Run `/config logchannel` and pick the `canal`.",
         "The bot checks it can view, write and send embeds there; if not, it doesn't save it.",
         "That's where these go: penalties, AutoMod, anti-spam, anti-raid, new accounts, joins and leaves, "
         "deleted and edited messages, report results and ticket transcripts (if there is no transcripts "
         "channel).",
         "With no log channel, important alerts (raid, reported users) go by DM to the server owner.",
     ]))



_cmd("config auditroles", "config_gen", "/config auditroles accion [rol]", P_ADMIN,
     ("Roles autorizados a ver canales privados (para /audit).", "Roles authorized to see private channels (for /audit)."),
     ([
         "Ejecuta `/config auditroles` con `add` o `remove` y el `rol`.",
         "`list` muestra los roles que `/audit` va a considerar esperados ahora mismo.",
         "Si no agregas ninguno, `/audit` usa la lista fija del código (ALLOWED_ROLE_IDS).",
     ], [
         "Run `/config auditroles` with `add` or `remove` and the `rol`.",
         "`list` shows the roles `/audit` will treat as expected right now.",
         "If you add none, `/audit` uses the fixed list in the code (ALLOWED_ROLE_IDS).",
     ]))

_cmd("config autorole", "config_gen", "/config autorole [rol] [quitar]", P_ADMIN,
     ("Rol que se da automáticamente a quien entra.", "Role given automatically to whoever joins."),
     ([
         "Ejecuta `/config autorole` y elige el `rol`.",
         "El bot lo rechaza si está por encima de su rol más alto, si es @everyone o si es un rol de "
         "sistema (de un bot o integración).",
         "Desde ese momento, cada miembro nuevo lo recibe al entrar.",
         "Para desactivarlo: `/config autorole quitar:True`.",
     ], [
         "Run `/config autorole` and pick the `rol`.",
         "The bot rejects it if it is above its highest role, if it is @everyone or if it is a managed "
         "role (from a bot or integration).",
         "From then on, every new member gets it when joining.",
         "To turn it off: `/config autorole quitar:True`.",
     ]))

# ------------------------------------------------------------
# Config · Seguridad
# ------------------------------------------------------------


_cmd("config words", "config_seg", "/config words accion [palabras]", P_ADMIN,
     ("Gestiona el filtro de vocabulario.", "Manages the vocabulary filter."),
     ([
         "Ejecuta `/config words` con `add`, `remove` o `list`.",
         "En `palabras` pon una o varias separadas por coma.",
         "El bot normaliza todo: sin mayúsculas ni acentos, sustituye números/símbolos (4→a, 3→e, 1→i, "
         "0→o, 5→s, 7→t, @→a, $→s) y colapsa letras repetidas. También detecta la palabra con "
         "separadores entre letras.",
         "Solo detecta palabras completas, no fragmentos dentro de otra palabra.",
         "Requiere el AutoMod activado (`/config automod`). `/confess` usa la misma lista.",
     ], [
         "Run `/config words` with `add`, `remove` or `list`.",
         "In `palabras` put one or more, comma-separated.",
         "The bot normalizes everything: no uppercase or accents, swaps digits/symbols (4→a, 3→e, 1→i, "
         "0→o, 5→s, 7→t, @→a, $→s) and collapses repeated letters. It also catches the word with "
         "separators between letters.",
         "It only matches whole words, not fragments inside another word.",
         "Requires AutoMod to be on (`/config automod`). `/confess` uses the same list.",
     ]))





_cmd("config newaccounts", "config_seg", "/config newaccounts [activar] [dias]", P_ADMIN,
     ("Alerta de cuentas nuevas.", "New account alert."),
     ([
         "Ejecuta `/config newaccounts` con `activar` y/o `dias` (1 a 90, por defecto 7).",
         "Cuando entra alguien cuya cuenta tiene menos de esos días, el bot lo anota en el canal de logs "
         "con su antigüedad.",
         "Es solo un aviso: no bloquea ni sanciona a nadie.",
     ], [
         "Run `/config newaccounts` with `activar` and/or `dias` (1 to 90, default 7).",
         "When someone joins whose account is younger than that, the bot notes it in the log channel with "
         "its age.",
         "It's only a notice: it doesn't block or penalize anyone.",
     ]))

_cmd("config warns", "config_seg", "/config warns [umbral] [accion] [minutos]", P_ADMIN,
     ("Sanción automática por acumulación de warns.", "Automatic penalty for accumulated warns."),
     ([
         "Ejecuta `/config warns` con lo que quieras cambiar.",
         "`umbral` (1 a 20, por defecto 3): cuántos warns disparan la sanción.",
         "`accion`: `mute`, `kick` o `ninguna`. `minutos` (1 a 40320, por defecto 60) es la duración del mute.",
         "Al sancionar, el contador de esa persona vuelve a cero.",
     ], [
         "Run `/config warns` with what you want to change.",
         "`umbral` (1 to 20, default 3): how many warns trigger the penalty.",
         "`accion`: `mute`, `kick` or `ninguna` (none). `minutos` (1 to 40320, default 60) is the mute length.",
         "When it penalizes, that person's counter goes back to zero.",
     ]))

# ------------------------------------------------------------
# Config · Módulos
# ------------------------------------------------------------





_cmd("sugerir", "sugerencias", "/sugerir",
     ("Todos", "Everyone"),
     ("Envía una sugerencia.", "Submit a suggestion."),
     ([
         "Abre un formulario; se publica en el canal configurado.",
     ], [
         "Opens a form; it is posted in the configured channel.",
     ]))






_cmd("config giveaway", "config_mod", "/config giveaway [canal] [plataforma] [desactivar]", P_ADMIN,
     ("Configura el tablero de juegos gratis (se actualiza cada 15 min).",
      "Configures the free games board (updates every 15 min)."),
     ([
         "Ejecuta `/config giveaway` con `canal` y, si quieres, `plataforma`.",
         "El bot publica un mensaje con hasta 8 juegos gratis de GamerPower y lo edita cada 15 minutos.",
         "Si cambias de canal, publica un mensaje nuevo ahí.",
         "`desactivar:True` deja de actualizar el tablero; el mensaje que ya estaba publicado no se borra.",
     ], [
         "Run `/config giveaway` with `canal` and, optionally, `plataforma`.",
         "The bot posts one message with up to 8 free games from GamerPower and edits it every 15 minutes.",
         "If you change the channel, it posts a new message there.",
         "`desactivar:True` stops updating the board; the message already posted is not deleted.",
     ]))

_cmd("config confess", "config_mod", "/config confess [canal] [activar]", P_ADMIN,
     ("Activa las confesiones anónimas y elige su canal.", "Turns on anonymous confessions and picks their channel."),
     ([
         "Ejecuta `/config confess` con `canal`; elegir el canal también las activa.",
         "El bot comprueba que pueda ver, escribir y mandar embeds ahí.",
         "Los miembros las envían con `/confess`, que solo funciona en ese canal.",
         "`activar:False` las apaga sin perder el canal ni el contador.",
     ], [
         "Run `/config confess` with `canal`; picking the channel also turns it on.",
         "The bot checks it can view, write and send embeds there.",
         "Members send them with `/confess`, which only works in that channel.",
         "`activar:False` turns them off without losing the channel or the counter.",
     ]))


def _validar():
    """Falla al cargar si falta un idioma o una categoría, en vez de romperse en pleno uso."""
    for clave, c in COMANDOS.items():
        if c["cat"] not in CATEGORIAS:
            raise ValueError(f"{clave}: categoría desconocida {c['cat']!r}")
        for campo in ("perm", "desc", "pasos"):
            for lg in IDIOMAS:
                if not c[campo].get(lg):
                    raise ValueError(f"{clave}: falta {campo}[{lg}]")
        if c["nota"] and not all(c["nota"].get(lg) for lg in IDIOMAS):
            raise ValueError(f"{clave}: nota incompleta")
    for lg in IDIOMAS:
        if set(TEXTOS[lg]) != set(TEXTOS["es"]):
            raise ValueError(f"TEXTOS[{lg}] no tiene las mismas claves que TEXTOS['es']")


_validar()


def _t(lang: str, clave: str) -> str:
    return TEXTOS[lang][clave]


def _de_categoria(cat: str) -> list[str]:
    return [k for k, c in COMANDOS.items() if c["cat"] == cat]


def _embed_inicio(lang: str) -> discord.Embed:
    e = discord.Embed(title=_t(lang, "titulo"), description=_t(lang, "inicio"), color=discord.Color.blurple())
    for cat, datos in CATEGORIAS.items():
        lista = " ".join(f"`/{k}`" for k in _de_categoria(cat))
        e.add_field(name=f"{datos['icono']} {datos[lang]}", value=lista[:1024], inline=False)
    return e


def _embed_categoria(lang: str, cat: str) -> discord.Embed:
    datos = CATEGORIAS[cat]
    lineas = [f"`/{k}` — {COMANDOS[k]['desc'][lang]}" for k in _de_categoria(cat)]
    e = discord.Embed(title=f"{datos['icono']} {datos[lang]}", description="\n".join(lineas),
                      color=discord.Color.blurple())
    e.set_footer(text=_t(lang, "pie_cat"))
    return e


def _embed_comando(lang: str, clave: str) -> discord.Embed:
    c = COMANDOS[clave]
    pasos = "\n".join(f"**{i}.** {p}" for i, p in enumerate(c["pasos"][lang], 1))
    texto = (f"{c['desc'][lang]}\n\n"
             f"**{_t(lang, 'uso')}:** `{c['uso']}`\n"
             f"**{_t(lang, 'permiso')}:** {c['perm'][lang]}\n\n"
             f"**{_t(lang, 'pasos')}**\n{pasos}")
    if c["nota"]:
        texto += f"\n\n**{_t(lang, 'nota')}:** {c['nota'][lang]}"
    e = discord.Embed(title=f"/{clave}", description=texto, color=discord.Color.blurple())
    e.set_footer(text=_t(lang, "opcional"))
    return e


def resolver(texto: str):
    """Devuelve ("inicio", None), ("cat", cat), ("cmd", clave) o ("no", (texto, parecidos))."""
    t = " ".join(texto.lower().replace("/", " ").split())
    if not t:
        return "inicio", None
    if t in COMANDOS:
        return "cmd", t
    if t == "config":
        return "cat", "config_gen"
    if f"config {t}" in COMANDOS:
        return "cmd", f"config {t}"
    cand = [k for k in COMANDOS if k.startswith(t)] or [k for k in COMANDOS if t in k]
    if len(cand) == 1:
        return "cmd", cand[0]
    return "no", (t, cand[:5])


class SelectCategoria(discord.ui.Select):
    def __init__(self, lang: str, actual: str | None):
        opciones = [
            discord.SelectOption(
                label=f"{d['icono']} {d[lang]}"[:100], value=cat,
                description=_t(lang, "n_cmds").format(n=len(_de_categoria(cat))),
                default=(cat == actual))
            for cat, d in CATEGORIAS.items()
        ]
        super().__init__(placeholder=_t(lang, "elige_cat"), options=opciones, row=0)

    async def callback(self, interaction: discord.Interaction):
        await self.view.ir(interaction, cat=self.values[0])


class SelectComando(discord.ui.Select):
    def __init__(self, lang: str, cat: str, actual: str | None):
        opciones = [
            discord.SelectOption(label=f"/{k}"[:100], value=k,
                                 description=COMANDOS[k]["desc"][lang][:100], default=(k == actual))
            for k in _de_categoria(cat)
        ]
        super().__init__(placeholder=_t(lang, "elige_cmd"), options=opciones, row=1)

    async def callback(self, interaction: discord.Interaction):
        await self.view.ir(interaction, cat=COMANDOS[self.values[0]]["cat"], cmd=self.values[0])


class BotonInicio(discord.ui.Button):
    def __init__(self, lang: str):
        super().__init__(label=_t(lang, "inicio_btn"), style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction):
        await self.view.ir(interaction)


class AyudaView(discord.ui.View):
    def __init__(self, origen: discord.Interaction, autor_id: int, lang: str,
                 cat: str | None = None, cmd: str | None = None):
        super().__init__(timeout=180)
        self.origen = origen
        self.autor_id = autor_id
        self.lang = lang
        self.add_item(SelectCategoria(lang, cat))
        if cat:
            self.add_item(SelectComando(lang, cat, cmd))
            self.add_item(BotonInicio(lang))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message(_t(self.lang, "solo_autor"), ephemeral=True)
            return False
        return True

    async def ir(self, interaction: discord.Interaction, cat: str | None = None, cmd: str | None = None):
        if cmd:
            embed = _embed_comando(self.lang, cmd)
        elif cat:
            embed = _embed_categoria(self.lang, cat)
        else:
            embed = _embed_inicio(self.lang)
        nueva = AyudaView(self.origen, self.autor_id, self.lang, cat, cmd)
        self.stop()
        await interaction.response.edit_message(embed=embed, view=nueva)

    async def on_timeout(self):
        try:
            await self.origen.edit_original_response(view=None)
        except discord.HTTPException as e:
            print(f"[ayuda] No pude quitar los menús al expirar: {e}")


class Ayuda(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _idioma(self, guild_id: int | None) -> str:
        fn = getattr(self.bot, "idioma_de", None)
        if fn is None:
            return "es"
        try:
            lang = fn(guild_id)
        except Exception as e:
            print(f"[ayuda] idioma_de falló, uso español: {e!r}")
            return "es"
        return lang if lang in TEXTOS else "es"

    @app_commands.command(name="help", description="Cómo usar cada comando del bot (solo administradores)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(comando="Comando a consultar (autocompleta)")
    async def ayuda_cmd(self, interaction: discord.Interaction,
                        comando: app_commands.Range[str, 1, 60] | None = None):
        lang = self._idioma(interaction.guild_id)
        tipo, valor = resolver(comando) if comando else ("inicio", None)

        if tipo == "no":
            texto, cercanos = valor
            msg = _t(lang, "no_existe").format(c=texto)
            if cercanos:
                msg += " " + _t(lang, "parecidos").format(s=", ".join(f"`/{k}`" for k in cercanos))
            msg += " " + _t(lang, "usa_help")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if tipo == "cmd":
            cat, cmd = COMANDOS[valor]["cat"], valor
            embed = _embed_comando(lang, valor)
        elif tipo == "cat":
            cat, cmd = valor, None
            embed = _embed_categoria(lang, valor)
        else:
            cat = cmd = None
            embed = _embed_inicio(lang)

        view = AyudaView(interaction, interaction.user.id, lang, cat, cmd)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ayuda_cmd.autocomplete("comando")
    async def _auto_comando(self, interaction: discord.Interaction, current: str):
        q = " ".join(current.lower().replace("/", " ").split())
        return [app_commands.Choice(name=f"/{k}", value=k) for k in COMANDOS if q in k][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Ayuda(bot))
