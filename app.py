from flask import Flask, render_template, jsonify, send_file, Response, request
from flask_cors import CORS
import redis
import os
import jinja2
import html
import json
from pathlib import Path
from threading import Lock
import cv2
from PIL import Image

app = Flask(__name__)
CORS(app)
thumbnail_lock = Lock()

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


def get_thumbnail_path(video_path):
    """Get the thumbnail path for a video without generating it."""
    return video_path.parent / f"{video_path.stem}_thumb.jpg"


def generate_thumbnail(video_path):
    """Generate a thumbnail from a video file."""
    thumbnail_path = get_thumbnail_path(video_path)

    with thumbnail_lock:
        # Check again with lock in case another request just generated it
        if thumbnail_path.exists():
            return True

        try:
            video = cv2.VideoCapture(str(video_path))
            success, frame = video.read()
            if success:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)

                # Set fixed dimensions for TikTok aspect ratio
                width = 320
                height = 568

                # Resize image maintaining aspect ratio and adding black bars
                original_ratio = pil_image.size[0] / pil_image.size[1]
                target_ratio = width / height

                if original_ratio > target_ratio:
                    new_width = width
                    new_height = int(width / original_ratio)
                    resize_size = (new_width, new_height)
                    position = (0, (height - new_height) // 2)
                else:
                    new_height = height
                    new_width = int(height * original_ratio)
                    resize_size = (new_width, new_height)
                    position = ((width - new_width) // 2, 0)

                background = Image.new("RGB", (width, height), (0, 0, 0))
                pil_image = pil_image.resize(resize_size, Image.Resampling.LANCZOS)
                background.paste(pil_image, position)
                background.save(thumbnail_path, "JPEG", quality=85)
                return True
        except Exception as e:
            print(f"Error generating thumbnail for {video_path}: {str(e)}")
            return False
        finally:
            if "video" in locals():
                video.release()


@app.route("/thumbnail/<path:thumbnail_path>")
def serve_thumbnail(thumbnail_path):
    """Serve thumbnail files, generating if needed."""
    full_thumb_path = Path("downloads") / thumbnail_path
    video_path = full_thumb_path.parent / f"{full_thumb_path.stem}.mp4"

    if not full_thumb_path.exists() and video_path.exists():
        if not generate_thumbnail(video_path):
            return Response(status=404)

    if full_thumb_path.exists():
        return send_file(full_thumb_path, mimetype="image/jpeg")
    else:
        return Response(status=404)


@app.route("/video/<path:video_path>")
def serve_video(video_path):
    """Serve video files from the downloads directory."""
    return send_file(Path("downloads") / video_path, mimetype="video/mp4")


@app.route("/check_thumbnail/<path:thumbnail_path>")
def check_thumbnail(thumbnail_path):
    """Check if a thumbnail exists."""
    full_thumb_path = Path("downloads") / thumbnail_path
    return jsonify({"exists": full_thumb_path.exists()})


@app.route("/")
def index():
    """Root route - render the video browser"""
    try:
        # Just render the template with minimal data
        return render_template(
            "index.html",
            filters=[],  # No need to load filters, they'll be fetched as needed
            videos=[],  # No need to load videos, they'll be fetched via AJAX
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


@app.route("/api/videos")
def get_videos():
    try:
        page = int(request.args.get("page", 0))
        per_page = int(request.args.get("per_page", 20))
        sort_order = request.args.get("order", "desc")  # Default newest first

        # Get video IDs from sorted set based on sort order
        start_idx = page * per_page
        end_idx = start_idx + per_page - 1  # Redis ranges are inclusive

        # Get sorted video IDs
        if sort_order == "desc":
            video_ids = redis_client.zrevrange("videos_by_date", start_idx, end_idx)
        else:
            video_ids = redis_client.zrange("videos_by_date", start_idx, end_idx)

        # Get total count
        total_videos = redis_client.zcard("videos_by_date")

        # Fetch video data for the page
        videos = []
        for video_id in video_ids:
            try:
                # Find the metadata key for this video_id
                matching_keys = redis_client.keys(f"metadata:*:{video_id}")
                if not matching_keys:
                    continue

                video_key = matching_keys[0]  # Use the first matching key
                video_data = redis_client.hgetall(video_key)

                if (
                    video_data
                    and video_data.get("deleted") != "True"
                    and video_data.get("file_missing") != "True"
                ):

                    try:
                        tags = json.loads(video_data.get("tags", "[]"))
                    except json.JSONDecodeError:
                        tags = []

                    username = video_data.get("username", "")
                    video = {
                        "video_id": video_data["video_id"],
                        "video_path": f"{username}_videos/{video_data['video_id']}.mp4",
                        "thumbnail_path": f"{username}_videos/{video_data['video_id']}_thumb.jpg",
                        "description": video_data.get("description", ""),
                        "username": username,
                        "tags": tags,
                        "has_thumbnail": True,
                        "author": video_data.get("author", ""),
                        "music": video_data.get("music", ""),
                        "date": (
                            video_data.get("date", "").split("·")[1]
                            if "·" in video_data.get("date", "")
                            else ""
                        ),
                        "url": video_data.get("url", ""),
                    }
                    videos.append(video)
            except Exception as e:
                logger.error(f"Error processing video {video_id}: {e}")
                continue

        return jsonify(
            {
                "videos": videos,
                "total": total_videos,
                "has_more": (start_idx + per_page) < total_videos,
            }
        )

    except Exception as e:
        logger.error(f"Error in get_videos route: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tags/search")
def search_tags():
    try:
        query = request.args.get("q", "").lower()
        if not query:
            return jsonify({"tags": []})

        # Get all tags and filter on the server side
        all_tags = list(redis_client.smembers("all_tags"))
        matching_tags = [tag for tag in all_tags if query in tag.lower()]

        # Limit results to prevent overwhelming the frontend
        return jsonify({"tags": matching_tags[:50]})  # Return top 50 matching tags
    except Exception as e:
        print(f"Error in tag search: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
