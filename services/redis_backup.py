import redis
import json
from pathlib import Path
import logging
from datetime import datetime
import os
from tqdm import tqdm
import gzip
import shutil

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("redis_backup.log"), logging.StreamHandler()],
)
logger = logging.getLogger("redis_backup")


class RedisBackupManager:
    def __init__(self):
        self.redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=6379,
            db=0,
            decode_responses=True,
        )
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)

    def create_backup(self, compress=True):
        """Create a backup of all Redis data."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_data = {
            "metadata": {},
            "sets": {
                "all_videos": list(self.redis_client.smembers("all_videos")),
                "deleted_videos": list(self.redis_client.smembers("deleted_videos")),
                "all_tags": list(self.redis_client.smembers("all_tags")),
                "all_usernames": list(self.redis_client.smembers("all_usernames")),
            },
            "sorted_sets": {
                "videos_by_date": [
                    {"member": member, "score": score}
                    for member, score in self.redis_client.zrange(
                        "videos_by_date", 0, -1, withscores=True
                    )
                ],
                # Add any other sorted sets here with the same pattern
            },
            "queues": {
                "tiktok_video_queue": list(
                    self.redis_client.lrange("tiktok_video_queue", 0, -1)
                ),
                "video_download_queue": list(
                    self.redis_client.lrange("video_download_queue", 0, -1)
                ),
                "metadata_failed_queue": list(
                    self.redis_client.lrange("metadata_failed_queue", 0, -1)
                ),
                "download_failed_queue": list(
                    self.redis_client.lrange("download_failed_queue", 0, -1)
                ),
            },
            "processing": {
                "metadata_processing": list(
                    self.redis_client.smembers("metadata_processing")
                ),
                "download_processing": list(
                    self.redis_client.smembers("download_processing")
                ),
            },
            "user_videos": {},
            "tag_videos": {},
            "timestamp": timestamp,
        }

        logger.info("Starting Redis backup...")

        # Backup all metadata
        metadata_keys = list(self.redis_client.scan_iter("metadata:*"))
        for key in tqdm(metadata_keys, desc="Backing up metadata"):
            backup_data["metadata"][key] = self.redis_client.hgetall(key)

        # Backup user video sets
        user_video_keys = list(self.redis_client.scan_iter("user_videos:*"))
        for key in tqdm(user_video_keys, desc="Backing up user videos"):
            backup_data["user_videos"][key] = list(self.redis_client.smembers(key))

        # Backup tag sets
        tag_keys = list(self.redis_client.scan_iter("tag:*"))
        for key in tqdm(tag_keys, desc="Backing up tags"):
            backup_data["tag_videos"][key] = list(self.redis_client.smembers(key))

        # Save backup
        backup_file = self.backup_dir / f"redis_backup_{timestamp}.json"

        if compress:
            backup_file = backup_file.with_suffix(".json.gz")
            with gzip.open(backup_file, "wt", encoding="utf-8") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)
        else:
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Backup completed: {backup_file}")
        return backup_file

    def restore_backup(
        self,
        backup_file: str or Path,
        clear_existing=False,
        restore_failed=False,
        restore_processing=False,
    ):
        """
        Restore Redis data from a backup file.

        Args:
            backup_file: Path to backup file
            clear_existing: Whether to clear existing Redis data
            restore_failed: Whether to restore failed queues
            restore_processing: Whether to restore processing sets
        """
        backup_file = Path(backup_file)
        if not backup_file.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_file}")

        logger.info(f"Starting restore from: {backup_file}")

        # Load backup data
        try:
            if backup_file.suffix == ".gz":
                with gzip.open(backup_file, "rt", encoding="utf-8") as f:
                    backup_data = json.load(f)
            else:
                with open(backup_file, "r", encoding="utf-8") as f:
                    backup_data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading backup file: {e}")
            raise

        try:
            if clear_existing:
                logger.info("Clearing existing Redis data...")
                self.redis_client.flushdb()

            # Restore metadata
            for key, data in tqdm(
                backup_data["metadata"].items(), desc="Restoring metadata"
            ):
                if data:  # Only restore if there's data
                    self.redis_client.hset(key, mapping=data)

            # Restore sets
            for key, members in tqdm(
                backup_data["sets"].items(), desc="Restoring sets"
            ):
                if members:  # Only restore if there are members
                    self.redis_client.sadd(key, *members)

            # Restore sorted sets
            if "sorted_sets" in backup_data:
                for set_name, items in tqdm(
                    backup_data["sorted_sets"].items(), desc="Restoring sorted sets"
                ):
                    if items:
                        # Delete existing sorted set
                        self.redis_client.delete(set_name)
                        # Add all members with their scores
                        for item in items:
                            self.redis_client.zadd(
                                set_name, {item["member"]: item["score"]}
                            )
                        logger.info(
                            f"Restored sorted set {set_name} with {len(items)} items"
                        )

            # Restore queues
            if "queues" in backup_data:
                for queue_name, items in tqdm(
                    backup_data["queues"].items(), desc="Restoring queues"
                ):
                    # Skip failed queues if not requested
                    if not restore_failed and queue_name.endswith("_failed_queue"):
                        logger.info(f"Skipping failed queue: {queue_name}")
                        continue

                    if items:
                        self.redis_client.rpush(queue_name, *items)
                        logger.info(
                            f"Restored queue {queue_name} with {len(items)} items"
                        )

            # Restore processing sets
            if restore_processing and "processing" in backup_data:
                for set_name, items in tqdm(
                    backup_data["processing"].items(), desc="Restoring processing sets"
                ):
                    if items:
                        self.redis_client.sadd(set_name, *items)
                        logger.info(
                            f"Restored processing set {set_name} with {len(items)} items"
                        )
            elif "processing" in backup_data:
                logger.info("Skipping processing sets as requested")

            # Restore user videos
            for key, members in tqdm(
                backup_data["user_videos"].items(), desc="Restoring user videos"
            ):
                if members:
                    self.redis_client.sadd(key, *members)

            # Restore tag videos
            for key, members in tqdm(
                backup_data["tag_videos"].items(), desc="Restoring tag videos"
            ):
                if members:
                    self.redis_client.sadd(key, *members)

            logger.info("Restore completed successfully")

        except Exception as e:
            logger.error(f"Error during restore: {e}")
            raise

    def list_backups(self):
        """List all available backups."""
        backups = []
        for file in self.backup_dir.glob("redis_backup_*.json*"):
            size = file.stat().st_size
            modified = datetime.fromtimestamp(file.stat().st_mtime)
            backups.append({"file": file.name, "size": size, "modified": modified})
        return sorted(backups, key=lambda x: x["modified"], reverse=True)

    def cleanup_old_backups(self, keep_last_n=5):
        """Remove old backups, keeping the n most recent ones."""
        backups = self.list_backups()
        if len(backups) > keep_last_n:
            for backup in backups[keep_last_n:]:
                try:
                    (self.backup_dir / backup["file"]).unlink()
                    logger.info(f"Removed old backup: {backup['file']}")
                except Exception as e:
                    logger.error(f"Error removing backup {backup['file']}: {e}")


def main():
    backup_manager = RedisBackupManager()

    while True:
        print("\nRedis Backup Manager")
        print("1. Create backup")
        print("2. Restore from backup")
        print("3. List backups")
        print("4. Cleanup old backups")
        print("5. Exit")

        choice = input("\nEnter choice (1-5): ")

        try:
            if choice == "1":
                compress = input("Compress backup? (y/n): ").lower() == "y"
                backup_file = backup_manager.create_backup(compress=compress)
                print(f"\nBackup created: {backup_file}")

            elif choice == "2":
                backups = backup_manager.list_backups()
                if not backups:
                    print("No backups found!")
                    continue

                print("\nAvailable backups:")
                for i, backup in enumerate(backups, 1):
                    print(f"{i}. {backup['file']} ({backup['modified']})")

                idx = int(input("\nEnter backup number to restore: ")) - 1
                if 0 <= idx < len(backups):
                    clear = (
                        input("Clear existing data before restore? (y/n): ").lower()
                        == "y"
                    )
                    restore_failed = (
                        input("Restore failed queues? (y/n): ").lower() == "y"
                    )
                    restore_processing = (
                        input("Restore processing sets? (y/n): ").lower() == "y"
                    )

                    backup_manager.restore_backup(
                        backup_manager.backup_dir / backups[idx]["file"],
                        clear_existing=clear,
                        restore_failed=restore_failed,
                        restore_processing=restore_processing,
                    )
                    print("Restore completed!")
                else:
                    print("Invalid backup number!")

            elif choice == "3":
                backups = backup_manager.list_backups()
                if not backups:
                    print("No backups found!")
                else:
                    print("\nAvailable backups:")
                    for backup in backups:
                        size_mb = backup["size"] / (1024 * 1024)
                        print(f"{backup['file']}")
                        print(f"  Size: {size_mb:.2f} MB")
                        print(f"  Modified: {backup['modified']}")

            elif choice == "4":
                keep = int(input("Number of backups to keep: "))
                backup_manager.cleanup_old_backups(keep_last_n=keep)
                print("Cleanup completed!")

            elif choice == "5":
                break

        except Exception as e:
            print(f"Error: {e}")
            logger.error(f"Error in main menu: {e}")


if __name__ == "__main__":
    main()
