import os
import json
import asyncio
import shutil
import uuid
import zipfile
import PyPDF2
import random
from moviepy.editor import AudioFileClip, CompositeAudioClip
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
import edge_tts
from flask import Flask
import threading

# ========== CONFIGURATION ==========
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", 1234567890))
BOT_USERNAME = "your_bot_username"
OWNER_NAME = "Owner"
STORIES_FOLDER = "stories"
UPLOADS_FOLDER = "uploads"
SUCCESS_FOLDER = "success"
TEMP_FOLDER = "temp_audio"
BG_MUSIC_FOLDER = "bg_music"
TOPIC_MAP_PATH = "config/stories.json"

for folder in [STORIES_FOLDER, UPLOADS_FOLDER, SUCCESS_FOLDER, TEMP_FOLDER, "config"]:
    os.makedirs(folder, exist_ok=True)

# ========== FLASK ==========
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Audio King is alive!", 200

# ========== UTILITY FUNCTIONS ==========
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
            text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
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
    elif any(word in text for word in ["तलवार", "गोलियां", "बम", "हमला", "लड़ाई"]):
        return "action"
    elif any(word in text for word in ["राज", "भविष्य", "ग्रह", "यात्रा", "वैज्ञानिक"]):
        return "sci-fi"
    return "default"

def get_bg_music_path(genre):
    folder = os.path.join(BG_MUSIC_FOLDER, genre)
    if not os.path.exists(folder): return None
    files = [f for f in os.listdir(folder) if f.endswith('.mp3')]
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

def merge_audio(tts_path, bg_music_path, output_path):
    try:
        voice = AudioFileClip(tts_path)
        bg = AudioFileClip(bg_music_path).subclip(0, voice.duration).volumex(0.2)
        mixed = CompositeAudioClip([bg, voice]).set_duration(voice.duration)
        mixed.write_audiofile(output_path, codec='libmp3lame')
        return True
    except Exception as e:
        print(f"Error merging: {e}")
        return False

# ========== TELEGRAM HANDLERS ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\U0001F451 Welcome to Audio King!\nSend PDF, ZIP, or TXT to start.")

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("\u274C Access Denied.")

    doc = update.message.document
    if not doc:
        return await update.message.reply_text("\u26A0\uFE0F No file received.")

    file_id = doc.file_id
    file = await context.bot.get_file(file_id)
    ext = os.path.splitext(doc.file_name)[-1]
    temp_file = os.path.join(UPLOADS_FOLDER, f"{uuid.uuid4().hex}{ext}")
    await file.download_to_drive(temp_file)
    context.user_data["pending_file"] = temp_file
    await update.message.reply_text("\u2705 File uploaded. Now send story name.")

async def handle_destination_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    story_name = update.message.text.strip()
    if "pending_file" not in context.user_data:
        return await update.message.reply_text("\u26A0\uFE0F No file to assign. Upload a file first.")

    file_path = context.user_data["pending_file"]
    ext = os.path.splitext(file_path)[-1].lower()

    if ext == ".zip":
        result = process_zip(file_path, story_name)
    elif ext == ".pdf":
        result = process_pdf(file_path, story_name)
    elif ext == ".txt":
        subfolder = os.path.join(STORIES_FOLDER, story_name)
        os.makedirs(subfolder, exist_ok=True)
        shutil.copy(file_path, os.path.join(subfolder, f"{story_name}_1.txt"))
        result = [f"{story_name}_1.txt"]
    else:
        return await update.message.reply_text("\u274C Unsupported file format.")

    if result:
        await update.message.reply_text(f"\U0001F389 Story '{story_name}' saved with {len(result)} chapter(s)!")
    else:
        await update.message.reply_text("\u274C Failed to process the story.")

    del context.user_data["pending_file"]
    shutil.move(file_path, os.path.join(SUCCESS_FOLDER, os.path.basename(file_path)))

# ========== SCHEDULERS ==========

async def clean_success_folder(context: ContextTypes.DEFAULT_TYPE):
    for file in os.listdir(SUCCESS_FOLDER):
        try:
            os.remove(os.path.join(SUCCESS_FOLDER, file))
        except:
            continue

async def monitor_uploads(context: ContextTypes.DEFAULT_TYPE):
    pass  # Future Feature

# ========== BOT RUNNER ==========

async def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("upload_file", "Upload a story (zip/pdf/txt)")
    ])

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, upload_file))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(user_id=OWNER_ID), handle_destination_input))
    application.job_queue.run_repeating(clean_success_folder, interval=300, first=0)
    application.job_queue.run_repeating(monitor_uploads, interval=10, first=10)

    print("\u2705 Bot is running!")
    await application.run_polling()

# ========== FLASK RUNNER ==========

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
        print("\U0001F6D1 Bot stopped.")
