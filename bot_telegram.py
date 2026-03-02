"""
Bot de Telegram — Recordatorios
================================
Comandos disponibles:
  /start         — Bienvenida
  /ayuda         — Lista de comandos
  /recordar      — Programar un recordatorio
  /lista         — Ver recordatorios activos (con tiempo restante)
  /cancelar      — Cancelar con botones interactivos
"""

import logging
import os
import time
import textwrap
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── Cargar variables ocultas ─────────────────────────────
load_dotenv()

# ─── Configuración ────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    raise ValueError("¡Error Crítico! No se encontró el TELEGRAM_TOKEN en el archivo .env")

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─── Utilidades ───────────────────────────────────────────
def _parsear_tiempo(texto: str) -> float | None:
    """
    Convierte texto a segundos. Acepta:
      '10s'  → segundos
      '5m'   → minutos
      '2h'   → horas
      '1.5h' → horas decimales
      '18:30'→ hora absoluta del día (HH:MM)
      '30'   → número solo = minutos
    Devuelve None si el formato es inválido.
    """
    texto = texto.strip().lower()
    try:
        # ── Hora absoluta HH:MM ──────────────────────────
        if ":" in texto:
            partes = texto.split(":")
            if len(partes) == 2:
                hora = int(partes[0])
                minuto = int(partes[1])
                if not (0 <= hora <= 23 and 0 <= minuto <= 59):
                    return None
                ahora = datetime.now()
                objetivo = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
                diff = (objetivo - ahora).total_seconds()
                # Si ya pasó la hora hoy, programar para mañana
                if diff <= 0:
                    diff += 86400
                return diff
            return None

        # ── Tiempos relativos ────────────────────────────
        if texto.endswith("s"):
            return float(texto.removesuffix("s"))
        elif texto.endswith("m"):
            return float(texto.removesuffix("m")) * 60
        elif texto.endswith("h"):
            return float(texto.removesuffix("h")) * 3600
        else:
            return float(texto) * 60
    except ValueError:
        return None


def _formato_tiempo(segundos: float) -> str:
    """Convierte segundos a texto legible: '2h 30m', '45m', '30s'."""
    s = int(segundos)
    if s >= 3600:
        h, rem = divmod(s, 3600)
        m = rem // 60
        return f"{h}h {m}m" if m else f"{h}h"
    elif s >= 60:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s" if sec else f"{m}m"
    else:
        return f"{s}s"


def _tiempo_restante(job) -> str:
    """Calcula el tiempo restante de un job en texto legible."""
    try:
        # next_t es un datetime con timezone
        next_t = job.next_t
        if next_t is None:
            return "pronto"
        restante = next_t.timestamp() - time.time()
        if restante <= 0:
            return "en instantes"
        return _formato_tiempo(restante)
    except Exception:
        return "pronto"


# ─── Comandos ─────────────────────────────────────────────
AYUDA = """
🤖 *Asistente de Recordatorios* — Comandos

⏱ */recordar* `<tiempo> <mensaje>`
   Programa un recordatorio.
   `<tiempo>` puede ser:
   • `10s`   → en 10 segundos
   • `5m`    → en 5 minutos
   • `2h`    → en 2 horas
   • `1.5h`  → en 1 hora y 30 minutos
   • `18:30` → a las 18:30 de hoy (o mañana si ya pasó)
   • `30`    → número solo = minutos

   *Ejemplos:*
   `/recordar 10m Tomar agua`
   `/recordar 2h Llamar al médico`
   `/recordar 18:30 Tomar la medicina`

📋 */lista* — Ver recordatorios activos con tiempo restante
❌ */cancelar* — Cancelar uno con botones interactivos
❓ */ayuda* — Mostrar este mensaje
""".strip()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name or "amigo"
    texto = (
        f"👋 ¡Hola, *{nombre}*!\n\n"
        "Soy tu bot de recordatorios. Puedo avisarte sobre cualquier "
        "cosa que necesites recordar.\n\n"
        + AYUDA
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(AYUDA, parse_mode="Markdown")


async def cmd_recordar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ejemplo: /recordar 10m Apagar el horno  o  /recordar 18:30 Tomar medicina"""
    args = context.args

    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ *Formato incorrecto.*\n\n"
            "Necesito el tiempo y el mensaje:\n"
            "`/recordar <tiempo> <mensaje>`\n\n"
            "*Ejemplos válidos:*\n"
            "• `/recordar 10m Tomar agua`\n"
            "• `/recordar 2h Llamar al médico`\n"
            "• `/recordar 18:30 Tomar la medicina`",
            parse_mode="Markdown",
        )
        return

    texto_tiempo = args[0]
    segundos = _parsear_tiempo(texto_tiempo)

    if segundos is None or segundos <= 0:
        # Mensaje de error inteligente según qué escribió el usuario
        if ":" in texto_tiempo:
            sugerencia = (
                f"⚠️ La hora `{texto_tiempo}` no es válida.\n\n"
                "Usa el formato `HH:MM` (24 horas), por ejemplo:\n"
                "• `/recordar 18:30 Tomar medicina`\n"
                "• `/recordar 07:00 Desayuno`"
            )
        else:
            sugerencia = (
                f"⚠️ No entendí el tiempo `{texto_tiempo}`.\n\n"
                "Prueba con:\n"
                "• `/recordar 30m Tomar agua` *(minutos)*\n"
                "• `/recordar 2h Llamar al médico` *(horas)*\n"
                "• `/recordar 18:30 Tomar medicina` *(hora exacta)*\n"
                "• `/recordar 45 Revisar el horno` *(número solo = minutos)*"
            )
        await update.message.reply_text(sugerencia, parse_mode="Markdown")
        return

    mensaje = " ".join(args[1:]).strip()
    nombre_job = f"{update.effective_chat.id}_{textwrap.shorten(mensaje, width=20, placeholder='')}"

    context.job_queue.run_once(
        _disparar_recordatorio,
        when=segundos,
        chat_id=update.effective_chat.id,
        name=nombre_job,
        data={"mensaje": mensaje, "segundos_originales": segundos},
    )

    assert segundos is not None  # ya validado arriba
    # Si es hora absoluta, mostrar la hora destino además del tiempo restante
    if ":" in texto_tiempo:
        hora_fmt = texto_tiempo.upper()
        confirmacion = (
            f"✅ *Recordatorio programado*\n\n"
            f"📝 {mensaje}\n"
            f"🕐 A las *{hora_fmt}* _(faltan {_formato_tiempo(segundos)})_"
        )
    else:
        confirmacion = (
            f"✅ *Recordatorio programado*\n\n"
            f"📝 {mensaje}\n"
            f"⏱ En *{_formato_tiempo(segundos)}*"
        )

    await update.message.reply_text(confirmacion, parse_mode="Markdown")


async def cmd_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los recordatorios activos con tiempo restante."""
    chat_id = str(update.effective_chat.id)
    jobs = [
        j for j in context.job_queue.jobs()
        if str(j.chat_id) == chat_id and not j.removed
    ]

    if not jobs:
        await update.message.reply_text(
            "📭 No tienes recordatorios activos.\n\n"
            "Crea uno con `/recordar <tiempo> <mensaje>`",
            parse_mode="Markdown",
        )
        return

    lineas = ["📋 *Recordatorios activos:*\n"]
    for i, job in enumerate(jobs, 1):
        data = job.data or {}
        msg = data.get("mensaje", "—")
        restante = _tiempo_restante(job)
        lineas.append(f"{i}. 📝 _{msg}_  ⏳ faltan *{restante}*")

    lineas.append("\nUsa /cancelar para eliminar uno.")
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")


async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra botones inline para cancelar un recordatorio."""
    chat_id = str(update.effective_chat.id)
    jobs = [
        j for j in context.job_queue.jobs()
        if str(j.chat_id) == chat_id and not j.removed
    ]

    if not jobs:
        await update.message.reply_text(
            "📭 No tienes recordatorios activos para cancelar."
        )
        return

    # Construir botones: uno por recordatorio + botón de salir
    botones = []
    for i, job in enumerate(jobs):
        msg: str = str((job.data or {}).get("mensaje", "—"))
        etiqueta = textwrap.shorten(f"{i + 1}. {msg}", width=38, placeholder="…")
        botones.append([InlineKeyboardButton(etiqueta, callback_data=f"cancelar_{job.name}")])

    botones.append([InlineKeyboardButton("🚫 Ninguno", callback_data="cancelar_ninguno")])
    teclado = InlineKeyboardMarkup(botones)

    await update.message.reply_text(
        "❌ *¿Qué recordatorio deseas cancelar?*",
        parse_mode="Markdown",
        reply_markup=teclado,
    )


async def callback_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa el botón de cancelar seleccionado."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "cancelar_ninguno":
        await query.edit_message_text("✅ No se canceló ningún recordatorio.")
        return

    # Extraer nombre del job desde el callback_data
    nombre_job = data.removeprefix("cancelar_")
    chat_id = str(query.message.chat_id)

    cancelado = False
    for job in context.job_queue.jobs():
        if job.name == nombre_job and str(job.chat_id) == chat_id and not job.removed:
            msg = (job.data or {}).get("mensaje", "—")
            job.schedule_removal()
            await query.edit_message_text(
                f"🗑 Recordatorio cancelado:\n\n_{msg}_",
                parse_mode="Markdown",
            )
            cancelado = True
            break

    if not cancelado:
        await query.edit_message_text(
            "⚠️ No se encontró ese recordatorio (puede que ya haya disparado)."
        )


# ─── Callback del temporizador ────────────────────────────
async def _disparar_recordatorio(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data or {}
    mensaje: str = str(data.get("mensaje", "¡Recordatorio!"))
    segundos_orig: float = float(data.get("segundos_originales") or 0.0)

    # Botón de repetir (solo si el intervalo original era < 24h para que tenga sentido)
    if segundos_orig and segundos_orig < 86400:
        etiqueta_rep = f"🔁 Repetir en {_formato_tiempo(segundos_orig)}"
        teclado = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                etiqueta_rep,
                callback_data=f"repetir_{job.chat_id}_{segundos_orig}_{textwrap.shorten(mensaje, width=40, placeholder='')}"
            )
        ]])
        reply_markup = teclado
    else:
        reply_markup = None

    await context.bot.send_message(
        chat_id=job.chat_id,
        text=(
            f"⏰ *¡RECORDATORIO!*\n\n"
            f"👉 {mensaje}"
        ),
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


async def callback_repetir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reprograma el mismo recordatorio con el mismo intervalo."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    # Formato: repetir_<chat_id>_<segundos>_<mensaje>
    partes = data.removeprefix("repetir_").split("_", 2)
    if len(partes) < 3:
        await query.edit_message_text("⚠️ No se pudo reprogramar el recordatorio.")
        return

    chat_id_str, seg_str, mensaje = partes
    try:
        chat_id = int(chat_id_str)
        segundos = float(seg_str)
    except ValueError:
        await query.edit_message_text("⚠️ Datos de repetición no válidos.")
        return

    nombre_job = f"{chat_id}_{textwrap.shorten(mensaje, width=20, placeholder='')}_rep"

    context.job_queue.run_once(
        _disparar_recordatorio,
        when=segundos,
        chat_id=chat_id,
        name=nombre_job,
        data={"mensaje": mensaje, "segundos_originales": segundos},
    )

    await query.edit_message_text(
        f"⏰ *¡RECORDATORIO!*\n\n"
        f"👉 {mensaje}\n\n"
        f"✅ _Repetido — te avisaré en {_formato_tiempo(segundos)}_",
        parse_mode="Markdown",
    )


# ─── Arranque ─────────────────────────────────────────────
def main():
    logger.info("Construyendo la aplicación del bot…")
    app = ApplicationBuilder().token(TOKEN).build()

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start",    "Bienvenida e instrucciones"),
            BotCommand("recordar", "Programar un recordatorio"),
            BotCommand("lista",    "Ver recordatorios activos"),
            BotCommand("cancelar", "Cancelar un recordatorio"),
            BotCommand("ayuda",    "Ver todos los comandos"),
        ])

    app.post_init = post_init

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("ayuda",    cmd_ayuda))
    app.add_handler(CommandHandler("recordar", cmd_recordar))
    app.add_handler(CommandHandler("lista",    cmd_lista))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))

    # Handlers para botones inline
    app.add_handler(CallbackQueryHandler(callback_cancelar, pattern=r"^cancelar_"))
    app.add_handler(CallbackQueryHandler(callback_repetir,  pattern=r"^repetir_"))

    logger.info("¡Bot en línea! Presiona Ctrl+C para detenerlo.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
