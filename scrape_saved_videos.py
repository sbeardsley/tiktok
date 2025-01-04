from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import os
from yt_dlp import YoutubeDL
import argparse


def scrape_bookmarked_videos(driver):
    """
    Scrape bookmarked TikTok videos from logged-in user's profile.
    """
    try:
        # Navigate to bookmarks page
        driver.get("https://www.tiktok.com/bookmarks")
        time.sleep(3)

        # Handle potential refresh button
        try:
            refresh_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//button[contains(text(), 'Refresh')]")
                )
            )
            refresh_button.click()
            print("Found and clicked refresh button")
            time.sleep(3)
        except Exception:
            print("No refresh button found")

        # Scroll to load more videos
        for _ in range(3):  # Adjust range for more scrolling
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        video_elements = driver.find_elements(
            By.XPATH, "//a[contains(@href, '/video/')]"
        )

        video_links = []
        for element in video_elements:
            href = element.get_attribute("href")
            if href and "/video/" in href:
                video_links.append(href)

        return list(set(video_links))

    except Exception as e:
        print(f"Error scraping bookmarks: {str(e)}")
        return []


def scrape_liked_videos(driver):
    """
    Scrape liked TikTok videos from logged-in user's profile.
    Note: Liked videos must be set to public in privacy settings.
    """
    try:
        # Navigate to liked videos page
        driver.get("https://www.tiktok.com/liked")
        time.sleep(3)

        # Handle potential refresh button
        try:
            refresh_button = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//button[contains(text(), 'Refresh')]")
                )
            )
            refresh_button.click()
            print("Found and clicked refresh button")
            time.sleep(3)
        except Exception:
            print("No refresh button found")

        # Scroll to load more videos
        for _ in range(3):  # Adjust range for more scrolling
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

        video_elements = driver.find_elements(
            By.XPATH, "//a[contains(@href, '/video/')]"
        )

        video_links = []
        for element in video_elements:
            href = element.get_attribute("href")
            if href and "/video/" in href:
                video_links.append(href)

        return list(set(video_links))

    except Exception as e:
        print(f"Error scraping liked videos: {str(e)}")
        return []


def login_to_tiktok(driver):
    """
    Handle TikTok login process.
    Note: You'll need to manually log in when the browser opens.
    """
    try:
        driver.get("https://www.tiktok.com/login")
        print("\nPlease log in to TikTok in the browser window...")
        print("Waiting for login (60 seconds)...")
        time.sleep(60)  # Give time for manual login
        return True
    except Exception as e:
        print(f"Login error: {str(e)}")
        return False


def download_videos(video_urls, folder_name):
    """
    Download videos from the provided URLs using yt-dlp, skipping existing files.
    """
    # Create folder for videos if it doesn't exist
    folder_path = os.path.join("downloads", folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Configure yt-dlp options
    ydl_opts = {
        "outtmpl": os.path.join(folder_path, "%(id)s.%(ext)s"),
        "format": "best",
        "quiet": False,
        "no_warnings": True,
        "extract_flat": False,
    }

    # First, get video IDs of existing files
    existing_files = set()
    for file in os.listdir(folder_path):
        if file.endswith(".mp4"):
            video_id = file.split(".")[0]  # Get video ID from filename
            existing_files.add(video_id)

    # Download each video, skipping existing ones
    with YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(video_urls, 1):
            try:
                # Extract video ID from URL
                video_id = url.split("/")[-1].split("?")[0]
                print(f"\n This one! {video_id} (already downloaded)\n\n")
                # Skip if video already exists
                if video_id in existing_files:
                    print(
                        f"\nSkipping video {i}/{len(video_urls)} (already downloaded)"
                    )
                    continue

                print(f"\nDownloading video {i}/{len(video_urls)}")
                # ydl.download([url])
            except Exception as e:
                print(f"Error downloading {url}: {str(e)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download bookmarked or liked TikTok videos"
    )
    parser.add_argument(
        "action",
        choices=["bookmarked", "liked"],
        help="Choose whether to download bookmarked or liked videos",
    )
    args = parser.parse_args()

    # Set up Chrome options without headless mode for login
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    try:
        if login_to_tiktok(driver):
            if args.action == "bookmarked":
                print("\nScraping bookmarked videos...")
                videos = scrape_bookmarked_videos(driver)
                folder_name = "bookmarked"
            else:
                print("\nScraping liked videos...")
                videos = scrape_liked_videos(driver)
                folder_name = "liked"

            if videos:
                print(f"\nFound {len(videos)} videos:")
                for video in videos:
                    print(video)

                response = input(
                    "\nDo you want to download these videos? (y/n): "
                ).lower()
                if response == "y":
                    download_videos(videos, folder_name)
                    print(
                        "\nDownload complete! Videos are stored in the 'downloads' folder."
                    )
            else:
                print("No videos found or unable to access the videos.")
        else:
            print("Login failed!")
    finally:
        driver.quit()
