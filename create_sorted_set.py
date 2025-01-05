import redis
import os
import json
from datetime import datetime
import time
from tqdm import tqdm

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)


def parse_date(date_str):
    try:
        if "·" in date_str:
            date_str = date_str.split("·")[1].strip()
        return datetime.strptime(date_str, "%Y-%m-%d").timestamp()
    except:
        return time.time()


def fix_paths_and_create_sorted_set():
    # Step 1: Create all_videos from metadata
    print("Creating all_videos set from metadata...")
    pipe = redis_client.pipeline()
    pipe.delete("all_videos")  # Clear existing set

    videos_added = 0
    fixed_paths = set()

    # Get all metadata keys
    metadata_keys = redis_client.keys("metadata:*")
    print(f"Found {len(metadata_keys)} metadata entries")

    # First pass: collect all valid video paths
    for key in tqdm(metadata_keys, desc="Processing metadata"):
        video_data = redis_client.hgetall(key)

        # Skip deleted or missing videos
        if (
            video_data.get("deleted") == "True"
            or video_data.get("file_missing") == "True"
        ):
            continue

        # Get video path from metadata
        video_path = video_data.get("video_path")
        if video_path:
            fixed_paths.add(video_path)
            videos_added += 1

    # Add all valid paths to all_videos
    if fixed_paths:
        pipe.sadd("all_videos", *fixed_paths)

    # Step 2: Create sorted set of videos by date
    print("\nCreating sorted set of videos by date...")
    pipe.delete("videos_by_date")  # Clear existing sorted set

    for key in tqdm(metadata_keys, desc="Processing videos"):
        video_data = redis_client.hgetall(key)

        # Skip deleted or missing videos
        if (
            video_data.get("deleted") == "True"
            or video_data.get("file_missing") == "True"
        ):
            continue

        # Get video ID and date
        video_id = video_data.get("video_id")
        if not video_id:
            continue

        # Try to get timestamp from scrape_time first
        timestamp = None
        if "scrape_time" in video_data:
            try:
                timestamp = datetime.strptime(
                    video_data["scrape_time"], "%Y-%m-%d %H:%M:%S"
                ).timestamp()
            except:
                pass

        # Fall back to date field if scrape_time failed
        if not timestamp and "date" in video_data:
            timestamp = parse_date(video_data["date"])

        if not timestamp:
            timestamp = time.time()

        # Add to sorted set
        pipe.zadd("videos_by_date", {video_id: timestamp})

    # Execute all commands
    pipe.execute()


if __name__ == "__main__":
    fix_paths_and_create_sorted_set()
