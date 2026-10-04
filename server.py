import os
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp


app = FastAPI(title="Emon Bodai Downloader")


class DownloadRequest(BaseModel):
    url: str


def allowed_url(url: str) -> bool:
    allowed_hosts = (
        "youtube.com",
        "youtu.be",
        "tiktok.com",
        "facebook.com",
        "fb.watch",
        "instagram.com",
    )

    value = url.lower().strip()

    return (
        value.startswith("http://")
        or value.startswith("https://")
    ) and any(host in value for host in allowed_hosts)


@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Emon Bodai Downloader"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/download")
def download_video(request: DownloadRequest):

    video_url = request.url.strip()

    if not allowed_url(video_url):
        raise HTTPException(
            status_code=400,
            detail="Unsupported or invalid video URL."
        )

    work_dir = Path(tempfile.mkdtemp(prefix="emon_bodai_"))
    output_template = str(work_dir / "%(id)s.%(ext)s")

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
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=True)
            downloaded = Path(ydl.prepare_filename(info))

        mp4_file = downloaded.with_suffix(".mp4")

        if not mp4_file.exists():
            candidates = list(work_dir.glob("*.mp4"))

            if not candidates:
                raise RuntimeError("MP4 file was not created.")

            mp4_file = candidates[0]

        filename = f"EmonBodai_{uuid.uuid4().hex[:10]}.mp4"

        return FileResponse(
            path=str(mp4_file),
            media_type="video/mp4",
            filename=filename,
            background=None
        )

    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {str(e)[:500]}"
        )


@app.get("/version")
def version():
    return {
        "name": "Emon Bodai",
        "version": "1.0"
      }
