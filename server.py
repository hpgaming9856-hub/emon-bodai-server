import os
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from pydantic import BaseModel
import yt_dlp


app = FastAPI(title="Emon Bodai Downloader")


SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://vryuvjzkgdbyhfvxhkkz.supabase.co"
)

SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


class DownloadRequest(BaseModel):
    url: str


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_settings():
    url = (
        SUPABASE_URL
        + "/rest/v1/app_settings"
        + "?select=download_limit_enabled,download_limit"
        + "&order=id.asc"
        + "&limit=1"
    )

    request = Request(
        url,
        headers=supabase_headers(),
        method="GET"
    )

    with urlopen(request, timeout=10) as response:
        data = response.read().decode("utf-8")

    rows = __import__("json").loads(data)

    if not rows:
        return False, 0

    row = rows[0]

    enabled = bool(row.get("download_limit_enabled", False))
    limit = int(row.get("download_limit") or 0)

    return enabled, limit


def get_download_usage():
    url = (
        SUPABASE_URL
        + "/rest/v1/rpc/get_download_usage_24h"
    )

    request = Request(
        url,
        data=b"{}",
        headers=supabase_headers(),
        method="POST"
    )

    with urlopen(request, timeout=10) as response:
        data = response.read().decode("utf-8").strip()

    if data.startswith("["):
        rows = __import__("json").loads(data)
        return int(rows[0]) if rows else 0

    return int(data)


def log_download(url, status, error_message=""):
    try:
        import json

        body = {
            "url": url,
            "platform": get_platform(url),
            "status": status
        }

        if error_message:
            body["error_message"] = error_message[:1000]

        data = json.dumps(body).encode("utf-8")

        request = Request(
            SUPABASE_URL + "/rest/v1/download_logs",
            data=data,
            headers={
                **supabase_headers(),
                "Prefer": "return=minimal"
            },
            method="POST"
        )

        with urlopen(request, timeout=10):
            pass

    except Exception:
        # Logging failure must never break downloading.
        pass


def get_platform(url):
    value = url.lower()

    if "youtube.com" in value or "youtu.be" in value:
        return "YouTube"

    if "tiktok.com" in value:
        return "TikTok"

    if "facebook.com" in value or "fb.watch" in value:
        return "Facebook"

    if "instagram.com" in value:
        return "Instagram"

    return "Other"


def allowed_url(url):
    value = url.lower().strip()

    allowed_hosts = (
        "youtube.com",
        "youtu.be",
        "tiktok.com",
        "facebook.com",
        "fb.watch",
        "instagram.com"
    )

    return (
        value.startswith("http://")
        or value.startswith("https://")
    ) and any(host in value for host in allowed_hosts)


def cleanup_directory(path):
    shutil.rmtree(path, ignore_errors=True)


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Emon Bodai Downloader"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/download")
def download_video(
    request: DownloadRequest,
    background_tasks: BackgroundTasks
):

    video_url = request.url.strip()

    if not allowed_url(video_url):
        log_download(
            video_url,
            "failed",
            "Unsupported or invalid video URL."
        )

        raise HTTPException(
            status_code=400,
            detail="Unsupported or invalid video URL."
        )

    # -----------------------------
    # DOWNLOAD CONTROL
    # -----------------------------

    try:
        limit_enabled, download_limit = get_settings()

        if limit_enabled and download_limit > 0:

            used = get_download_usage()

            if used >= download_limit:

                log_download(
                    video_url,
                    "failed",
                    "24-hour download limit reached."
                )

                raise HTTPException(
                    status_code=429,
                    detail="24-hour download limit reached."
                )

    except HTTPException:
        raise

    except Exception:
        # If Supabase temporarily fails,
        # keep the existing downloader working.
        pass

    work_dir = Path(
        tempfile.mkdtemp(
            prefix="emon_bodai_"
        )
    )

    output_template = str(
        work_dir / "%(id)s.%(ext)s"
    )

    try:

        options = {
            "format": "bv*+ba/b",
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "ffmpeg_location": "/usr/bin/ffmpeg",

            # Speed optimization
            "concurrent_fragment_downloads": 8,

            # Avoid unnecessary work
            "overwrites": True,
            "continuedl": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:

            info = ydl.extract_info(
                video_url,
                download=True
            )

            downloaded = Path(
                ydl.prepare_filename(info)
            )

        mp4_file = downloaded.with_suffix(".mp4")

        if not mp4_file.exists():

            candidates = list(
                work_dir.glob("*.mp4")
            )

            if not candidates:
                raise RuntimeError(
                    "MP4 file was not created."
                )

            mp4_file = candidates[0]

        filename = (
            "EmonBodai_"
            + uuid.uuid4().hex[:10]
            + ".mp4"
        )

        # Successful download log
        log_download(
            video_url,
            "success"
        )

        # Delete temporary files after response
        background_tasks.add_task(
            cleanup_directory,
            str(work_dir)
        )

        return FileResponse(
            path=str(mp4_file),
            media_type="video/mp4",
            filename=filename
        )

    except Exception as e:

        error_message = str(e)

        cleanup_directory(
            str(work_dir)
        )

        log_download(
            video_url,
            "failed",
            error_message
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Download failed: "
                + error_message[:500]
            )
        )


@app.get("/version")
def version():
    return {
        "name": "Emon Bodai",
        "version": "2.0"
        }
