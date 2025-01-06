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
import os

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
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )

    def read_usernames(self) -> List[str]:
        """Read usernames from Redis."""
        try:
            usernames = self.redis_client.smembers("all_usernames")
            logger.info(f"Found {len(usernames)} usernames in Redis")
            return sorted(list(usernames))  # Return sorted list for consistency
        except Exception as e:
            logger.error(f"Error reading usernames from Redis: {e}")
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
        chrome_options.binary_location = "/usr/bin/chromium"
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
        service = webdriver.ChromeService(executable_path="/usr/bin/chromedriver")
        driver = webdriver.Chrome(options=chrome_options, service=service)
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        video_data = []
        seen_urls = set()

        try:
            # Get list of video URLs first
            driver.get(base_url)
            time.sleep(3)

            # Check for private content message
            try:
                private_msg = driver.find_element(
                    By.XPATH,
                    "//*[contains(text(), 'This user's liked videos are private') or contains(text(), 'This account is private')]",
                )
                if private_msg:
                    logger.info("This user's videos are private")
                    return []
            except:
                pass

            # Check for and click refresh button if no videos are shown
            try:
                video_containers = driver.find_elements(
                    By.CSS_SELECTOR,
                    "[data-e2e='user-post-item'] a[href*='/video/']",
                )

                if not video_containers:
                    logger.info(
                        "No videos found initially, looking for refresh button..."
                    )
                    refresh_button = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (
                                By.XPATH,
                                "//button[contains(text(), 'Refresh')] | //div[contains(@class, 'refresh')]",
                            )
                        )
                    )
                    refresh_button.click()
                    logger.info(
                        "Clicked refresh button, waiting for content to load..."
                    )
                    time.sleep(3)  # Wait for refresh
            except Exception as e:
                logger.debug(f"No refresh button found or error clicking it: {str(e)}")

            # Implement infinite scroll to get all videos
            last_height = driver.execute_script("return document.body.scrollHeight")
            video_count = 0
            scroll_attempts = 0
            max_attempts = 20  # Maximum number of scroll attempts

            with tqdm(desc=f"Loading videos for {username}", unit="scroll") as pbar:
                while scroll_attempts < max_attempts:
                    # Scroll down
                    driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);"
                    )
                    time.sleep(2)  # Wait for content to load

                    # Get current video count
                    video_containers = driver.find_elements(
                        By.CSS_SELECTOR,
                        "[data-e2e='user-post-item'] a[href*='/video/']",
                    )
                    new_count = len(video_containers)

                    # Update progress
                    if new_count > video_count:
                        pbar.update(new_count - video_count)
                        video_count = new_count
                        scroll_attempts = 0  # Reset attempts if we found new videos
                    else:
                        scroll_attempts += 1  # Increment attempts if no new videos

                    # Calculate new scroll height
                    new_height = driver.execute_script(
                        "return document.body.scrollHeight"
                    )

                    # Break if no new content (after multiple attempts)
                    if new_height == last_height and scroll_attempts >= 3:
                        break

                    last_height = new_height

            logger.info(f"Found {video_count} total videos after scrolling")

            # Get all video URLs
            video_containers = driver.find_elements(
                By.CSS_SELECTOR,
                "[data-e2e='user-post-item'] a[href*='/video/']",
            )

            # Extract URLs from containers
            for container in video_containers:
                try:
                    url = container.get_attribute("href")
                    # url = container.find_element(
                    #     By.CSS_SELECTOR, "a[href*='/video/']"
                    # ).get_attribute("href")

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
                    # Get container HTML for debugging
                    try:
                        html_content = container.get_attribute("outerHTML")
                        logger.error(
                            f"Error extracting video URL: {e}\n"
                            f"Container HTML:\n{html_content}\n"
                            f"Container class: {container.get_attribute('class')}\n"
                            f"Container tag: {container.tag_name}"
                        )
                    except Exception as html_e:
                        logger.error(
                            f"Error extracting video URL: {e}\n"
                            f"Failed to get container HTML: {html_e}"
                        )
                    continue

            return video_data

        except Exception as e:
            logger.error(f"Error fetching videos for {username}: {e}")
            return []

        finally:
            driver.quit()

    def get_existing_videos_for_user(self, username: str) -> Set[str]:
        """Get all video IDs that exist in Redis for a specific user."""
        existing_ids = set()

        # Check user's video set in Redis
        user_videos_key = f"user_videos:{username}"
        existing_ids.update(self.redis_client.smembers(user_videos_key))

        # Check metadata keys for this user
        metadata_pattern = f"metadata:{username}:*"
        for key in self.redis_client.scan_iter(match=metadata_pattern):
            video_id = key.split(":")[-1]
            existing_ids.add(video_id)

        # Check discovery queue for existing videos
        queue_items = self.redis_client.lrange(QUEUE_KEY, 0, -1)
        for item in queue_items:
            try:
                video_data = json.loads(item)
                if video_data.get("username") == username:
                    video_id = video_data.get("video_id")
                    if video_id:
                        existing_ids.add(video_id)
            except json.JSONDecodeError:
                continue

        # Check metadata download queue
        metadata_queue_items = self.redis_client.lrange("video_download_queue", 0, -1)
        for item in metadata_queue_items:
            try:
                video_data = json.loads(item)
                if video_data.get("username") == username:
                    video_id = video_data.get("video_id")
                    if video_id:
                        existing_ids.add(video_id)
            except json.JSONDecodeError:
                continue

        # NEW: Check video download queue
        download_queue_items = self.redis_client.lrange("video_download_queue", 0, -1)
        for item in download_queue_items:
            try:
                video_data = json.loads(item)
                if video_data.get("username") == username:
                    video_id = video_data.get("video_id")
                    if video_id:
                        existing_ids.add(video_id)
            except json.JSONDecodeError:
                continue

        logger.info(f"Found {len(existing_ids)} existing videos for user {username}")
        return existing_ids

    def queue_new_videos(self, videos: List[Dict], username: str):
        """Add new videos to the Redis queue, skipping existing ones."""
        existing_ids = self.get_existing_videos_for_user(username)
        queued_count = 0

        for video in videos:
            video_id = video.get("video_id")
            if video_id and video_id not in existing_ids:
                try:
                    self.redis_client.rpush(QUEUE_KEY, json.dumps(video))
                    queued_count += 1
                    logger.info(f"Queued new video: {video_id}")
                except Exception as e:
                    logger.error(f"Error queuing video {video_id}: {e}")

        logger.info(f"Queued {queued_count} new videos for {username}")
        return queued_count

    def process_all_users(self):
        """Process all users from usernames.md to find new videos."""
        # Force clear any stale lock on startup
        if hasattr(self, "_first_run"):
            if self.redis_client.get(PROCESSING_LOCK):
                logger.info("Another instance is already running")
                return
        else:
            self._first_run = False
            logger.info("First run - clearing any stale lock")
            self.redis_client.delete(PROCESSING_LOCK)

        try:
            self.redis_client.setex(PROCESSING_LOCK, 3600, "true")  # 1 hour timeout
            usernames = self.read_usernames()
            logger.info(f"Processing {len(usernames)} users")

            total_queued = 0
            for username in usernames:
                logger.info(f"Fetching videos for {username}")
                videos = self.fetch_user_videos(username)
                queued = self.queue_new_videos(videos, username)
                total_queued += queued

                # Be nice to TikTok's servers
                time.sleep(5)

            logger.info(f"Finished processing. Total new videos queued: {total_queued}")

        except Exception as e:
            logger.error(f"Error in process_all_users: {e}")
        finally:
            self.redis_client.delete(PROCESSING_LOCK)


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
