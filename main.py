# main.py
import os
import json
import asyncio
import shutil
import uuid
import zipfile
import random
from flask import Flask
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import edge_tts
from moviepy.editor import concatenate_audioclips, AudioFileClip

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "5567036606"))
OWNER_NAME = "Ruders"

UPLOAD_FOLDER = "uploads"
STORY_FOLDER = "stories"
SUCCESS_FOLDER = "success"
TEMP_FOLDER = "temp_audio"
CONFIG_PATH = "config/stories.json"
BG_MUSIC_FOLDER = "bg_music"

app = Flask(__name__)

@app.route("/")
def health():
    return "✅ Audio-King is Alive", 200

# ================ UTILITIES =================
def ensure_folders():
    for f in [UPLOAD_FOLDER, STORY_FOLDER, SUCCESS_FOLDER, TEMP_FOLDER, os.path.dirname(CONFIG_PATH)]:
        os.makedirs(f, exist_ok=True)

def load_json(path, default={}):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def detect_genre(text):
    text = text.lower()
    if any(x in text for x in ["भूत", "डर", "रात"]): return "horror"
    if any(x in text for x in ["प्यार", "धड़कन", "आँख"]): return "romantic"
    if any(x in text for x in ["गोलियां", "तलवार"]): return "action"
    if any(x in text for x in ["ग्रह", "भविष्य"]): return "sci-fi"
    return "default"

def get_bg_music(genre):
    genre_path = os.path.join(BG_MUSIC_FOLDER, genre)
    if not os.path.exists(genre_path): return None
    files = [f for f in os.listdir(genre_path) if f.endswith(".mp3")]
    return os.path.join(genre_path, random.choice(files)) if files else None

async def safe_tts(text, output_path):
    try:
        communicate = edge_tts.Communicate(text, voice="hi-IN-MadhurNeural", rate="+20%")
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"TTS Error: {e}")
        return False

async def text_to_audio_chunks(text):
    chunks = []
    buffer = ""
    for line in text.splitlines():
        if len(buffer + line) > 4000:
            path = os.path.join(TEMP_FOLDER, f"{uuid.uuid4().hex}.mp3")
            if await safe_tts(buffer.strip(), path): chunks.append(path)
            buffer = line
        else:
            buffer += "\n" + line
    if buffer.strip():
        path = os.path.join(TEMP_FOLDER, f"{uuid.uuid4().hex}.mp3")
        if await safe_tts(buffer.strip(), path): chunks.append(path)
    return chunks

def merge_audio(chunks, output_path, genre):
    try:
        clips = [AudioFileClip(c) for c in chunks if os.path.exists(c)]
        final = concatenate_audioclips(clips)

        bg_path = get_bg_music(genre)
        if bg_path:
            bg_clip = AudioFileClip(bg_path).volumex(0.2)
            bg_loop = bg_clip.loop(duration=final.duration)
            final = final.audio.set_audio(final.audio).fx(lambda _: final.audio.set_audio(bg_loop))

        final.write_audiofile(output_path, bitrate="64k")
        for c in chunks: os.remove(c)
    except Exception as e:
        print(f"Merge error: {e}")

# ================ FILE HANDLERS =================
def process_file(file_path, story_name):
    out_path = os.path.join(STORY_FOLDER, story_name)
    os.makedirs(out_path, exist_ok=True)
    if file_path.endswith(".zip"):
        with zipfile.ZipFile(file_path, 'r') as z:
            z.extractall(out_path)
    elif file_path.endswith(".pdf"):
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
            with open(os.path.join(out_path, f"{story_name}.txt"), 'w', encoding='utf-8') as out:
                out.write(text)
    elif file_path.endswith(".txt"):
        shutil.copy(file_path, os.path.join(out_path, os.path.basename(file_path)))
    return out_path

async def convert_and_post(story_name, context, destination):
    story_path = os.path.join(STORY_FOLDER, story_name)
    files = [f for f in os.listdir(story_path) if f.endswith(".txt")]
    for file in files:
        path = os.path.join(story_path, file)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        genre = detect_genre(text)
        chunks = await text_to_audio_chunks(text)
        upload_dir = os.path.join(UPLOAD_FOLDER, story_name)
        os.makedirs(upload_dir, exist_ok=True)
        output_audio = os.path.join(upload_dir, f"{file}.mp3")
        merge_audio(chunks, output_audio, genre)
        try:
            with open(output_audio, "rb") as audio:
                await context.bot.send_audio(chat_id=destination["chat_id"], audio=audio)
        except Exception as e:
            print(f"Send error: {e}")

# ================ TELEGRAM HANDLERS ================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🎙 Welcome to Audio King!\nOnly Owner ({OWNER_NAME}) can upload files."
    )

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Access denied.")
    doc = update.message.document
    if not doc:
        return await update.message.reply_text("⚠️ No file found.")
    path = os.path.join(TEMP_FOLDER, doc.file_name)
    file = await doc.get_file()
    await file.download_to_drive(path)
    story_name = doc.file_name.split(".")[0]
    process_file(path, story_name)
    await update.message.reply_text(
        f"✅ {doc.file_name} uploaded. Where to send audio?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Send to Owner", callback_data=f"dest_owner_{story_name}")]
        ])
    )

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    story_name = data.split("_")[-1]
    destination = {"chat_id": OWNER_ID, "type": "personal"}
    await query.message.reply_text(f"🎧 Starting audio conversion for: {story_name}")
    await convert_and_post(story_name, context, destination)

# ================ MAIN ================
async def main():
    ensure_folders()
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()
    await app_.bot.set_my_commands([
        BotCommand("start", "Start bot"),
    ])
    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(MessageHandler(filters.Document.ALL & filters.User(user_id=OWNER_ID), upload))
    app_.add_handler(CallbackQueryHandler(callback, pattern="^dest_"))
    print("🚀 Bot running")
    await app_.run_polling()

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    from threading import Thread
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
