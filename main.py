import os
import json
import uuid
import asyncio
import shutil
import zipfile
import random
from flask import Flask
from threading import Thread

from telegram import Update, BotCommand, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

import edge_tts
from PyPDF2 import PdfReader
from moviepy.editor import AudioFileClip, concatenate_audioclips

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "5567036606"))

UPLOAD_FOLDER = "uploads"
STORY_FOLDER = "stories"
SUCCESS_FOLDER = "success"
TEMP_FOLDER = "temp_audio"
CONFIG_FILE = "config/stories.json"

for folder in [UPLOAD_FOLDER, STORY_FOLDER, SUCCESS_FOLDER, TEMP_FOLDER, "config"]:
    os.makedirs(folder, exist_ok=True)

# === FLASK ===
app = Flask(__name__)

@app.route("/")
def health():
    return "✅ Audio-King running", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# === UTILITIES ===
def extract_text_from_pdf(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        print(f"PDF extract error: {e}")
        return ""

async def tts_generate(text, path):
    try:
        communicate = edge_tts.Communicate(text, voice="hi-IN-MadhurNeural")
        await communicate.save(path)
        return True
    except Exception as e:
        print(f"TTS error: {e}")
        return False

async def merge_audio(audio_files, output_path):
    try:
        clips = [AudioFileClip(path) for path in audio_files if os.path.exists(path)]
        final = concatenate_audioclips(clips)
        final.write_audiofile(output_path, bitrate="64k")
        for c in clips: c.close()
    except Exception as e:
        print(f"Merge error: {e}")

# === BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Welcome to Audio-King!\nSend PDF/TXT/ZIP to convert.")

async def handle_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Access denied.")

    doc = update.message.document
    ext = os.path.splitext(doc.file_name)[-1]
    file_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}{ext}")
    await doc.get_file().download_to_drive(file_path)

    context.user_data["uploaded_file"] = file_path
    await update.message.reply_text("📄 File received. Send story name.")

async def handle_story_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if "uploaded_file" not in context.user_data:
        return await update.message.reply_text("⚠️ Upload a file first.")

    file_path = context.user_data.pop("uploaded_file")
    story_name = update.message.text.strip()
    folder = os.path.join(STORY_FOLDER, story_name)
    os.makedirs(folder, exist_ok=True)

    # Extract text
    ext = os.path.splitext(file_path)[-1]
    if ext == ".pdf":
        text = extract_text_from_pdf(file_path)
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    elif ext == ".zip":
        with zipfile.ZipFile(file_path) as z:
            z.extractall(folder)
        return await update.message.reply_text("✅ ZIP extracted.")
    else:
        return await update.message.reply_text("❌ Unsupported file type.")

    # Save text
    txt_path = os.path.join(folder, f"{story_name}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    await update.message.reply_text(f"✅ Story '{story_name}' saved. Converting to audio...")

    # Convert to audio
    audio_paths = []
    chunks = [text[i:i+3000] for i in range(0, len(text), 3000)]
    for i, chunk in enumerate(chunks):
        audio_file = os.path.join(TEMP_FOLDER, f"{story_name}_{i}.mp3")
        if await tts_generate(chunk, audio_file):
            audio_paths.append(audio_file)

    final_audio = os.path.join(SUCCESS_FOLDER, f"{story_name}.mp3")
    await merge_audio(audio_paths, final_audio)

    await context.bot.send_audio(
        chat_id=OWNER_ID,
        audio=InputFile(final_audio),
        title=story_name
    )
    await update.message.reply_text("🎧 Audio created successfully!")

# === MAIN ===
async def main():
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()

    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(MessageHandler(filters.Document.ALL, handle_upload))
    app_.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=OWNER_ID), handle_story_name))

    await app_.bot.set_my_commands([
        BotCommand("start", "Start the bot")
    ])

    Thread(target=run_flask, daemon=True).start()
    print("🤖 Bot running...")
    await app_.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Bot stopped.")
