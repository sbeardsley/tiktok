import redis
import datetime

# Connect to Redis
r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# Get the first 10 entries from videos_by_date
videos = r.zrevrange("videos_by_date", 0, 9, withscores=True)

# Print each entry with human-readable date
for video_id, timestamp in videos:
    date = datetime.datetime.fromtimestamp(timestamp)
    print(f"Video ID: {video_id}")
    print(f"Date: {date.strftime('%Y-%m-%d %H:%M:%S')}")
    print("---")
