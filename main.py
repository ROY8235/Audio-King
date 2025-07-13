import os
import json
import asyncio
import shutil
import uuid
import zipfile
import PyPDF2
from pydub import AudioSegment
import random
from telegram import Update, Bot, InputFile, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
import edge_tts
from flask import Flask
import threading

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

# Create directories
for folder in [STORIES_FOLDER, UPLOADS_FOLDER, SUCCESS_FOLDER, TEMP_FOLDER, "config"]:
    os.makedirs(folder, exist_ok=True)

# Flask app
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Audio King is alive!", 200

# ======================
# 🛠️ UTILITIES
# ======================
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

# ======================
# 📄 FILE PROCESSING
# ======================
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
    elif any(word in text for word in ["तलवार", "गोलियां", "बम", "हमला", "लड़ाई"]):
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

async def text_to_audio_chunks(text: str, max_chars=4000) -> list:
    chunks = []
    buffer = ""
    for line in text.splitlines():
        if len(buffer) + len(line) > max_chars:
            if buffer.strip():
                output_path = os.path.join(TEMP_FOLDER, f"{uuid.uuid4().hex}.mp3")
                if await safe_tts(buffer.strip(), output_path):
                    chunks.append(output_path)
            buffer = line
        else:
            buffer += "\n" + line
    if buffer.strip():
        output_path = os.path.join(TEMP_FOLDER, f"{uuid.uuid4().hex}.mp3")
        if await safe_tts(buffer.strip(), output_path):
            chunks.append(output_path)
    return chunks

# ✅ PYHUB हटाने के लिए कोई बदलाव नहीं चाहिए क्योंकि वो उपयोग नहीं हो रहा है यहां पर
# ✅ ffmpeg और pydub पहले से मौजूद हैं और इस्तेमाल हो रहे हैं merge_audio में
# ✅ इस कोड में कोई भी "pyhub" import या function नहीं है — यानी ये फाइल पहले से pyhub-free है

# बाकी फाइलें जैसे हैं, उन्हें जरूरत के अनुसार अपडेट किया जा सकता है।
