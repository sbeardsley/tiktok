from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import os
import json
from yt_dlp import YoutubeDL
import argparse
from tqdm import tqdm

from bs4 import BeautifulSoup


def extract_metadata_with_v2t(html_content):
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
    metadata["tags"] = [tag.get_text(strip=True) for tag in tags]

    # Extract custom title
    custom_title = soup.find("div", class_="css-1jlss87-DivTitle")
    if custom_title:
        metadata["custom_title"] = custom_title.get_text(strip=True)

    # Extract custom description
    custom_description = soup.find("div", class_="css-1ojpnt5-DivContent")
    if custom_description:
        metadata["custom_description"] = custom_description.get_text(strip=True)

    # Extract AI-generated title (v2t-title)
    v2t_title = soup.find("div", {"data-e2e": "v2t-title"})
    if v2t_title:
        metadata["v2t_title"] = v2t_title.get_text(strip=True)

    # Extract AI-generated description (v2t-desc)
    v2t_desc = soup.find("div", {"data-e2e": "v2t-desc"})
    if v2t_desc:
        metadata["v2t_desc"] = v2t_desc.get_text(strip=True)

    return metadata


def read_usernames(filename):
    """Read usernames from file, skipping empty lines and stripping whitespace."""
    with open(filename, "r") as f:
        return [line.strip() for line in f if line.strip()]


def process_all_users(usernames_file, video_type="videos"):
    """Process all usernames from the file."""
    usernames = read_usernames(usernames_file)
    total_users = len(usernames)
    tqdm.write(f"\nProcessing {total_users} users...")

    # Process each user individually
    for username in tqdm(usernames, desc="Processing users"):
        # tqdm.write(f"\n\nProcessing user: {username}")
        videos = scrape_user_videos(username, video_type)

        if videos:
            folder_name = f"{username}_{video_type}"
            download_videos(videos, folder_name)
        else:
            tqdm.write(f"No {video_type} videos found for {username}")

        # Ask if user wants to continue to next account
        # if username != usernames[-1]:  # Don't ask for the last user
        # continue_response = input("\nContinue to next user? (y/n): ").lower()
        # if continue_response != "y":
        # print("\nStopping process. Already processed users' videos are saved.")
        # break

    print("\nProcess complete! Videos are stored in the 'downloads' folder.")


def scrape_user_videos(username, video_type="videos"):
    """
    Scrape public TikTok videos from a user's profile.
    """
    base_url = f"https://www.tiktok.com/@{username}"
    if video_type == "liked":
        base_url += "/liked"
    elif video_type == "favorite":
        base_url += "/favorite"

    # Set up Chrome options
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

    driver = webdriver.Chrome(options=chrome_options)
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
                print("This user's videos are private")
                return []
        except:
            pass

        # Check for and click refresh button if no videos are shown
        try:
            video_containers = driver.find_elements(
                By.CSS_SELECTOR,
                "[data-e2e='user-post-item'], div[class*='DivItemContainer']",
            )

            if not video_containers:
                # tqdm.write("No videos found initially, looking for refresh button...")
                refresh_button = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (
                            By.XPATH,
                            "//button[contains(text(), 'Refresh')] | //div[contains(@class, 'refresh')]",
                        )
                    )
                )
                refresh_button.click()
                # tqdm.write("Clicked refresh button, waiting for content to load...")
                time.sleep(3)  # Wait for refresh
        except Exception as e:
            tqdm.write(f"No refresh button found or error clicking it: {str(e)}")

        # Implement infinite scroll to get all videos
        # print("\nScrolling to load all videos...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        video_count = 0
        scroll_attempts = 0
        max_attempts = 20  # Maximum number of scroll attempts

        with tqdm(desc="Loading videos", unit="scroll") as pbar:
            while scroll_attempts < max_attempts:
                # Scroll down
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)  # Wait for content to load

                # Get current video count
                video_containers = driver.find_elements(
                    By.CSS_SELECTOR,
                    "[data-e2e='user-post-item'], div[class*='DivItemContainer']",
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
                new_height = driver.execute_script("return document.body.scrollHeight")

                # Break if no new content (after multiple attempts)
                if new_height == last_height and scroll_attempts >= 3:
                    break

                last_height = new_height

        # print(f"\nFound {video_count} total videos after scrolling")

        # Get all video URLs
        video_containers = driver.find_elements(
            By.CSS_SELECTOR,
            "[data-e2e='user-post-item'], div[class*='DivItemContainer']",
        )

        video_urls = []
        for container in video_containers:
            try:
                url = container.find_element(
                    By.CSS_SELECTOR, "a[href*='/video/']"
                ).get_attribute("href")

                if url not in seen_urls:
                    seen_urls.add(url)
                    video_urls.append(url)
            except:
                continue

        # print(f"\nFound {len(video_urls)} unique video URLs")

        # Now visit each video URL to get detailed metadata
        for i, url in tqdm(
            enumerate(video_urls, 1),
            desc=f"Processing videos for {username}",
            total=len(video_urls),
            unit="video",
        ):
            try:
                # Print current video URL on new line to not interfere with progress bar
                # tqdm.write(f"\nProcessing: {url}")
                driver.get(url)
                time.sleep(2)  # Wait for page to load

                # Get the page source for BeautifulSoup parsing
                html_content = driver.page_source

                # Extract metadata using BeautifulSoup
                bs_metadata = extract_metadata_with_v2t(html_content)

                # Create video info dict with URL and ID
                video_info = {
                    "url": url,
                    "video_id": url.split("/")[-1].split("?")[0],
                    **bs_metadata,  # Merge the BeautifulSoup extracted metadata
                }

                # Add constant metadata
                video_info["username"] = username
                video_info["scrape_time"] = time.strftime("%Y-%m-%d %H:%M:%S")

                video_data.append(video_info)

                # # Print video info using tqdm.write to not interfere with progress bar
                # tqdm.write(f"   Published: {video_info.get('date', '')}")
                # tqdm.write(
                #     f"   Description: {video_info.get('description', '')[:100]}..."
                # )
                # if video_info.get("tags"):
                #     tqdm.write(f"   Tags: {', '.join(video_info['tags'])}")
                # if video_info.get("v2t_title"):
                #     tqdm.write(f"   AI Title: {video_info['v2t_title']}")
                # if video_info.get("v2t_desc"):
                #     tqdm.write(f"   AI Description: {video_info['v2t_desc'][:100]}...")
                # tqdm.write(f"   Music: {video_info.get('music', '')}")

            except Exception as e:
                tqdm.write(f"Error processing video: {str(e)}")
                continue

        return video_data

    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return []

    finally:
        driver.quit()


def download_videos(video_data, username):
    """
    Download videos and save metadata.
    """
    folder_path = os.path.join("downloads", username)
    os.makedirs(folder_path, exist_ok=True)

    # Save metadata to JSON
    metadata_path = os.path.join(folder_path, "metadata.json")
    try:
        if os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0:
            with open(metadata_path, "r", encoding="utf-8") as f:
                existing_metadata = json.load(f)
        else:
            existing_metadata = []
    except json.JSONDecodeError:
        print(f"Warning: Could not read existing metadata file. Starting fresh.")
        existing_metadata = []

    # Update metadata with new videos
    video_ids = {v["video_id"] for v in existing_metadata}
    new_metadata = [v for v in video_data if v["video_id"] not in video_ids]
    all_metadata = existing_metadata + new_metadata

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(all_metadata, f, indent=2, ensure_ascii=False)

    # Download videos
    ydl_opts = {
        "outtmpl": os.path.join(folder_path, "%(id)s.%(ext)s"),
        "format": "best",
        "quiet": True,
        "no_warnings": True,
        "postprocessor_args": [
            "-metadata",
            "title=%(title)s",
            "-metadata",
            "description=%(description)s",
            "-metadata",
            "author=%(uploader)s",
        ],
    }

    # First, get video IDs of existing files
    existing_files = set()
    for file in os.listdir(folder_path):
        if file.endswith(".mp4"):
            video_id = file.split(".")[0]  # Get video ID from filename
            existing_files.add(video_id)

    # Download each video, skipping existing ones
    with YoutubeDL(ydl_opts) as ydl:
        for i, video in enumerate(video_data, 1):
            try:
                video_id = video["video_id"]
                url = video["url"]

                # Skip if video already exists
                if video_id in existing_files:
                    # tqdm.write(
                    #     f"\nSkipping video {i}/{len(video_data)} (already downloaded)"
                    # )
                    continue

                # tqdm.write(f"\nDownloading video {i}/{len(video_data)}")
                ydl.download([url])
            except Exception as e:
                print(f"Error downloading video: {str(e)}")


# Example Usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape TikTok videos from users' profiles"
    )
    parser.add_argument(
        "--type",
        choices=["videos", "liked", "favorite"],
        default="videos",
        help="Type of videos to scrape (default: videos)",
    )
    parser.add_argument(
        "--user",
        help="Single username to process (without @)",
    )
    parser.add_argument(
        "--file",
        default="usernames.md",
        help="File containing usernames (default: usernames.md)",
    )
    args = parser.parse_args()

    if args.user:
        # Process single user
        videos = scrape_user_videos(args.user, args.type)
        if videos:
            # print(f"\nFound {len(videos)} {args.type} videos:")
            # for i, video in enumerate(videos, 1):
            #     print(f"\n{i}. URL: {video['url']}")
            #     print(f"   Published: {video['published_date']}")
            #     print(f"   Description: {video['description'][:100]}...")
            #     if video["tags"]:
            #         print(f"   Tags: {', '.join(video['tags'])}")
            #     print(f"   Likes: {video['likes']}")
            #     print(f"   Duration: {video['duration']}")

            # response = input("\nDo you want to download these videos? (y/n): ").lower()
            # if response == "y":
            folder_name = f"{args.user}_{args.type}"
            download_videos(videos, folder_name)
            # print(
            #     "\nDownload complete! Videos are stored in the 'downloads' folder."
            # )
        # else:
        #     print("\nDownload cancelled.")
        else:
            print(f"No {args.type} videos found for {args.user}")
    else:
        # Process all users from file
        process_all_users(args.file, args.type)
