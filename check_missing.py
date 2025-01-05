import redis
import json
from pathlib import Path
import os
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("check_missing.log"), logging.StreamHandler()],
)
logger = logging.getLogger("check_missing")

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)


def parse_date_string(date_str: str) -> float:
    """Extract timestamp from date string like 'The Cheese Knees·2022-12-13' or 'username·2d ago'"""
    try:
        # Split by '·' and take the last part which should be the date/time
        date_part = date_str.split("·")[-1].strip()

        # Handle relative time formats
        if "ago" in date_part:
            # Extract number and unit
            parts = date_part.split()
            if len(parts) >= 2:
                value = parts[0]
                unit = value[-1]  # 'd' for days, 'h' for hours
                number = int(value[:-1])  # number before the unit

                current_time = time.time()
                if unit == "d":
                    return current_time - (number * 86400)  # days to seconds
                elif unit == "h":
                    return current_time - (number * 3600)  # hours to seconds
                else:
                    return current_time

        # Try standard date format
        return time.mktime(time.strptime(date_part, "%Y-%m-%d"))

    except Exception as e:
        logger.error(f"Error parsing date '{date_str}', using current time: {e}")
        # Return current timestamp for any parsing errors
        return time.time()


def check_missing_files():
    """Check for videos marked as not deleted but missing files, and requeue them."""
    # First, let's see what keys exist
    all_keys = redis_client.keys("*")
    print("\nAll Redis keys:")
    for key in all_keys:
        print(f"- {key}")

    # Now check metadata specifically
    video_keys = redis_client.keys("metadata:*")
    print(f"\nFound {len(video_keys)} metadata keys:")
    for key in video_keys[:5]:  # Print first 5 keys as sample
        print(f"- {key}")
        data = redis_client.hgetall(key)
        print(f"  Data: {data}")

    missing_videos = []
    processed = 0

    print(f"\nChecking {len(video_keys)} metadata entries...")

    # Get current queue contents
    queue_contents = []
    queue_length = redis_client.llen("video_download_queue")
    for i in range(queue_length):
        item = redis_client.lindex("video_download_queue", i)
        if item:
            try:
                queue_item = json.loads(item)
                queue_contents.append(queue_item.get("url"))
            except json.JSONDecodeError:
                continue

    for video_key in video_keys:
        try:
            video_data = redis_client.hgetall(video_key)
            if video_data and video_data.get("deleted") != "True":
                username = video_data.get("username", "")
                video_id = video_data.get("video_id", "")

                if username and video_id:
                    video_path = (
                        Path("downloads") / f"{username}_videos" / f"{video_id}.mp4"
                    )

                    if not video_path.exists():
                        # Mark the video as missing in metadata
                        redis_client.hset(video_key, "file_missing", "True")

                        # Remove from sorted set if file is missing
                        redis_client.zrem("videos_by_date", video_id)

                        url = video_data.get("url")
                        if url and url not in queue_contents:
                            missing_videos.append(
                                {
                                    "url": url,
                                    "username": username,
                                    "video_id": video_id,
                                    "date": video_data.get(
                                        "date", ""
                                    ),  # Include date for sorting
                                }
                            )
                    else:
                        # Ensure file_missing is set to False if file exists
                        redis_client.hset(video_key, "file_missing", "False")

                        # Ensure video is in sorted set with correct date
                        if video_data.get("date"):
                            timestamp = parse_date_string(video_data["date"])
                        else:
                            # Use file modification time if no date available
                            timestamp = video_path.stat().st_mtime

                        redis_client.zadd("videos_by_date", {video_id: timestamp})

            processed += 1
            if processed % 1000 == 0:
                print(f"Processed {processed}/{len(video_keys)} entries...")

        except Exception as e:
            print(f"Error processing {video_key}: {e}")
            continue

    print(f"\nFound {len(missing_videos)} missing videos not in queue")

    # Add missing videos back to download queue
    if missing_videos:
        for video in missing_videos:
            try:
                redis_client.rpush("video_download_queue", json.dumps(video))
                print(f"Requeued: {video['url']}")
            except Exception as e:
                print(f"Error queuing {video['url']}: {e}")

    print(f"\nRequeued {len(missing_videos)} videos for download")


if __name__ == "__main__":
    check_missing_files()
