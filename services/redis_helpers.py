import json
from typing import List, Dict
import redis
from pathlib import Path


def get_all_videos(redis_client, username=None):
    """Get all videos for a user or all users."""
    if username:
        video_ids = redis_client.smembers(f"user_videos:{username}")
    else:
        video_ids = redis_client.smembers("all_videos")

    videos = []
    for video_id in video_ids:
        for key in redis_client.scan_iter(f"metadata:*:{video_id}"):
            video_data = redis_client.hgetall(key)
            videos.append(video_data)

    return videos


def get_videos_by_tag(redis_client, tag):
    """Get all videos with a specific tag."""
    video_ids = redis_client.smembers(f"tag:{tag}")
    videos = []
    for video_id in video_ids:
        for key in redis_client.scan_iter(f"metadata:*:{video_id}"):
            video_data = redis_client.hgetall(key)
            videos.append(video_data)
    return videos


def get_all_tags(redis_client):
    """Get all known tags."""
    return list(redis_client.smembers("all_tags"))


def delete_video_files(video_path: str, thumbnail_path: str) -> tuple[bool, str]:
    """Delete physical video and thumbnail files.

    Returns:
        tuple[bool, str]: (success, error_message)
    """
    try:
        if video_path:
            video_file = Path("downloads") / video_path
            if video_file.exists():
                video_file.unlink()

        if thumbnail_path:
            thumbnail_file = Path("downloads") / thumbnail_path
            if thumbnail_file.exists():
                thumbnail_file.unlink()

        return True, ""
    except Exception as e:
        return False, str(e)


def delete_videos(redis_client, videos_to_delete: List[Dict]) -> List[Dict]:
    """Delete multiple videos from Redis and filesystem."""
    results = []

    for video in videos_to_delete:
        video_id = video.get("video_id")
        username = video.get("username")
        video_path = video.get("video_path")
        thumbnail_path = video.get("thumbnail_path")

        if not video_id or not username:
            results.append(
                {
                    "video_id": video_id,
                    "success": False,
                    "error": "Missing video ID or username",
                }
            )
            continue

        try:
            # Mark as deleted in Redis
            redis_key = f"metadata:{username}:{video_id}"
            if redis_client.exists(redis_key):
                redis_client.hset(redis_key, "deleted", "true")

                # Remove from active sets
                redis_client.srem("all_videos", video_id)
                redis_client.srem(f"user_videos:{username}", video_id)
                redis_client.sadd("deleted_videos", video_id)

                # Remove from tag sets
                tags = redis_client.hget(redis_key, "tags")
                if tags:
                    tags = json.loads(tags)
                    for tag in tags:
                        redis_client.srem(f"tag:{tag}", video_id)

                # Delete physical files
                success, error = delete_video_files(video_path, thumbnail_path)
                if not success:
                    results.append(
                        {
                            "video_id": video_id,
                            "success": False,
                            "error": f"Redis updated but file deletion failed: {error}",
                        }
                    )
                    continue

                results.append({"video_id": video_id, "success": True})
            else:
                results.append(
                    {
                        "video_id": video_id,
                        "success": False,
                        "error": "Video not found in Redis",
                    }
                )

        except Exception as e:
            results.append({"video_id": video_id, "success": False, "error": str(e)})

    return results


def add_tags_to_videos(redis_client, video_ids: List[str], new_tag: str) -> bool:
    """Add a tag to multiple videos.

    Args:
        redis_client: Redis connection
        video_ids: List of video IDs to tag
        new_tag: Tag to add (will be converted to lowercase)

    Returns:
        bool: Success status
    """
    try:
        new_tag = new_tag.lower()

        for video_id in video_ids:
            # Find the video in Redis
            for key in redis_client.scan_iter(f"metadata:*:{video_id}"):
                # Get existing tags
                tags = redis_client.hget(key, "tags")
                if tags:
                    tags = json.loads(tags)
                else:
                    tags = []

                # Add new tag if not present
                if new_tag not in tags:
                    tags.append(new_tag)
                    # Update tags in Redis
                    redis_client.hset(key, "tags", json.dumps(tags))
                    # Add to tag set
                    redis_client.sadd(f"tag:{new_tag}", video_id)
                    redis_client.sadd("all_tags", new_tag)

        return True

    except Exception as e:
        print(f"Error adding tags: {e}")  # Consider using proper logging
        return False
