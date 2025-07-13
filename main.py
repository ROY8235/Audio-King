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
    elif any(word in text for word in ["प्यार", "आँखें", "धड़कन", "रिश्ता", "चूड़ी"]):
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

def merge_audio(chunks: list, output_path: str, genre: str):
    if not chunks:
        return
    merged = AudioSegment.empty()
    for path in chunks:
        try:
            merged += AudioSegment.from_file(path)
        except Exception as e:
            print(f"Error merging audio chunk {path}: {e}")
    bg_path = get_bg_music_path(genre)
    print(f"Genre Detected: {genre} | BG Music: {bg_path}")
    if bg_path:
        try:
            bg_music = AudioSegment.from_file(bg_path) - 15
            bg_loop = bg_music * ((len(merged) // len(bg_music)) + 1)
            merged = merged.overlay(bg_loop)
        except Exception as e:
            print(f"Error while merging bg music: {e}")
    try:
        merged.export(output_path, format="mp3", bitrate="64k")
        print(f"Saved: {output_path} with genre: {genre}")
    except Exception as e:
        print(f"Error exporting audio: {e}")

def clean_temp(chunks: list):
    for path in chunks:
        try:
            os.remove(path)
        except Exception:
            pass

async def process_story_subfolder(story_name, context: ContextTypes.DEFAULT_TYPE, destination: dict):
    story_path = os.path.join(STORIES_FOLDER, story_name)
    txt_files = sorted(
        [f for f in os.listdir(story_path) if f.endswith(".txt")],
        key=extract_number
    )
    for txt_file in txt_files:
        input_path = os.path.join(story_path, txt_file)
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                text = f.read()
            genre = detect_genre(text)
            chunks = await text_to_audio_chunks(text)
            upload_subfolder = os.path.join(UPLOADS_FOLDER, story_name)
            os.makedirs(upload_subfolder, exist_ok=True)
            output_filename = f"{os.path.splitext(txt_file)[0]}.mp3"
            output_path = os.path.join(upload_subfolder, output_filename)
            merge_audio(chunks, output_path, genre)
            clean_temp(chunks)
            success_subfolder = os.path.join(SUCCESS_FOLDER, story_name)
            os.makedirs(success_subfolder, exist_ok=True)
            shutil.move(input_path, os.path.join(success_subfolder, txt_file))
            print(f"Processed {txt_file} of {story_name}")
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"Processed {txt_file} for {story_name}. MP3 created: {output_filename}"
            )
        except Exception as e:
            print(f"Error processing {txt_file}: {e}")
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"Error processing {txt_file} for {story_name}: {str(e)}"
            )
    # Clean up stories folder after all audio is created
    if not os.listdir(story_path):  # Check if no txt files remain
        shutil.rmtree(story_path)
        print(f"Cleaned up stories subfolder: {story_path}")

    # Store destination for this story
    topic_map = ensure_json_file(TOPIC_MAP_PATH)
    topic_map[story_name] = destination
    save_json(TOPIC_MAP_PATH, topic_map)

# ======================
# 💬 BOT COMMANDS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or user.first_name or "User"
    try:
        await update.message.reply_text(
            f"Welcome to Audio King Bot!\n\n"
            f"Hey {username},\n"
            f"I am a bot that creates audio stories. Only the Owner ({OWNER_NAME}) can upload files.\n\n"
            f"Available commands:\n"
            f"/start - Start the bot\n"
            f"/upload_file - Upload ZIP/PDF/text files (Owner only)\n"
            f"Powered by {OWNER_NAME}"
        )
    except Exception as e:
        print(f"Error in start command: {e}")
        await update.message.reply_text(
            "Something went wrong. Please try again."
        )

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Only the Bot Owner can use this command.")
        return
    if not update.message.document:
        await update.message.reply_text("Please upload a ZIP, PDF, or text file.")
        return
    file = update.message.document
    story_name = file.file_name.split('.')[0]  # Use file name as story title
    file_path = os.path.join(TEMP_FOLDER, file.file_name)
    try:
        file_obj = await file.get_file()
        await file_obj.download_to_drive(file_path)
        txt_files = []
        if file.file_name.endswith('.zip'):
            txt_files = process_zip(file_path, story_name)
        elif file.file_name.endswith('.pdf'):
            txt_files = process_pdf(file_path, story_name)
        elif file.file_name.endswith('.txt'):
            subfolder = os.path.join(STORIES_FOLDER, story_name)
            os.makedirs(subfolder, exist_ok=True)
            output_path = os.path.join(subfolder, file.file_name)
            shutil.move(file_path, output_path)
            txt_files = [file.file_name]
        else:
            await update.message.reply_text("Unsupported file type. Please upload ZIP, PDF, or text files.")
            return
        await update.message.reply_text(
            f"Processing {len(txt_files)} text files for {story_name}. Where should I send the audio?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Group", callback_data=f"dest_group_{story_name}")],
                [InlineKeyboardButton("Supergroup", callback_data=f"dest_supergroup_{story_name}")],
                [InlineKeyboardButton("Personal Chat", callback_data=f"dest_personal_{story_name}")]
            ])
        )
        context.user_data['story_name'] = story_name
        context.user_data['txt_files'] = txt_files
    except Exception as e:
        await update.message.reply_text(f"Error processing file: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    story_name = context.user_data.get('story_name')
    txt_files = context.user_data.get('txt_files', [])
    if not story_name or not txt_files:
        await query.message.reply_text("Error: No story or files to process.")
        return
    if data.startswith("dest_group"):
        await query.message.reply_text("Please send the Group ID (e.g., -1001234567890):")
        context.user_data['destination_type'] = "group"
    elif data.startswith("dest_supergroup"):
        await query.message.reply_text("Please send the Supergroup ID and Topic ID (e.g., -1001234567890 12345):")
        context.user_data['destination_type'] = "supergroup"
    elif data.startswith("dest_personal"):
        destination = {"chat_id": OWNER_ID, "type": "personal"}
        await query.message.reply_text(
            f"Audio will be sent to your personal chat. Starting audio creation for {story_name}..."
        )
        asyncio.create_task(process_story_subfolder(story_name, context, destination))
    context.user_data['story_name'] = story_name

async def handle_destination_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Only the Bot Owner can use this command.")
        return
    story_name = context.user_data.get('story_name')
    destination_type = context.user_data.get('destination_type')
    if not story_name or not destination_type:
        await update.message.reply_text("Error: No story or destination type selected.")
        return
    text = update.message.text.strip()
    try:
        if destination_type == "group":
            chat_id = int(text)
            destination = {"chat_id": chat_id, "type": "group"}
            await update.message.reply_text(
                f"Audio will be sent to group {chat_id}. Starting audio creation for {story_name}..."
            )
            asyncio.create_task(process_story_subfolder(story_name, context, destination))
        elif destination_type == "supergroup":
            chat_id, topic_id = map(int, text.split())
            destination = {"chat_id": chat_id, "message_thread_id": topic_id, "type": "supergroup"}
            await update.message.reply_text(
                f"Audio will be sent to supergroup {chat_id} (topic {topic_id}). Starting audio creation for {story_name}..."
            )
            asyncio.create_task(process_story_subfolder(story_name, context, destination))
    except ValueError:
        await update.message.reply_text("Invalid input. Please send the correct ID format.")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def monitor_uploads(context: ContextTypes.DEFAULT_TYPE):
    try:
        topic_map = ensure_json_file(TOPIC_MAP_PATH)
        for story_name in os.listdir(UPLOADS_FOLDER):
            subfolder = os.path.join(UPLOADS_FOLDER, story_name)
            if not os.path.isdir(subfolder):
                continue
            chat_topic = topic_map.get(story_name)
            if not chat_topic:
                continue
            files = [f for f in os.listdir(subfolder) if f.endswith('.mp3')]
            for file in files:
                file_path = os.path.join(subfolder, file)
                try:
                    success = await send_file(story_name, file_path, chat_topic, context)
                    if success:
                        await context.bot.send_message(
                            chat_id=OWNER_ID,
                            text=f"Posted {file} to destination for {story_name}"
                        )
                except Exception as e:
                    print(f"Error in monitor_uploads for {file}: {e}")
                    await context.bot.send_message(
                        chat_id=OWNER_ID,
                        text=f"Error posting {file} for {story_name}: {str(e)}"
                    )
                await asyncio.sleep(0.5)
            # Clean up uploads folder if no mp3 files remain
            if not os.listdir(subfolder):  # Check if no mp3 files remain
                shutil.rmtree(subfolder)
                print(f"Cleaned up uploads subfolder: {subfolder}")
                # Clean up config after uploads are cleared
                if story_name in topic_map:
                    del topic_map[story_name]
                    save_json(TOPIC_MAP_PATH, topic_map)
                    print(f"Cleaned up config entry for {story_name}")
    except Exception as e:
        print(f"Error in monitor_uploads: {e}")

async def send_file(folder, filepath, chat_topic, context):
    chat_id = chat_topic["chat_id"]
    destination_type = chat_topic.get("type", "group")
    message_thread_id = chat_topic.get("message_thread_id")
    filename = os.path.basename(filepath)
    try_count = 0
    while try_count < 3:
        try_count += 1
        try:
            with open(filepath, "rb") as f:
                if destination_type == "supergroup":
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        message_thread_id=message_thread_id,
                        audio=f,
                        title=f"{folder} - {filename}"
                    )
                else:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        title=f"{folder} - {filename}"
                    )
            success_folder = os.path.join(SUCCESS_FOLDER, folder)
            os.makedirs(success_folder, exist_ok=True)
            shutil.move(filepath, os.path.join(success_folder, filename))
            print(f"Posted {filename} to {destination_type} {chat_id}")
            return True
        except Exception as e:
            print(f"Error in send_file: {e}")
            await asyncio.sleep(min(30, 5 * try_count))
    return False

async def clean_success_folder(context: ContextTypes.DEFAULT_TYPE):
    try:
        deleted = 0
        for subdir in os.listdir(SUCCESS_FOLDER):
            sub_path = os.path.join(SUCCESS_FOLDER, subdir)
            if os.path.isdir(sub_path):
                shutil.rmtree(sub_path)
                deleted += 1
        print(f"Success folder cleaned. {deleted} subfolders deleted.")
    except Exception as e:
        print(f"Error cleaning success folder: {e}")

# ======================
# 🧠 MAIN FUNCTION
# ======================
async def main():
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        await app.bot.set_my_commands([
            BotCommand("start", "Start the bot and get info"),
            BotCommand("upload_file", "Upload ZIP/PDF/text files (Owner only)"),
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
    except Exception as e:
        print(f"Error in main: {e}")

# Flask को Replit के साथ रन करें
def run_flask():
      app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
