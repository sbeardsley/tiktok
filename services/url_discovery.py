from pathlib import Path
import json
import time
import schedule
from datetime import datetime
import redis
import logging
from typing import Set, List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("url_discovery.log"), logging.StreamHandler()],
)
logger = logging.getLogger("url_discovery")

# Redis connection
redis_client = redis.Redis(host="localhost", port=6379, db=0)
QUEUE_KEY = "tiktok_video_queue"
PROCESSING_LOCK = "url_discovery_running"


class URLDiscoveryService:
    def __init__(self):
        self.downloads_dir = Path("downloads")

    def get_known_video_ids(self) -> Set[str]:
        """Get all video IDs we already have metadata for."""
        known_ids = set()

        for metadata_file in self.downloads_dir.rglob("metadata.json"):
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    for video in metadata:
                        if video.get("video_id"):
                            known_ids.add(video["video_id"])
            except Exception as e:
                logger.error(f"Error reading {metadata_file}: {e}")

        return known_ids

    def read_usernames(self, filename="usernames.md") -> List[str]:
        """Read usernames from file, skipping empty lines and stripping whitespace."""
        try:
            with open(filename, "r") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Error reading usernames file: {e}")
            return []

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

    def fetch_user_videos(self, username: str, video_type="videos") -> List[Dict]:
        """Fetch video URLs for a given username using existing scraping logic."""
        base_url = f"https://www.tiktok.com/@{username}"
        if video_type == "liked":
            base_url += "/liked"
        elif video_type == "favorite":
            base_url += "/favorite"

        chrome_options = self.setup_chrome_options()
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        video_data = []
        seen_urls = set()

        try:
            driver.get(base_url)
            time.sleep(3)

            # Check for private content
            try:
                private_msg = driver.find_element(
                    By.XPATH,
                    "//*[contains(text(), 'This user's liked videos are private') or contains(text(), 'This account is private')]",
                )
                if private_msg:
                    logger.info(f"User {username} has private videos")
                    return []
            except:
                pass

            # Implement infinite scroll to get all videos
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_attempts = 0
            max_attempts = 20

            while scroll_attempts < max_attempts:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)

                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0
                    last_height = new_height

                if scroll_attempts >= 3:
                    break

            # Get all video URLs
            video_containers = driver.find_elements(
                By.CSS_SELECTOR,
                "[data-e2e='user-post-item'], div[class*='DivItemContainer']",
            )

            for container in video_containers:
                try:
                    url = container.find_element(
                        By.CSS_SELECTOR, "a[href*='/video/']"
                    ).get_attribute("href")

                    if url not in seen_urls:
                        video_id = url.split("/")[-1].split("?")[0]
                        seen_urls.add(url)
                        video_data.append(
                            {
                                "url": url,
                                "video_id": video_id,
                                "username": username,
                                "discovery_time": datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                            }
                        )
                except Exception as e:
                    logger.error(f"Error extracting video URL: {e}")
                    continue

            return video_data

        except Exception as e:
            logger.error(f"Error fetching videos for {username}: {e}")
            return []

        finally:
            driver.quit()

    def queue_new_videos(self, videos: List[Dict]):
        """Add new videos to the Redis queue."""
        known_ids = self.get_known_video_ids()
        queued_count = 0

        for video in videos:
            video_id = video.get("video_id")
            if video_id and video_id not in known_ids:
                try:
                    redis_client.rpush(QUEUE_KEY, json.dumps(video))
                    queued_count += 1
                    logger.info(f"Queued new video: {video_id}")
                except Exception as e:
                    logger.error(f"Error queuing video {video_id}: {e}")

        return queued_count

    def process_all_users(self):
        """Process all users from usernames.md to find new videos."""
        if redis_client.get(PROCESSING_LOCK):
            logger.info("Another instance is already running")
            return

        try:
            redis_client.setex(PROCESSING_LOCK, 3600, "true")

            usernames = self.read_usernames()
            logger.info(f"Processing {len(usernames)} users")

            total_queued = 0
            for username in usernames:
                logger.info(f"Fetching videos for {username}")
                videos = self.fetch_user_videos(username)
                queued = self.queue_new_videos(videos)
                total_queued += queued
                logger.info(f"Queued {queued} new videos for {username}")

                # Be nice to TikTok's servers
                time.sleep(5)

            logger.info(f"Finished processing. Total new videos queued: {total_queued}")

        except Exception as e:
            logger.error(f"Error in process_all_users: {e}")
        finally:
            redis_client.delete(PROCESSING_LOCK)


def run_service():
    """Main service function."""
    service = URLDiscoveryService()

    # Schedule the job to run every hour
    schedule.every().hour.do(service.process_all_users)

    logger.info("URL Discovery Service started")

    # Run once immediately on startup
    service.process_all_users()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_service()
