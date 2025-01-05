import redis
import os
from tqdm import tqdm

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)


def fix_video_paths():
    try:
        # Get all video IDs
        video_ids = redis_client.smembers("all_videos")
        print(f"Found {len(video_ids)} videos to fix")

        # Create a pipe for batch operations
        pipe = redis_client.pipeline()

        # First, remove all old video IDs
        pipe.delete("all_videos")

        fixed_paths = set()

        # For each video ID, find its metadata and construct proper path
        for video_id in tqdm(video_ids, desc="Fixing video paths"):
            # Search for metadata keys containing this video ID
            metadata_keys = redis_client.keys(f"metadata:*:{video_id}")

            for metadata_key in metadata_keys:
                # Extract username from metadata key (format: metadata:username:video_id)
                parts = metadata_key.split(":")
                if len(parts) == 3:
                    username = parts[1]
                    # Construct proper path
                    proper_path = f"{username}/{video_id}.mp4"
                    fixed_paths.add(proper_path)

        # Add all fixed paths back to Redis
        if fixed_paths:
            pipe.sadd("all_videos", *fixed_paths)

        # Execute all commands
        pipe.execute()

        print(f"Fixed {len(fixed_paths)} video paths")
        print("\nSample fixed paths:")
        for path in list(fixed_paths)[:5]:
            print(f"- {path}")

    except Exception as e:
        print(f"Error fixing video paths: {e}")


if __name__ == "__main__":
    fix_video_paths()
