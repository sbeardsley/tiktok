from pathlib import Path
import json
import time
import redis
import logging
from typing import Dict, List
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("metadata_service.log"), logging.StreamHandler()],
)
logger = logging.getLogger("metadata_service")

# Redis connection
redis_client = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0)
QUEUE_KEY = "tiktok_video_queue"
DOWNLOAD_QUEUE_KEY = "video_download_queue"


class MetadataService:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )

    def setup_chrome_options(self) -> Options:
        """Set up Chrome options for scraping."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        return chrome_options

    def extract_metadata(self, html_content: str) -> Dict:
        """Extract metadata from TikTok video page HTML."""
        soup = BeautifulSoup(html_content, "html.parser")
        metadata = {}

        # Extract the author and date
        author_info = soup.find("a", class_="css-ej4tw5-StyledLink")
        if author_info:
            metadata["author"] = author_info.get_text(strip=True)

        date_info = soup.find("span", class_="css-5set0y-SpanOtherInfos")
        if date_info:
            date_text = date_info.get_text(strip=True).split(" · ")[-1]
            metadata["date"] = date_text

        # Extract video description
        description = soup.find("h1", class_="css-1fbzdvh-H1Container")
        if description:
            metadata["description"] = description.get_text(strip=True)

        # Extract music info
        music_info = soup.find("h4", class_="css-blqru4-H4Link")
        if music_info:
            metadata["music"] = music_info.get_text(strip=True)

        # Extract tags
        tags = soup.find_all("a", class_="css-ln01ug-StyledTagLink")
        metadata["tags"] = [tag.get_text(strip=True).lower() for tag in tags]

        # Extract additional metadata
        metadata["tags"].extend(
            self.extract_tags_from_description(metadata.get("description", ""))
        )
        metadata["tags"] = sorted(list(set(metadata["tags"])))  # Deduplicate and sort

        return metadata

    def extract_tags_from_description(self, description: str) -> List[str]:
        """Extract hashtags from description text."""
        if not description:
            return []

        tags = []
        parts = description.split()

        for part in parts:
            if part.startswith("#"):
                hashtags = [tag.lower() for tag in part.split("#") if tag]
                tags.extend(hashtags)
            elif "#" in part:
                hashtags = [tag.lower() for tag in part.split("#")[1:] if tag]
                tags.extend(hashtags)

        return list(set(tags))

    def update_metadata(self, video_data: Dict):
        """Store video metadata in Redis."""
        try:
            username = video_data["username"]
            video_id = video_data["video_id"]

            # Store video metadata using hash
            # Key format: metadata:{username}:{video_id}
            redis_key = f"metadata:{username}:{video_id}"
            self.redis_client.hset(redis_key, mapping=video_data)

            # Add to user's video list
            user_videos_key = f"user_videos:{username}"
            self.redis_client.sadd(user_videos_key, video_id)

            # Add to global video list
            self.redis_client.sadd("all_videos", video_id)

            # Update tags index
            if "tags" in video_data:
                for tag in video_data["tags"]:
                    self.redis_client.sadd(f"tag:{tag}", video_id)
                    self.redis_client.sadd("all_tags", tag)

        except Exception as e:
            logger.error(f"Error updating metadata: {e}")
            raise

    def process_video(self, video_data: Dict):
        """Process a single video to collect metadata."""
        chrome_options = self.setup_chrome_options()
        driver = webdriver.Chrome(options=chrome_options)

        try:
            url = video_data["url"]
            driver.get(url)
            time.sleep(2)  # Wait for page to load

            # Extract metadata
            html_content = driver.page_source
            metadata = self.extract_metadata(html_content)

            # Combine with existing video data
            video_data.update(metadata)
            video_data["metadata_collection_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

            # Update metadata file
            self.update_metadata(video_data)

            # Queue for video download
            redis_client.rpush(DOWNLOAD_QUEUE_KEY, json.dumps(video_data))
            logger.info(f"Queued video {video_data['video_id']} for download")

        except Exception as e:
            logger.error(f"Error processing video {video_data.get('url')}: {e}")
        finally:
            driver.quit()

    def run(self):
        """Main service loop."""
        logger.info("Metadata Service started")

        while True:
            try:
                # Get next video from queue
                video_data = redis_client.lpop(QUEUE_KEY)
                if video_data:
                    video_data = json.loads(video_data)
                    logger.info(f"Processing video: {video_data.get('video_id')}")
                    self.process_video(video_data)
                else:
                    # No videos in queue, wait before checking again
                    time.sleep(5)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)


if __name__ == "__main__":
    service = MetadataService()
    service.run()
