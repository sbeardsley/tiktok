import redis
import logging
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cleanup_deleted_videos")


def cleanup_deleted_videos():
    """Remove deleted videos from videos_by_date sorted set."""
    try:
        # Connect to Redis
        redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )

        # Get all video IDs from the sorted set
        all_video_ids = redis_client.zrange("videos_by_date", 0, -1)
        total_videos = len(all_video_ids)
        removed_count = 0

        logger.info(f"Checking {total_videos} videos for deletion status...")

        for video_id in all_video_ids:
            # Find the metadata key for this video_id
            matching_keys = redis_client.keys(f"metadata:*:{video_id}")

            if not matching_keys:
                # If no metadata exists, remove from sorted set
                redis_client.zrem("videos_by_date", video_id)
                removed_count += 1
                logger.info(f"Removed {video_id} - no metadata found")
                continue

            metadata_key = matching_keys[0]
            is_deleted = redis_client.hget(metadata_key, "deleted") == "True"

            if is_deleted:
                # Remove from sorted set if marked as deleted
                redis_client.zrem("videos_by_date", video_id)
                removed_count += 1
                logger.info(f"Removed {video_id} - marked as deleted")

        logger.info(
            f"Cleanup complete. Removed {removed_count} out of {total_videos} videos from videos_by_date"
        )
        return removed_count, total_videos

    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise


if __name__ == "__main__":
    try:
        removed, total = cleanup_deleted_videos()
        print(f"\nCleanup Summary:")
        print(f"Total videos checked: {total}")
        print(f"Videos removed: {removed}")
    except Exception as e:
        print(f"Error: {e}")
