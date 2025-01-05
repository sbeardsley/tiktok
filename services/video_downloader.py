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
        self.downloads_dir = Path("downloads")
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )
        self.max_retries = 3
        self.FAILED_QUEUE = "download_failed_queue"
        self.PROCESSING_SET = "download_processing"

        # Create downloads directory if it doesn't exist
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    def parse_date_string(self, date_str: str) -> float:
        """Extract timestamp from date string like 'The Cheese Knees·2022-12-13'"""
        try:
            # Split by '·' and take the last part which should be the date
            date_part = date_str.split("·")[-1].strip()
            # Convert to timestamp
            return time.mktime(time.strptime(date_part, "%Y-%m-%d"))
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}', using current time: {e}")
            # Return current timestamp instead of 0
            return time.time()

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

    def update_video_paths(
        self, username: str, video_id: str, video_path: str, thumbnail_path: str
    ):
        """Update video and thumbnail paths in Redis."""
        redis_key = f"metadata:{video_id}"
        self.redis_client.hset(redis_key, "video_path", video_path)
        self.redis_client.hset(redis_key, "thumbnail_path", thumbnail_path)
        download_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.redis_client.hset(redis_key, "download_time", download_time)

        # Update the sorted set with download time if no valid date exists
        video_data = self.redis_client.hgetall(redis_key)
        if not video_data.get("date"):
            self.redis_client.zadd("videos_by_date", {video_id: time.time()})
        else:
            # Ensure the video is in the sorted set with its proper date
            timestamp = self.parse_date_string(video_data["date"])
            self.redis_client.zadd("videos_by_date", {video_id: timestamp})

        # Remove file_missing flag when video is successfully downloaded
        self.redis_client.hdel(redis_key, "file_missing")

    def delete_video(self, video_id: str):
        """Mark video as deleted and remove from sorted sets."""
        try:
            # Mark as deleted in metadata
            redis_key = f"metadata:{video_id}"
            self.redis_client.hset(redis_key, "deleted", "True")

            # Remove from sorted set
            self.redis_client.zrem("videos_by_date", video_id)

            logger.info(
                f"Marked video {video_id} as deleted and removed from sorted sets"
            )
        except Exception as e:
            logger.error(f"Error marking video {video_id} as deleted: {e}")

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
            # Mark as processing
            self.redis_client.sadd(self.PROCESSING_SET, video_id)

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
                    # Update video paths in Redis
                    self.update_video_paths(
                        username,
                        video_id,
                        str(video_path.relative_to(self.downloads_dir)),
                        thumbnail_path,
                    )
                    logger.info(f"Successfully processed video: {video_id}")
                else:
                    logger.error(f"Failed to generate thumbnail for video: {video_id}")

            # Remove from processing on success
            self.redis_client.srem(self.PROCESSING_SET, video_id)

        except Exception as e:
            logger.error(f"Error downloading video {video_id}: {e}")
            retry_count = video_data.get("retry_count", 0) + 1
            video_data["retry_count"] = retry_count
            video_data["last_error"] = str(e)

            if retry_count < self.max_retries:
                # Put back in queue for retry
                logger.info(
                    f"Requeueing video {video_id} for retry {retry_count}/{self.max_retries}"
                )
                self.redis_client.rpush(DOWNLOAD_QUEUE_KEY, json.dumps(video_data))
            else:
                # Move to failed queue
                logger.error(
                    f"Video {video_id} failed after {self.max_retries} attempts"
                )
                self.redis_client.rpush(self.FAILED_QUEUE, json.dumps(video_data))

            # Remove from processing set
            self.redis_client.srem(self.PROCESSING_SET, video_id)

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


if __name__ == "__main__":
    service = VideoDownloader()
    service.run()