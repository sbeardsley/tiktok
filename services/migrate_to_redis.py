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
        success_count = 0
        error_count = 0

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Check if metadata is a dictionary (single video) or list (multiple videos)
            if isinstance(metadata, dict):
                metadata_list = [metadata]
            elif isinstance(metadata, list):
                metadata_list = metadata
            else:
                logger.error(f"Invalid metadata format in {file_path}")
                return 0, 1

            # Get username from directory name
            username = file_path.parent.name.replace("_videos", "")

            # Debug log
            logger.info(f"Processing {len(metadata_list)} videos from {file_path}")

            for video_data in metadata_list:
                video_id = None
                try:
                    # Check for video_id in different possible fields
                    video_id = str(
                        video_data.get("id")
                        or video_data.get("video_id")
                        or video_data.get("aweme_id")
                    )

                    if not video_id:
                        logger.error(
                            f"Missing video ID in {file_path}. Data: {json.dumps(video_data)[:200]}..."
                        )
                        error_count += 1
                        continue

                    # Convert lists to JSON strings before storing
                    processed_data = {}
                    for key, value in video_data.items():
                        if isinstance(value, (list, dict)):
                            processed_data[key] = json.dumps(value)
                        else:
                            processed_data[key] = str(
                                value
                            )  # Convert all values to strings

                    # Add username to the data
                    processed_data["username"] = username

                    # Store in Redis
                    redis_key = f"metadata:{username}:{video_id}"
                    self.redis_client.hset(redis_key, mapping=processed_data)

                    # Add to sets
                    self.redis_client.sadd("all_videos", video_id)
                    self.redis_client.sadd(f"user_videos:{username}", video_id)
                    self.redis_client.sadd("usernames", username)

                    # Handle tags if present
                    tags = []
                    if "tags" in video_data:
                        tags = (
                            video_data["tags"]
                            if isinstance(video_data["tags"], list)
                            else json.loads(video_data["tags"])
                        )
                    elif "hashtags" in video_data:
                        tags = video_data["hashtags"]

                    if tags:
                        for tag in tags:
                            if isinstance(tag, dict) and "name" in tag:
                                tag = tag["name"]
                            tag = str(tag).lower().strip()  # Normalize tags
                            if tag:  # Only add non-empty tags
                                self.redis_client.sadd(f"tag:{tag}", video_id)
                                self.redis_client.sadd("all_tags", tag)

                    success_count += 1

                except Exception as e:
                    error_msg = f"Error processing video {video_id if video_id else 'unknown'} in {file_path}: {e}"
                    logger.error(error_msg)
                    error_count += 1

            return success_count, error_count

        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return success_count, error_count + 1

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

    def load_usernames_from_file(self):
        """Load usernames from usernames.md file."""
        try:
            with open("usernames.md", "r", encoding="utf-8") as f:
                usernames = [line.strip() for line in f if line.strip()]

            logger.info(f"Found {len(usernames)} usernames in usernames.md")

            # Add all usernames to Redis set
            if usernames:
                self.redis_client.sadd("usernames", *usernames)

            return len(usernames)
        except Exception as e:
            logger.error(f"Error loading usernames from file: {e}")
            return 0

    def migrate(self):
        """Run the migration process."""
        try:
            logger.info("Starting migration process...")

            # First load usernames from file
            username_count = self.load_usernames_from_file()
            logger.info(f"Loaded {username_count} usernames from file")

            # Then process metadata files
            metadata_files = list(Path("downloads").glob("**/metadata.json"))
            logger.info(f"Found {len(metadata_files)} metadata files to process")

            total_success = 0
            total_errors = 0

            with tqdm(metadata_files) as pbar:
                for file_path in pbar:
                    success, errors = self.process_metadata_file(file_path)
                    total_success += success
                    total_errors += errors
                    pbar.set_description(
                        f"Success: {total_success}, Errors: {total_errors}"
                    )

            logger.info("Migration complete!")
            logger.info(f"Total videos migrated: {total_success}")
            logger.info(f"Total errors: {total_errors}")

            # Log final stats
            logger.info(
                f"Total usernames in Redis: {self.redis_client.scard('usernames')}"
            )
            logger.info(
                f"Total videos in Redis: {self.redis_client.scard('all_videos')}"
            )
            logger.info(f"Total tags in Redis: {self.redis_client.scard('all_tags')}")

        except Exception as e:
            logger.error(f"Migration failed: {e}")

    def print_summary(self):
        """Print migration summary."""
        print("\nMigration Summary:")
        print(f"Total videos: {self.redis_client.scard('all_videos')}")
        print(f"Total users: {self.redis_client.scard('usernames')}")
        print(f"Total tags: {self.redis_client.scard('all_tags')}")

        print("\nVideos by user:")
        # Fix: scan_iter only returns keys, we need to get the counts separately
        for key in self.redis_client.scan_iter("user_videos:*"):
            username = key.split(":")[-1]  # Extract username from key
            video_count = self.redis_client.scard(key)
            print(f"  @{username}: {video_count}")

        print("\nMost used tags:")
        tag_counts = []
        for tag_key in self.redis_client.scan_iter("tag:*"):
            tag = tag_key.split(":")[-1]
            count = self.redis_client.scard(tag_key)
            tag_counts.append((tag, count))

        # Show top 10 tags
        for tag, count in sorted(tag_counts, key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {tag}: {count}")


def main():
    migration = MetadataMigration()

    # Confirm with user
    response = input("This will migrate all metadata to Redis. Continue? (y/n): ")
    if response.lower() != "y":
        print("Migration cancelled")
        return

    # Run migration
    migration.migrate()

    # Print summary
    migration.print_summary()


if __name__ == "__main__":
    main()
