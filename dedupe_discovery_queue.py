import redis
import json
import os

# Connect to Redis
r = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)

# Get all items from queue
queue_items = r.lrange("tiktok_video_queue", 0, -1)

# Track seen video IDs
seen_ids = set()
unique_items = []

# Filter duplicates
for item in queue_items:
    try:
        video_data = json.loads(item)
        video_id = video_data.get("video_id")
        if video_id and video_id not in seen_ids:
            seen_ids.add(video_id)
            unique_items.append(item)
    except json.JSONDecodeError:
        continue

# Clear queue and add unique items
r.delete("tiktok_video_queue")
if unique_items:
    r.rpush("tiktok_video_queue", *unique_items)

print(f"Removed {len(queue_items) - len(unique_items)} duplicates")
