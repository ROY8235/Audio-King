import os
import asyncio
from flask import Flask
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Telegram bot token from env
BOT_TOKEN = os.environ.get("BOT_TOKEN")

app = Flask(__name__)

# Example command
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("नमस्ते! मैं Audio-King बॉट हूँ।")

# Example message handler
async def echo(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"आपने कहा: {update.message.text}")

# Telegram Bot Main
async def telegram_main():
    app_ = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app_.add_handler(CommandHandler("start", start))
    app_.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    print("🤖 Bot is running...")
    await app_.run_polling()

# Flask route (optional)
@app.route('/')
def home():
    return "✅ Audio-King bot is deployed and running."

# Async entry point for both Flask & Telegram
async def main():
    tg_task = asyncio.create_task(telegram_main())
    await tg_task

# Run when script is executed
if __name__ == "__main__":
    asyncio.run(main())
