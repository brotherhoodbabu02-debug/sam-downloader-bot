import os
import asyncio
import tempfile
import shutil

import yt_dlp
from quart import Quart, request
from hypercorn.asyncio import serve
from hypercorn.config import Config

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# SETTINGS
# =========================

TOKEN = os.environ["BOT_TOKEN"]

PORT = int(os.environ.get("PORT", "10000"))

PUBLIC_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    ""
).rstrip("/")

# =========================
# WEB APP
# =========================

web_app = Quart(__name__)

# =========================
# TELEGRAM APPLICATION
# =========================

telegram_app = (
    Application.builder()
    .token(TOKEN)
    .updater(None)
    .build()
)

# =========================
# /start
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "👋 Welcome to Sam Downloader Bot!\n\n"
        "🔗 Send a public/permitted video URL.\n\n"
        "🌐 YouTube\n"
        "📸 Instagram\n"
        "📌 Pinterest\n"
        "🌍 Other yt-dlp supported websites\n\n"
        "⚠️ Only download content you are "
        "allowed to download."
    )

# =========================
# DOWNLOAD
# =========================

async def download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    # Basic URL check
    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        await update.message.reply_text(
            "❌ Please send a valid URL."
        )
        return

    msg = await update.message.reply_text(
        "⏳ Processing your link..."
    )

    folder = tempfile.mkdtemp()

    try:

        output_template = os.path.join(
            folder,
            "video.%(ext)s"
        )

        ydl_options = {
            # More compatible than forcing MP4
            "format": "best",

            "outtmpl": output_template,

            "noplaylist": True,

            "quiet": False,

            "no_warnings": False,

            # Don't download subtitles/thumbnails
            "writesubtitles": False,
            "writethumbnail": False,

            # Retry failed network requests
            "retries": 3,

            "fragment_retries": 3,
        }

        def perform_download():

            with yt_dlp.YoutubeDL(
                ydl_options
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True
                )

                return ydl.prepare_filename(info)

        # Run downloader without blocking
        file_path = await asyncio.to_thread(
            perform_download
        )

        # =========================
        # FIND FILE
        # =========================

        if not os.path.exists(file_path):

            downloaded_files = []

            for filename in os.listdir(folder):

                full_path = os.path.join(
                    folder,
                    filename
                )

                if os.path.isfile(full_path):
                    downloaded_files.append(
                        full_path
                    )

            if not downloaded_files:
                raise FileNotFoundError(
                    "Downloaded file not found."
                )

            file_path = downloaded_files[0]

        # =========================
        # FILE SIZE
        # =========================

        file_size = os.path.getsize(
            file_path
        )

        # Telegram has file-size limits.
        # Don't attempt very large files.
        max_size = 49 * 1024 * 1024

        if file_size > max_size:

            await msg.edit_text(
                "❌ File is too large for this bot "
                "to send through Telegram."
            )

            return

        # =========================
        # UPLOAD
        # =========================

        await msg.edit_text(
            "📤 Uploading..."
        )

        with open(
            file_path,
            "rb"
        ) as video_file:

            await update.message.reply_document(
                document=video_file,
                filename=os.path.basename(
                    file_path
                ),
                caption=(
                    "🎬 Download completed!\n\n"
                    "🤖 Sam Downloader Bot"
                )
            )

        await msg.delete()

    # =========================
    # ERRORS
    # =========================

    except Exception as error:

        print(
            "\n=============================="
        )

        print(
            "DOWNLOAD ERROR:"
        )

        print(
            repr(error)
        )

        print(
            "==============================\n"
        )

        try:

            await msg.edit_text(
                "❌ Download failed.\n\n"
                "Possible reasons:\n"
                "• Website is not supported\n"
                "• Video is unavailable/private\n"
                "• Download is not permitted\n"
                "• Video is too large\n"
                "• Temporary network error\n\n"
                "Please try another public URL."
            )

        except Exception:
            pass

    finally:

        # Delete temporary files
        shutil.rmtree(
            folder,
            ignore_errors=True
        )

# =========================
# HOME
# =========================

@web_app.get("/")
async def home():

    return (
        "🤖 Sam Downloader Bot is running!"
    )

# =========================
# HEALTH CHECK
# =========================

@web_app.get("/health")
async def health():

    return "OK"

# =========================
# TELEGRAM WEBHOOK
# =========================

@web_app.post("/telegram")
async def telegram_webhook():

    data = await request.get_json()

    update = Update.de_json(
        data,
        telegram_app.bot
    )

    await telegram_app.process_update(
        update
    )

    return "OK"

# =========================
# HANDLERS
# =========================

telegram_app.add_handler(
    CommandHandler(
        "start",
        start
    )
)

telegram_app.add_handler(
    MessageHandler(
        filters.TEXT
        & ~filters.COMMAND,
        download
    )
)

# =========================
# MAIN
# =========================

async def main():

    print(
        "🤖 Starting Sam Downloader Bot..."
    )

    # Initialize Telegram
    await telegram_app.initialize()

    # Start application
    await telegram_app.start()

    # Set Telegram webhook
    if PUBLIC_URL:

        webhook_url = (
            f"{PUBLIC_URL}/telegram"
        )

        await telegram_app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES
        )

        print(
            "✅ Webhook set:"
        )

        print(
            webhook_url
        )

    else:

        print(
            "⚠️ RENDER_EXTERNAL_URL not found."
        )

    # Start web server
    config = Config()

    config.bind = [
        f"0.0.0.0:{PORT}"
    ]

    print(
        "🌐 Web server starting..."
    )

    await serve(
        web_app,
        config
    )

# =========================
# RUN
# =========================

if __name__ == "__main__":

    asyncio.run(
        main()
)
