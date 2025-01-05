from flask import Flask, render_template, jsonify
from flask_cors import CORS
import redis
import os
import jinja2
import html
import json

app = Flask(__name__)
CORS(app)

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)


# Create a function to read JS files
def read_js_file(filename):
    try:
        with open(os.path.join(app.static_folder, filename), "r") as f:
            # Use html.unescape to handle any HTML entities in the JavaScript
            return html.unescape(f.read())
    except FileNotFoundError:
        return "// File not found: " + filename


# Register the template filter properly
app.jinja_env.globals["include_file"] = read_js_file

# Mark the JavaScript as safe to prevent auto-escaping
app.jinja_env.filters["js_escape"] = lambda x: jinja2.Markup(x)


@app.route("/")
def index():
    """Root route - render the video browser"""
    try:
        # Get all available tags
        all_tags = (
            list(redis_client.smembers("all_tags"))
            if redis_client.exists("all_tags")
            else []
        )

        # Get video metadata using the 'metadata:' prefix
        all_videos = []
        video_keys = redis_client.keys("metadata:*")

        print(f"Found {len(video_keys)} video metadata keys")

        for video_key in video_keys[
            :30
        ]:  # Limit to 30 videos initially for performance
            try:
                video_data = redis_client.hgetall(video_key)
                if (
                    video_data
                    and "video_id" in video_data
                    and video_data.get("deleted") != "True"
                ):
                    # Parse tags from JSON string
                    try:
                        tags = json.loads(video_data.get("tags", "[]"))
                    except json.JSONDecodeError:
                        tags = []

                    video = {
                        "video_id": video_data["video_id"],
                        "video_path": f"videos/{video_data['video_id']}.mp4",  # Remove leading slash
                        "thumbnail_path": f"thumbnails/{video_data['video_id']}.jpg",  # Remove leading slash
                        "description": video_data.get("description", ""),
                        "username": video_data.get("username", ""),
                        "tags": tags,
                        "has_thumbnail": True,  # We'll assume thumbnails exist for non-deleted videos
                        "author": video_data.get("author", ""),
                        "music": video_data.get("music", ""),
                        "date": (
                            video_data.get("date", "").split("·")[1]
                            if "·" in video_data.get("date", "")
                            else ""
                        ),
                        "url": video_data.get("url", ""),
                    }
                    all_videos.append(video)
            except Exception as e:
                print(f"Error processing video {video_key}: {e}")
                continue

        print(f"Successfully processed {len(all_videos)} videos")
        if all_videos:
            print("Sample video:", all_videos[0])

        return render_template(
            "index.html",
            filters=all_tags,
            videos=[v for v in all_videos if not v.get("deleted")],
        )
    except Exception as e:
        print(f"Error in index route: {e}")
        import traceback

        traceback.print_exc()
        return render_template("index.html", filters=[], videos=[])


@app.route("/queue")
def queue():
    """Queue status dashboard route"""
    try:
        redis_status = redis_client.ping()
        status_data = {
            "status": "running",
            "redis_connected": redis_status,
            "services": {
                "url_discovery": bool(redis_client.get("url_discovery_running")),
                "metadata": len(redis_client.smembers("metadata_processing")),
                "downloader": len(redis_client.smembers("download_processing")),
            },
            "queues": {
                "videos_to_process": redis_client.llen("tiktok_video_queue"),
                "videos_to_download": redis_client.llen("video_download_queue"),
                "failed_metadata": redis_client.llen("metadata_failed_queue"),
                "failed_downloads": redis_client.llen("download_failed_queue"),
            },
        }
    except Exception as e:
        print(f"Error in queue route: {e}")  # Add logging
        status_data = {
            "status": "error",
            "redis_connected": False,
            "services": {"url_discovery": False, "metadata": 0, "downloader": 0},
            "queues": {
                "videos_to_process": 0,
                "videos_to_download": 0,
                "failed_metadata": 0,
                "failed_downloads": 0,
            },
        }

    return render_template("queue.html", data=status_data)


@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})


@app.route("/debug")
def debug():
    """Debug route to inspect Redis data"""
    try:
        # Get all keys but limit the output
        all_keys = redis_client.keys("*")
        key_patterns = {}

        video_key = redis_client.keys("metadata:*")[0]  # Get first metadata key
        print(redis_client.hgetall(video_key))

        # Group keys by pattern
        for key in all_keys:
            pattern = key.split(":")[0] if ":" in key else key
            if pattern not in key_patterns:
                key_patterns[pattern] = 0
            key_patterns[pattern] += 1

        # Get sample data for specific key types we're interested in
        data = {
            "total_keys": len(all_keys),
            "key_patterns": key_patterns,
            "video_queue_length": (
                redis_client.llen("tiktok_video_queue")
                if redis_client.exists("tiktok_video_queue")
                else 0
            ),
            "all_tags_count": (
                redis_client.scard("all_tags") if redis_client.exists("all_tags") else 0
            ),
            "all_usernames_count": (
                redis_client.scard("all_usernames")
                if redis_client.exists("all_usernames")
                else 0
            ),
        }

        # Try to get one sample video if it exists
        if redis_client.exists("tiktok_video_queue"):
            sample_video = redis_client.lindex("tiktok_video_queue", 0)
            if sample_video:
                try:
                    data["sample_video"] = json.loads(sample_video)
                except:
                    data["sample_video"] = "Error decoding video JSON"

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
