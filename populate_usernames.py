import redis
import os

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)


def populate_usernames():
    try:
        # Get all metadata keys
        metadata_keys = redis_client.keys("metadata:*")
        print(f"Found {len(metadata_keys)} metadata keys")

        # Extract usernames from metadata keys
        usernames = set()
        for key in metadata_keys:
            # Key format is "metadata:username:video_id"
            parts = key.split(":")
            if len(parts) >= 2:
                username = parts[1]
                usernames.add(username)

        # Add usernames to Redis set
        if usernames:
            print(f"Adding {len(usernames)} usernames to Redis")
            redis_client.sadd("all_usernames", *usernames)
            print("Usernames added successfully")
            print("\nSample usernames:")
            for username in list(usernames)[:5]:
                print(f"- {username}")
        else:
            print("No usernames found")

    except Exception as e:
        print(f"Error populating usernames: {e}")


if __name__ == "__main__":
    populate_usernames()
