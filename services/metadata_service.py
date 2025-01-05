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
        self.max_retries = 3
        self.FAILED_QUEUE = "metadata_failed_queue"
        self.PROCESSING_SET = "metadata_processing"

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
        chrome_options.binary_location = "/usr/bin/chromium"
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

        # Extract AI-generated title (v2t-title)
        v2t_title = soup.find("div", {"data-e2e": "v2t-title"})
        if v2t_title:
            metadata["v2t_title"] = v2t_title.get_text(strip=True)

        # Extract AI-generated description (v2t-desc)
        v2t_desc = soup.find("div", {"data-e2e": "v2t-desc"})
        if v2t_desc:
            metadata["v2t_desc"] = v2t_desc.get_text(strip=True)

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

    def update_metadata(self, video_data: Dict):
        """Store video metadata in Redis."""
        try:
            username = video_data["username"]
            video_id = video_data["video_id"]

            # Create a copy of video_data to modify
            redis_data = video_data.copy()

            # Convert lists and dicts to JSON strings
            for key, value in redis_data.items():
                if isinstance(value, (list, dict)):
                    redis_data[key] = json.dumps(value)

            # Store video metadata using hash
            redis_key = f"metadata:{video_id}"  # Simplified key format
            self.redis_client.hset(redis_key, mapping=redis_data)

            # Add to user's video list
            user_videos_key = f"user_videos:{username}"
            self.redis_client.sadd(user_videos_key, video_id)

            # Add to global video list
            self.redis_client.sadd("all_videos", video_id)

            # Add to sorted set by date
            if "date" in video_data:
                timestamp = self.parse_date_string(video_data["date"])
                self.redis_client.zadd("videos_by_date", {video_id: timestamp})

            # Update tags index
            if "tags" in video_data:
                for tag in video_data["tags"]:
                    self.redis_client.sadd(f"tag:{tag}", video_id)
                    self.redis_client.sadd("all_tags", tag)

            logger.info(f"Successfully updated metadata for video {video_id}")

        except Exception as e:
            logger.error(f"Error updating metadata: {e}")
            raise

    def process_video(self, video_data: Dict):
        """Process a single video to collect metadata."""
        video_id = video_data.get("video_id", "unknown")

        try:
            # Mark as processing
            self.redis_client.sadd(self.PROCESSING_SET, video_id)

            # Original processing code here...
            chrome_options = self.setup_chrome_options()
            service = webdriver.ChromeService(executable_path="/usr/bin/chromedriver")
            driver = webdriver.Chrome(options=chrome_options, service=service)

            try:
                url = video_data["url"]
                driver.get(url)
                time.sleep(2)

                html_content = driver.page_source
                metadata = self.extract_metadata(html_content)
                video_data.update(metadata)
                video_data["metadata_collection_time"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                # Update metadata and queue for download
                self.update_metadata(video_data)
                self.redis_client.rpush(DOWNLOAD_QUEUE_KEY, json.dumps(video_data))
                logger.info(f"Successfully processed video {video_id}")

                # Remove from processing set on success
                self.redis_client.srem(self.PROCESSING_SET, video_id)

            finally:
                driver.quit()

        except Exception as e:
            logger.error(f"Error processing video {video_id}: {e}")
            retry_count = video_data.get("retry_count", 0) + 1
            video_data["retry_count"] = retry_count
            video_data["last_error"] = str(e)

            if retry_count < self.max_retries:
                # Put back in queue for retry
                logger.info(
                    f"Requeueing video {video_id} for retry {retry_count}/{self.max_retries}"
                )
                self.redis_client.rpush(QUEUE_KEY, json.dumps(video_data))
            else:
                # Move to failed queue
                logger.error(
                    f"Video {video_id} failed after {self.max_retries} attempts"
                )
                self.redis_client.rpush(self.FAILED_QUEUE, json.dumps(video_data))

            # Remove from processing set
            self.redis_client.srem(self.PROCESSING_SET, video_id)

    def retry_failed_videos(self):
        """Retry videos from the failed queue."""
        while True:
            failed_video = self.redis_client.lpop(self.FAILED_QUEUE)
            if not failed_video:
                break

            video_data = json.loads(failed_video)
            video_data["retry_count"] = 0  # Reset retry count
            logger.info(f"Retrying failed video {video_data.get('video_id')}")
            self.redis_client.rpush(QUEUE_KEY, json.dumps(video_data))

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

    def get_metadata(self, username: str, video_id: str) -> Dict:
        """Retrieve video metadata from Redis."""
        try:
            redis_key = f"metadata:{username}:{video_id}"
            data = self.redis_client.hgetall(redis_key)

            # Convert JSON strings back to Python objects
            for key, value in data.items():
                try:
                    data[key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    # If not JSON, keep original value
                    pass

            return data
        except Exception as e:
            logger.error(f"Error retrieving metadata: {e}")
            return {}


if __name__ == "__main__":
    service = MetadataService()
    service.run()
