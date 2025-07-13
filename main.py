import os
import json
import asyncio
import shutil
import uuid
import zipfile
import PyPDF2
import random
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
import edge_tts
from flask import Flask
import threading
from audio_king_core import *  # ✅ Your handlers must be defined in this file
from moviepy.editor import AudioFileClip, concatenate_audioclips

# ======================
# 🔧 CONFIGURATION
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN", "7592009800:AAE9OMzv9cHG7bl-lPAh_Nb8iGJL1rT6XE0")
OWNER_ID = int(os.getenv("OWNER_ID", 8169917040))
OWNER_NAME = "Ruders"
BOT_USERNAME = "i_am_raghavbot"
STORIES_FOLDER = "stories"
UPLOADS_FOLDER = "uploads"
SUCCESS_FOLDER = "success"
TEMP_FOLDER = "temp_audio"
BG_MUSIC_FOLDER = "bg_music"
TOPIC_MAP_PATH = "config/stories.json"

for folder in [STORIES_FOLDER, UPLOADS_FOLDER, SUCCESS_FOLDER, TEMP_FOLDER, "config"]:
    os.makedirs(folder, exist_ok=True)

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Audio King is alive!", 200

# Utilities
def ensure_json_file(path, default_data=None):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_data or {}, f)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def extract_number(filename):
    import re
    match = re.search(r'\d+', filename)
    return int(match.group()) if match else 0

def process_zip(file_path, story_name):
    subfolder = os.path.join(STORIES_FOLDER, story_name)
    os.makedirs(subfolder, exist_ok=True)
    with zipfile.ZipFile(file_path, 'r') as zip_ref:
        zip_ref.extractall(subfolder)
    return [f for f in os.listdir(subfolder) if f.endswith('.txt')]

def process_pdf(file_path, story_name):
    subfolder = os.path.join(STORIES_FOLDER, story_name)
    os.makedirs(subfolder, exist_ok=True)
    try:
        with open(file_path, 'rb') as file:
            pdf = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf.pages:
                extracted_text = page.extract_text()
                if extracted_text:
                    text += extracted_text + "\n"
            output_path = os.path.join(subfolder, f"{story_name}_1.txt")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return [f"{story_name}_1.txt"]
    except Exception as e:
        print(f"Error processing PDF: {e}")
        return []

def detect_genre(text):
    text = text.lower()
    if any(word in text for word in ["भूत", "डर", "अंधेरा", "चिल्लाहट", "खून"]):
        return "horror"
    elif any(word in text for word in ["प्यार", "आँखें", "धड़कन", "रिश्ता", "चूड़ी"]):
        return "romantic"
    elif any(word in text for word in ["तलवार", "गोलियां", "बम", "हमला", "लड़ाई"]):
        return "action"
    elif any(word in text for word in ["राज", "भविष्य", "ग्रह", "यात्रा", "वैज्ञानिक"]):
        return "sci-fi"
    return "default"

def get_bg_music_path(genre):
    folder = os.path.join(BG_MUSIC_FOLDER, genre)
    if not os.path.exists(folder):
        return None
    files = [f for f in os.listdir(folder) if f.endswith('.mp3') or f.endswith('.wav')]
    return os.path.join(folder, random.choice(files)) if files else None

async def safe_tts(text, output_path, retries=3):
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(text, voice="hi-IN-MadhurNeural", rate="+40%")
            await communicate.save(output_path)
            return True
        except Exception as e:
            print(f"Error TTS (Attempt {attempt+1}): {e}")
            await asyncio.sleep(2)
    return False

def mix_audio_with_music(voice_path, music_path, output_path):
    try:
        voice_clip = AudioFileClip(voice_path)
        music_clip = AudioFileClip(music_path).volumex(0.2).subclip(0, voice_clip.duration)
        final_audio = voice_clip.audio.set_audio(music_clip)
        final_audio.write_audiofile(output_path)
        voice_clip.close()
        music_clip.close()
    except Exception as e:
        print(f"Audio mix error: {e}")

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    await app.bot.set_my_commands([
        BotCommand("start", "Start the bot and get info"),
        BotCommand("upload_file", "Upload ZIP/PDF/text files (Owner only)")
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("upload_file", upload_file))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, upload_file))
    app.add_handler(CallbackQueryHandler(destination_callback, pattern="dest_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(user_id=OWNER_ID), handle_destination_input))

    app.job_queue.run_repeating(clean_success_folder, interval=300, first=0)
    app.job_queue.run_repeating(monitor_uploads, interval=5, first=0)

    print("🚀 Audio King Bot Started")
    await app.run_polling()

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
