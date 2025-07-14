import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

BOT_TOKEN = "7592009800:AAE9OMzv9cHG7bl-lPAh_Nb8iGJL1rT6XE0"  # 🔁 अपना बॉट टोकन यहां डालो

# 📍 /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 ROY is alive and running on Render!")

# 📍 Other example command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Available commands: /start, /help")

# 🔁 Main async function
async def main():
    # Build the app using ApplicationBuilder
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # Start the bot with polling
    print("✅ ROY bot is starting...")
    await app.run_polling()

# 🚀 Entry point
if __name__ == "__main__":
    asyncio.run(main())
