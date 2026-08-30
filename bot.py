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


# Websites that must NOT be downloaded
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
# HELPERS
# =========================================================

def is_blocked_url(url: str) -> bool:
    """
    Returns True if the URL belongs to YouTube,
    Instagram or Pinterest.
    """

    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower().removeprefix("www.")

        for domain in BLOCKED_DOMAINS:
            if hostname == domain:
                return True

            if hostname.endswith("." + domain):
                return True

        return False

    except Exception:
        return False


def is_valid_url(url: str) -> bool:
    """
    Basic HTTP/HTTPS URL validation.
    """

    try:
        parsed = urlparse(url)

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
        )

    except Exception:
        return False


def find_downloaded_file(folder: str):
    """
    Finds the largest downloaded file in the temporary folder.
    """

    files = []

    for filename in os.listdir(folder):
        full_path = os.path.join(folder, filename)

        if os.path.isfile(full_path):
            files.append(full_path)

    if not files:
        return None

    return max(
        files,
        key=os.path.getsize
    )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Welcome to Sam Downloader Bot!\n\n"
        "🔗 Send a public/permitted video URL.\n\n"
        "✅ Most supported websites\n"
        "❌ YouTube\n"
        "❌ Instagram\n"
        "❌ Pinterest\n\n"
        "⚠️ Only download content you are "
        "allowed to download."
    )


# =========================================================
# DOWNLOAD
# =========================================================

async def download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    url = update.message.text.strip()


    # -----------------------------------------------------
    # URL VALIDATION
    # -----------------------------------------------------

    if not is_valid_url(url):

        await update.message.reply_text(
            "❌ Please send a valid website video URL."
        )

        return


    # -----------------------------------------------------
    # BLOCK YOUTUBE / INSTAGRAM / PINTEREST
    # -----------------------------------------------------

    if is_blocked_url(url):

        await update.message.reply_text(
            "❌ This website is not supported.\n\n"
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


    # -----------------------------------------------------
    # TEMPORARY FOLDER
    # -----------------------------------------------------

    folder = tempfile.mkdtemp()


    try:

        output_template = os.path.join(
            folder,
            "video.%(ext)s"
        )


        # -------------------------------------------------
        # YT-DLP OPTIONS
        # -------------------------------------------------

        ydl_options = {

            # Best available single format
            "format": "best",

            "outtmpl": output_template,

            # Do not download playlists
            "noplaylist": True,

            # Logging
            "quiet": False,
            "no_warnings": False,

            # Do not download subtitles
            "writesubtitles": False,

            # Do not download thumbnails
            "writethumbnail": False,

            # Network retries
            "retries": 5,
            "fragment_retries": 5,

            # Continue partial downloads
            "continuedl": True,

            # Do not overwrite existing files
            "overwrites": False,

            # Limit filename problems
            "restrictfilenames": True,
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


        await msg.edit_text(
            "⬇️ Downloading..."
        )


        # Run yt-dlp in another thread
        file_path = await asyncio.to_thread(
            perform_download
        )


        # -------------------------------------------------
        # FIND FILE
        # -------------------------------------------------

        if not os.path.exists(file_path):

            file_path = find_downloaded_file(
                folder
            )


        if not file_path:

            raise FileNotFoundError(
                "Downloaded file not found."
            )


        # -------------------------------------------------
        # FILE SIZE
        # -------------------------------------------------

        file_size = os.path.getsize(
            file_path
        )


        file_size_mb = (
            file_size / (1024 * 1024)
        )


        print(
            f"Downloaded file size: "
            f"{file_size_mb:.2f} MB"
        )


        # -------------------------------------------------
        # 2 GB CHECK
        # -------------------------------------------------

        if file_size > MAX_FILE_SIZE:

            await msg.edit_text(
                "❌ File is larger than 2 GB.\n\n"
                "Please try a smaller video."
            )

            return


        # -------------------------------------------------
        # TELEGRAM UPLOAD
        # -------------------------------------------------

        await msg.edit_text(
            "📤 Preparing upload..."
        )


        # NOTE:
        # Telegram's standard cloud Bot API has its
        # own upload/file-size limits.
        #
        # Therefore a file being <= 2 GB does NOT mean
        # the standard Bot API can necessarily send it.
        #
        # Small files will be sent normally.


        try:

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


        except Exception as upload_error:

            print(
                "UPLOAD ERROR:"
            )

            print(
                repr(upload_error)
            )


            await msg.edit_text(
                "⚠️ Download completed, but "
                "Telegram could not upload/send "
                "this file.\n\n"
                f"📦 File size: "
                f"{file_size_mb:.1f} MB\n\n"
                "The website download itself "
                "was successful."
            )


    # =====================================================
    # ERRORS
    # =====================================================

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
                "• Website requires login\n"
                "• DRM protected video\n"
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


# =========================================================
# HOME
# =========================================================

@web_app.get("/")
async def home():

    return (
        "🤖 Sam Downloader Bot is running!"
    )


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
        filters.TEXT
        & ~filters.COMMAND,
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
