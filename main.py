import os
import asyncio
import shutil
import uuid
import zipfile
import random
import PyPDF2
import edge_tts
from flask import Flask
from threading import Thread
from telegram import Update, BotCommand
from telegram.ext import (
    Application, ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, filters
)
from moviepy.editor import AudioFileClip, CompositeAudioClip

# CONFIG
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "5567036606"))
STORIES_FOLDER = "stories"
UPLOADS_FOLDER = "uploads"
SUCCESS_FOLDER = "success"
TEMP_FOLDER = "temp_audio"
BG_MUSIC_FOLDER = "bg_music"

for f in [STORIES_FOLDER, UPLOADS_FOLDER, SUCCESS_FOLDER, TEMP_FOLDER]:
    os.makedirs(f, exist_ok=True)

# FLASK HEALTH CHECK
app = Flask(__name__)
@app.route('/')
def index():
    return "Audio-King is alive!", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

# UTILITIES
def process_pdf(file_path, story_name):
    folder = os.path.join(STORIES_FOLDER, story_name)
    os.makedirs(folder, exist_ok=True)
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
    file_name = f"{story_name}_1.txt"
    path = os.path.join(folder, file_name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return [file_name]

async def safe_tts(text, out_file):
    try:
        communicate = edge_tts.Communicate(text, voice="hi-IN-MadhurNeural", rate="+20%")
        await communicate.save(out_file)
        return True
    except Exception as e:
        print("TTS Error:", e)
        return False

def merge_audio(tts_path, bg_path, out_path):
    try:
        voice = AudioFileClip(tts_path)
        bg = AudioFileClip(bg_path).subclip(0, voice.duration).volumex(0.2)
        CompositeAudioClip([bg, voice]).write_audiofile(out_path, codec='libmp3lame')
        return True
    except Exception as e:
        print("Merge Error:", e)
        return False

# TELEGRAM HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Welcome to Audio-King!\nSend a PDF/TXT/ZIP to convert.")

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Only owner can upload files.")

    document = update.message.document
    if not document:
        return await update.message.reply_text("⚠️ No file sent.")

    file = await context.bot.get_file(document.file_id)
    ext = os.path.splitext(document.file_name)[-1].lower()
    temp_path = os.path.join(UPLOADS_FOLDER, f"{uuid.uuid4().hex}{ext}")
    await file.download_to_drive(temp_path)

    context.user_data["pending_file"] = temp_path
    await update.message.reply_text("✅ File received. Now send story name.")

async def handle_story_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if "pending_file" not in context.user_data:
        return await update.message.reply_text("⚠️ Upload a file first.")

    file_path = context.user_data.pop("pending_file")
    name = update.message.text.strip()
    ext = os.path.splitext(file_path)[-1].lower()

    if ext == ".pdf":
        result = process_pdf(file_path, name)
    elif ext == ".txt":
        os.makedirs(os.path.join(STORIES_FOLDER, name), exist_ok=True)
        dst = os.path.join(STORIES_FOLDER, name, f"{name}_1.txt")
        shutil.copy(file_path, dst)
        result = [dst]
    else:
        return await update.message.reply_text("❌ Only PDF and TXT supported now.")

    shutil.move(file_path, os.path.join(SUCCESS_FOLDER, os.path.basename(file_path)))
    await update.message.reply_text(f"🎉 '{name}' saved with {len(result)} chapter(s).")

# MAIN APP
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("upload_file", upload_file))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_file))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=OWNER_ID), handle_story_name))

    await app.bot.set_my_commands([
        BotCommand("start", "Start bot"),
        BotCommand("upload_file", "Upload story file")
    ])

    print("🤖 Bot Running...")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    # Run Flask in background
    Thread(target=run_flask, daemon=True).start()

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot Stopped.")
