from pathlib import Path
import json
import time
import redis
import logging
from typing import Dict
import cv2
from PIL import Image
from yt_dlp import YoutubeDL
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("video_downloader.log"), logging.StreamHandler()],
)
logger = logging.getLogger("video_downloader")

# Redis connection
redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0)
DOWNLOAD_QUEUE_KEY = "video_download_queue"


class VideoDownloader:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )

    def generate_thumbnail(self, video_path: Path) -> str:
        """Generate a thumbnail from a video file."""
        thumbnail_path = video_path.parent / f"{video_path.stem}_thumb.jpg"

        try:
            video = cv2.VideoCapture(str(video_path))
            success, frame = video.read()

            if success:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)

                # Set fixed dimensions for TikTok aspect ratio
                width = 320
                height = 568

                # Resize image maintaining aspect ratio and adding black bars
                original_ratio = pil_image.size[0] / pil_image.size[1]
                target_ratio = width / height

                if original_ratio > target_ratio:
                    new_width = width
                    new_height = int(width / original_ratio)
                    resize_size = (new_width, new_height)
                    position = (0, (height - new_height) // 2)
                else:
                    new_height = height
                    new_width = int(height * original_ratio)
                    resize_size = (new_width, new_height)
                    position = ((width - new_width) // 2, 0)

                # Create black background
                background = Image.new("RGB", (width, height), (0, 0, 0))

                # Resize image
                pil_image = pil_image.resize(resize_size, Image.Resampling.LANCZOS)

                # Paste resized image onto black background
                background.paste(pil_image, position)

                # Save thumbnail
                background.save(thumbnail_path, "JPEG", quality=85)
                return str(thumbnail_path.relative_to(self.downloads_dir))

        except Exception as e:
            logger.error(f"Error generating thumbnail for {video_path}: {e}")
            return None
        finally:
            if "video" in locals():
                video.release()

    def update_metadata(self, video_data: Dict, video_path: str, thumbnail_path: str):
        """Update metadata file with video and thumbnail paths."""
        try:
            metadata_path = (
                self.downloads_dir / video_data["username"] / "metadata.json"
            )

            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Update video information
            for video in metadata:
                if video["video_id"] == video_data["video_id"]:
                    video["video_path"] = video_path
                    video["thumbnail_path"] = thumbnail_path
                    video["download_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    break

            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Error updating metadata: {e}")

    def download_video(self, video_data: Dict):
        """Download video and generate thumbnail."""
        username = video_data["username"]
        video_id = video_data["video_id"]
        url = video_data["url"]

        folder_path = self.downloads_dir / f"{username}_videos"
        folder_path.mkdir(parents=True, exist_ok=True)

        video_filename = f"{video_id}.mp4"
        video_path = folder_path / video_filename

        # Skip if video already exists
        if video_path.exists():
            logger.info(f"Video already exists: {video_path}")
            return

        try:
            ydl_opts = {
                "outtmpl": str(video_path),
                "format": "best",
                "quiet": True,
                "no_warnings": True,
            }

            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Generate thumbnail
            if video_path.exists():
                thumbnail_path = self.generate_thumbnail(video_path)
                if thumbnail_path:
                    # Update metadata with paths
                    self.update_metadata(
                        video_data,
                        str(video_path.relative_to(self.downloads_dir)),
                        thumbnail_path,
                    )
                    logger.info(f"Successfully processed video: {video_id}")
                else:
                    logger.error(f"Failed to generate thumbnail for video: {video_id}")

        except Exception as e:
            logger.error(f"Error downloading video {video_id}: {e}")

    def run(self):
        """Main service loop."""
        logger.info("Video Downloader Service started")

        while True:
            try:
                # Get next video from queue
                video_data = redis_client.lpop(DOWNLOAD_QUEUE_KEY)
                if video_data:
                    video_data = json.loads(video_data)
                    logger.info(f"Downloading video: {video_data.get('video_id')}")
                    self.download_video(video_data)
                else:
                    # No videos in queue, wait before checking again
                    time.sleep(5)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)

    def update_video_paths(
        self, username: str, video_id: str, video_path: str, thumbnail_path: str
    ):
        """Update video and thumbnail paths in Redis."""
        redis_key = f"metadata:{username}:{video_id}"
        self.redis_client.hset(redis_key, "video_path", video_path)
        self.redis_client.hset(redis_key, "thumbnail_path", thumbnail_path)
        self.redis_client.hset(
            redis_key, "download_time", time.strftime("%Y-%m-%d %H:%M:%S")
        )


if __name__ == "__main__":
    service = VideoDownloader()
    service.run()
