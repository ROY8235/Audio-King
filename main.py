# main.py
import os
import asyncio
import shutil
import uuid
from flask import Flask
from threading import Thread

from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ---------- CONFIG ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "5567036606"))

UPLOAD_FOLDER = "uploads"
STORY_FOLDER = "stories"
SUCCESS_FOLDER = "success"

# Create folders
for f in [UPLOAD_FOLDER, STORY_FOLDER, SUCCESS_FOLDER]:
    os.makedirs(f, exist_ok=True)

# ---------- FLASK ----------
app = Flask(__name__)
@app.route("/")
def index():
    return "✅ Audio-King is Alive", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

# ---------- TELEGRAM HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Welcome to Audio-King!\nSend PDF/TXT/ZIP to convert.")

async def upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Access denied.")

    document = update.message.document
    if not document:
        return await update.message.reply_text("⚠️ No file found.")

    file = await context.bot.get_file(document.file_id)
    ext = os.path.splitext(document.file_name)[-1]
    temp_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}{ext}")
    await file.download_to_drive(temp_path)

    context.user_data["pending_file"] = temp_path
    await update.message.reply_text("✅ File uploaded. Now send the story name.")

async def handle_story_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if "pending_file" not in context.user_data:
        return await update.message.reply_text("⚠️ No pending file. Upload first.")

    file_path = context.user_data.pop("pending_file")
    story_name = update.message.text.strip()
    story_path = os.path.join(STORY_FOLDER, story_name)
    os.makedirs(story_path, exist_ok=True)

    shutil.move(file_path, os.path.join(story_path, os.path.basename(file_path)))
    await update.message.reply_text(f"🎉 Story '{story_name}' saved successfully.")

# ---------- MAIN ----------
async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL, upload_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=OWNER_ID), handle_story_name))

    await application.bot.set_my_commands([
        BotCommand("start", "Start bot"),
    ])

    print("🤖 Bot started.")
    await application.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    
    Thread(target=run_flask, daemon=True).start()

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot stopped.")
