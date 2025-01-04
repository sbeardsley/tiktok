import json
from pathlib import Path
import redis
import logging
from typing import Dict, Set
import os
from tqdm import tqdm

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("migration.log"), logging.StreamHandler()],
)
logger = logging.getLogger("migration")


class MetadataMigration:
    def __init__(self):
        self.downloads_dir = Path("downloads")
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )

    def get_all_metadata_files(self) -> list[Path]:
        """Get all metadata.json files in the downloads directory."""
        return list(self.downloads_dir.rglob("metadata.json"))

    def process_metadata_file(self, file_path: Path) -> tuple[int, int]:
        """Process a single metadata.json file.
        Returns (success_count, error_count)"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                metadata_list = json.load(f)

            # Get username from directory name
            username = file_path.parent.name.replace("_videos", "")

            success_count = 0
            error_count = 0

            for video_data in metadata_list:
                try:
                    # Ensure required fields exist
                    video_id = video_data.get("video_id")
                    if not video_id:
                        logger.error(f"Missing video_id in {file_path}")
                        error_count += 1
                        continue

                    # Add username if not present
                    video_data["username"] = username

                    # Ensure deleted flag exists
                    if "deleted" not in video_data:
                        video_data["deleted"] = False

                    # Store in Redis
                    redis_key = f"metadata:{username}:{video_id}"
                    self.redis_client.hset(redis_key, mapping=video_data)

                    # Add to user's video list and global video list only if not deleted
                    if not video_data.get("deleted", False):
                        user_videos_key = f"user_videos:{username}"
                        self.redis_client.sadd(user_videos_key, video_id)
                        self.redis_client.sadd("all_videos", video_id)

                        # Update tags index only for non-deleted videos
                        if "tags" in video_data:
                            for tag in video_data["tags"]:
                                tag = tag.lower()  # Normalize tags to lowercase
                                self.redis_client.sadd(f"tag:{tag}", video_id)
                                self.redis_client.sadd("all_tags", tag)
                    else:
                        # Add to deleted videos set
                        self.redis_client.sadd("deleted_videos", video_id)

                    success_count += 1

                except Exception as e:
                    logger.error(f"Error processing video {video_id}: {e}")
                    error_count += 1

            return success_count, error_count

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return 0, 1

    def verify_migration(self) -> Dict:
        """Verify migration results."""
        stats = {
            "total_videos": len(self.redis_client.smembers("all_videos")),
            "deleted_videos": len(self.redis_client.smembers("deleted_videos")),
            "total_users": len(list(self.redis_client.scan_iter("user_videos:*"))),
            "total_tags": len(self.redis_client.smembers("all_tags")),
            "videos_by_user": {},
            "videos_by_tag": {},
        }

        # Count videos per user
        for user_key in self.redis_client.scan_iter("user_videos:*"):
            username = user_key.split(":")[-1]
            video_count = self.redis_client.scard(user_key)
            stats["videos_by_user"][username] = video_count

        # Count videos per tag
        for tag in self.redis_client.smembers("all_tags"):
            video_count = self.redis_client.scard(f"tag:{tag}")
            stats["videos_by_tag"][tag] = video_count

        return stats

    def run_migration(self):
        """Run the full migration process."""
        logger.info("Starting migration to Redis")

        # Get all metadata files
        metadata_files = self.get_all_metadata_files()
        logger.info(f"Found {len(metadata_files)} metadata files to process")

        total_success = 0
        total_errors = 0

        # Process each file with progress bar
        for file_path in tqdm(metadata_files, desc="Migrating metadata files"):
            success, errors = self.process_metadata_file(file_path)
            total_success += success
            total_errors += errors

        logger.info(f"Migration complete!")
        logger.info(f"Successfully migrated {total_success} videos")
        logger.info(f"Encountered {total_errors} errors")

        # Verify migration
        stats = self.verify_migration()
        logger.info("Migration verification results:")
        logger.info(f"Total videos in Redis: {stats['total_videos']}")
        logger.info(f"Total users in Redis: {stats['total_users']}")
        logger.info(f"Total tags in Redis: {stats['total_tags']}")

        return stats


def main():
    migration = MetadataMigration()

    # Confirm with user
    response = input("This will migrate all metadata to Redis. Continue? (y/n): ")
    if response.lower() != "y":
        print("Migration cancelled")
        return

    # Run migration
    stats = migration.run_migration()

    # Print summary
    print("\nMigration Summary:")
    print(f"Total videos: {stats['total_videos']}")
    print(f"Total users: {stats['total_users']}")
    print(f"Total tags: {stats['total_tags']}")
    print("\nVideos by user:")
    for username, count in stats["videos_by_user"].items():
        print(f"  {username}: {count}")
    print("\nMost used tags:")
    # Show top 10 tags by video count
    top_tags = sorted(stats["videos_by_tag"].items(), key=lambda x: x[1], reverse=True)[
        :10
    ]
    for tag, count in top_tags:
        print(f"  {tag}: {count}")


if __name__ == "__main__":
    main()
