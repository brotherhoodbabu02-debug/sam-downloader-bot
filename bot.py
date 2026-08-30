import os
import asyncio
import tempfile
import shutil
from urllib.parse import urlparse

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

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.environ["BOT_TOKEN"]

PORT = int(os.environ.get("PORT", "10000"))

PUBLIC_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    ""
).rstrip("/")

# Maximum download size: 2 GB
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024

# Websites that are NOT allowed
BLOCKED_DOMAINS = {
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "pinterest.com",
}


# =========================================================
# WEB APP
# =========================================================

web_app = Quart(__name__)


# =========================================================
# TELEGRAM APPLICATION
# =========================================================

telegram_app = (
    Application.builder()
    .token(TOKEN)
    .updater(None)
    .build()
)


# =========================================================
# DOMAIN CHECK
# =========================================================

def get_domain(url):
    try:
        hostname = urlparse(url).hostname

        if not hostname:
            return ""

        hostname = hostname.lower()

        if hostname.startswith("www."):
            hostname = hostname[4:]

        return hostname

    except Exception:
        return ""


def is_blocked_domain(url):

    domain = get_domain(url)

    if not domain:
        return False

    for blocked in BLOCKED_DOMAINS:

        if domain == blocked:
            return True

        if domain.endswith("." + blocked):
            return True

    return False


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Welcome to Sam Downloader Bot!\n\n"
        "🔗 Send a public video URL.\n\n"
        "✅ Supported:\n"
        "• Public website videos\n"
        "• Other yt-dlp supported websites\n\n"
        "🚫 Not supported:\n"
        "• YouTube\n"
        "• Instagram\n"
        "• Pinterest\n\n"
        "⚠️ Download only content you are "
        "allowed to download."
    )


# =========================================================
# DOWNLOAD
# =========================================================

async def download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    # -----------------------------------------------------
    # URL CHECK
    # -----------------------------------------------------

    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):

        await update.message.reply_text(
            "❌ Please send a valid website URL."
        )

        return

    # -----------------------------------------------------
    # BLOCKED WEBSITE CHECK
    # -----------------------------------------------------

    if is_blocked_domain(url):

        await update.message.reply_text(
            "🚫 This website is not supported.\n\n"
            "YouTube, Instagram and Pinterest "
            "downloads are disabled."
        )

        return

    # -----------------------------------------------------
    # PROCESSING MESSAGE
    # -----------------------------------------------------

    msg = await update.message.reply_text(
        "⏳ Processing your link..."
    )

    # Temporary folder

    folder = tempfile.mkdtemp()

    try:

        # -------------------------------------------------
        # OUTPUT
        # -------------------------------------------------

        output_template = os.path.join(
            folder,
            "video.%(ext)s"
        )

        # -------------------------------------------------
        # YT-DLP OPTIONS
        # -------------------------------------------------

        ydl_options = {

            # Best available single file.
            # Avoids requiring ffmpeg for merging.
            "format": "best",

            "outtmpl": output_template,

            "noplaylist": True,

            "quiet": False,

            "no_warnings": False,

            # Network retries
            "retries": 5,

            "fragment_retries": 5,

            "file_access_retries": 3,

            # Do not download extra files
            "writesubtitles": False,

            "writeautomaticsub": False,

            "writethumbnail": False,

            # Continue partial downloads
            "continuedl": True,

            # Do not overwrite existing file
            "overwrites": False,

        }

        # -------------------------------------------------
        # DOWNLOAD FUNCTION
        # -------------------------------------------------

        def perform_download():

            with yt_dlp.YoutubeDL(
                ydl_options
            ) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True
                )

                return ydl.prepare_filename(info)

        # Run downloader in background thread

        file_path = await asyncio.to_thread(
            perform_download
        )

        # -------------------------------------------------
        # FIND DOWNLOADED FILE
        # -------------------------------------------------

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

        # -------------------------------------------------
        # FILE SIZE
        # -------------------------------------------------

        file_size = os.path.getsize(
            file_path
        )

        # 2 GB limit

        if file_size > MAX_FILE_SIZE:

            await msg.edit_text(
                "❌ File is larger than 2 GB.\n\n"
                "Please try a smaller video."
            )

            return

        # -------------------------------------------------
        # UPLOAD
        # -------------------------------------------------

        await msg.edit_text(
            "📤 Download completed!\n"
            "⏳ Sending file to Telegram..."
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

        # Delete processing message

        try:

            await msg.delete()

        except Exception:

            pass

    # =====================================================
    # ERRORS
    # =====================================================

    except yt_dlp.utils.DownloadError as error:

        print("\n==============================")
        print("YT-DLP DOWNLOAD ERROR:")
        print(repr(error))
        print("==============================\n")

        try:

            await msg.edit_text(
                "❌ Download failed.\n\n"
                "Possible reasons:\n"
                "• Website is not supported\n"
                "• Video is private/unavailable\n"
                "• Download is not permitted\n"
                "• Website requires login\n"
                "• Temporary network problem\n"
                "• Video is too large\n\n"
                "Please try another public website URL."
            )

        except Exception:

            pass

    except Exception as error:

        print("\n==============================")
        print("DOWNLOAD ERROR:")
        print(repr(error))
        print("==============================\n")

        try:

            await msg.edit_text(
                "❌ Download failed.\n\n"
                "Please try another public video URL."
            )

        except Exception:

            pass

    finally:

        # Remove temporary files

        shutil.rmtree(
            folder,
            ignore_errors=True
        )


# =========================================================
# HOME
# =========================================================

@web_app.get("/")
async def home():

    return "🤖 Sam Downloader Bot is running!"


# =========================================================
# HEALTH CHECK
# =========================================================

@web_app.get("/health")
async def health():

    return "OK"


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

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


# =========================================================
# HANDLERS
# =========================================================

telegram_app.add_handler(
    CommandHandler(
        "start",
        start
    )
)

telegram_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        download
    )
)


# =========================================================
# MAIN
# =========================================================

async def main():

    print(
        "🤖 Starting Sam Downloader Bot..."
    )

    # Initialize Telegram

    await telegram_app.initialize()

    # Start application

    await telegram_app.start()

    # -----------------------------------------------------
    # WEBHOOK
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # WEB SERVER
    # -----------------------------------------------------

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


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
