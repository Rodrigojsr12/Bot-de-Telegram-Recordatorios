"""
Bot de Telegram — Recordatorios
================================
Comandos disponibles:
  /start         — Bienvenida
  /ayuda         — Lista de comandos
  /recordar      — Programar un recordatorio
  /lista         — Ver recordatorios activos
  /cancelar      — Cancelar un recordatorio
"""

import logging
import os
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ─── Cargar variables ocultas ─────────────────────────────
# Esto lee el archivo .env y carga las contraseñas en memoria
load_dotenv()

# ─── Configuración ────────────────────────────────────────
# Ahora Python busca el token en el entorno, no en el texto plano
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Medida de seguridad: Si olvidaste crear el .env, el programa te avisa y se detiene
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
    Convierte texto como '10s', '5m', '2h' a segundos.
    Si es un número solo, lo trata como minutos.
    Devuelve None si el formato es inválido.
    """
    texto = texto.strip().lower()
    try:
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

# ─── Comandos ─────────────────────────────────────────────
AYUDA = """
🤖 *Asistente de Recordatorios* — Comandos

⏱ */recordar* `<tiempo> <mensaje>`
   Programa un recordatorio.
   `<tiempo>` puede ser:
   • `10s` → 10 segundos
   • `5m`  → 5 minutos  *(por defecto si no pones unidad)*
   • `2h`  → 2 horas
   • `1.5h` → 1 hora y 30 minutos

   *Ejemplos:*
   `/recordar 10m Tomar agua`
   `/recordar 2h Llamar al médico`
   `/recordar 30 Revisar el horno`

📋 */lista* — Ver recordatorios activos
❌ */cancelar* `<nombre>` — Cancelar un recordatorio por nombre
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
    """Ejemplo: /recordar 10m Apagar el horno"""
    args = context.args  

    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ Formato incorrecto.\n\n"
            "Uso: `/recordar <tiempo> <mensaje>`\n"
            "Ej.: `/recordar 10m Apagar el horno`",
            parse_mode="Markdown",
        )
        return

    segundos = _parsear_tiempo(args[0])
    if segundos is None or segundos <= 0:
        await update.message.reply_text(
            "⚠️ Tiempo no válido. Usa `10s`, `5m`, `2h` o un número (minutos).",
            parse_mode="Markdown",
        )
        return

    mensaje = " ".join(args[1:]).strip()

    # Nombre único del job para poder listarlo/cancelarlo
    nombre_job = f"{update.effective_chat.id}_{mensaje[0:20]}"

    context.job_queue.run_once(
        _disparar_recordatorio,
        when=segundos,
        chat_id=update.effective_chat.id,
        name=nombre_job,
        data={"mensaje": mensaje, "tiempo": segundos},
    )

    assert segundos is not None  
    await update.message.reply_text(
        f"✅ *Recordatorio programado*\n\n"
        f"📝 {mensaje}\n"
        f"⏱ En *{_formato_tiempo(segundos)}*",
        parse_mode="Markdown",
    )

async def cmd_lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los recordatorios activos del chat."""
    chat_id = str(update.effective_chat.id)
    jobs = [
        j for j in context.job_queue.jobs()
        if str(j.chat_id) == chat_id and not j.removed
    ]

    if not jobs:
        await update.message.reply_text("📭 No tienes recordatorios activos.")
        return

    lineas = ["📋 *Recordatorios activos:*\n"]
    for i, job in enumerate(jobs, 1):
        data = job.data or {}
        msg   = data.get("mensaje", "—")
        lineas.append(f"{i}. 📝 _{msg}_")

    lineas.append(f"\nUsa `/cancelar <nombre>` para eliminar uno.")
    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")

async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela recordatorios cuyo mensaje contenga el texto dado."""
    if not context.args:
        await update.message.reply_text(
            "Uso: `/cancelar <parte del mensaje>`",
            parse_mode="Markdown",
        )
        return

    buscar = " ".join(context.args).lower()
    chat_id = str(update.effective_chat.id)

    cancelados = []
    for job in context.job_queue.jobs():
        if str(job.chat_id) == chat_id and not job.removed:
            msg = (job.data or {}).get("mensaje", "")
            if buscar in msg.lower():
                job.schedule_removal()
                cancelados.append(msg)

    if cancelados:
        lista = "\n".join(f"• _{m}_" for m in cancelados)
        await update.message.reply_text(
            f"🗑 Cancelado(s):\n{lista}", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "⚠️ No encontré ningún recordatorio con ese texto."
        )

# ─── Callback del temporizador ────────────────────────────
async def _disparar_recordatorio(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data or {}
    mensaje = data.get("mensaje", "¡Recordatorio!")

    await context.bot.send_message(
        chat_id=job.chat_id,
        text=(
            f"⏰ *¡RECORDATORIO!*\n\n"
            f"👉 {mensaje}"
        ),
        parse_mode="Markdown",
    )

# ─── Arranque ─────────────────────────────────────────────
def main():
    logger.info("Construyendo la aplicación del bot…")
    app = ApplicationBuilder().token(TOKEN).build()

    # Registrar comandos visibles en el menú de Telegram
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

    logger.info("¡Bot en línea! Presiona Ctrl+C para detenerlo.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
