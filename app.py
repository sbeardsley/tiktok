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
import time
from dateutil import parser
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

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
        sort_order = request.args.get("order", "desc")
        filters = request.args.getlist("filters[]")
        filter_type = request.args.get("filter_type", "and")

        logger.info(
            f"Getting videos - page: {page}, filters: {filters}, type: {filter_type}"
        )

        # Fast path for no filters - use sorted set
        if not filters:
            start_idx = page * per_page
            end_idx = start_idx + per_page

            # Get total count first
            total_videos = redis_client.zcard("videos_by_date")

            # Get video IDs for this page
            if sort_order == "desc":
                video_ids = redis_client.zrevrange(
                    "videos_by_date", start_idx, end_idx - 1
                )
            else:
                video_ids = redis_client.zrange(
                    "videos_by_date", start_idx, end_idx - 1
                )

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
                    "has_more": (end_idx) < total_videos,
                }
            )

        # Filter logic
        # Extract username filter if present
        username_filter = next((f[1:] for f in filters if f.startswith("@")), None)
        tag_filters = [f for f in filters if not f.startswith("@")]

        # Get video keys based on username if present
        if username_filter:
            video_keys = redis_client.keys(f"metadata:{username_filter}:*")
        else:
            # If no username filter, get all video keys
            video_keys = redis_client.keys("metadata:*:*")

        # Get all matching videos with their dates
        video_data_with_dates = []
        for key in video_keys:
            video_data = redis_client.hgetall(key)
            if (
                video_data
                and video_data.get("deleted") != "True"
                and video_data.get("file_missing") != "True"
            ):
                try:
                    # Check if video matches tag filters
                    video_tags = set(json.loads(video_data.get("tags", "[]")))
                    tag_filters_set = set(tag_filters)

                    # Apply tag filters based on filter type
                    if tag_filters:
                        if filter_type == "and":
                            if not tag_filters_set.issubset(video_tags):
                                continue
                        elif filter_type == "or":
                            if not tag_filters_set.intersection(video_tags):
                                continue
                        elif filter_type == "not":
                            if tag_filters_set.intersection(video_tags):
                                continue

                    # If video passes filters, add it to results
                    if video_data.get("date"):
                        timestamp = parse_date_string(video_data["date"])
                    else:
                        timestamp = time.time()
                    video_data_with_dates.append((key, timestamp, video_data))
                except Exception as e:
                    logger.error(f"Error processing date for {key}: {e}")
                    continue

        # Sort all videos by date
        video_data_with_dates.sort(key=lambda x: x[1], reverse=(sort_order == "desc"))

        # Get total count of valid videos
        total_videos = len(video_data_with_dates)

        # Then paginate the sorted results
        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_data = video_data_with_dates[start_idx:end_idx]

        # Format videos for response
        videos = []
        for _, _, video_data in page_data:
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

        return jsonify(
            {
                "videos": videos,
                "total": total_videos,
                "has_more": end_idx < total_videos,
            }
        )

    except Exception as e:
        logger.error(f"Error in get_videos route: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tags/search")
def search_tags():
    try:
        query = request.args.get("q", "").lower()
        logger.info(f"Tag search query: {query}")

        # Get all tags and usernames
        all_tags = list(redis_client.smembers("all_tags"))
        all_usernames = list(redis_client.smembers("all_usernames"))

        logger.info(f"Found {len(all_usernames)} usernames: {all_usernames}")
        logger.info(
            f"Found {len(all_tags)} tags: {all_tags[:5]}..."
        )  # Just show first 5 tags

        # Handle username search (with or without @ symbol)
        clean_query = query.lstrip("@")  # Remove @ if present
        logger.info(f"Clean query: {clean_query}")

        # Filter and format usernames (add @ symbol)
        matching_usernames = []
        if (
            query.startswith("@") or not query
        ):  # Show usernames if searching with @ or empty query
            matching_usernames = [
                f"@{username}"
                for username in all_usernames
                if clean_query in username.lower()
            ]
        logger.info(f"Matching usernames: {matching_usernames}")

        # Filter tags (only if query doesn't start with @)
        matching_tags = []
        if not query.startswith("@"):
            matching_tags = [tag for tag in all_tags if query in tag.lower()]
        logger.info(f"Matching tags: {len(matching_tags)} tags")

        # Combine and sort results (usernames first, then tags)
        results = sorted(matching_usernames) + sorted(matching_tags)

        return jsonify({"tags": results[:50]})  # Return top 50 matching items
    except Exception as e:
        logger.error(f"Error in tag search: {e}")
        return jsonify({"error": str(e)}), 500


def parse_date_string(date_str: str) -> float:
    """Extract timestamp from date string like 'The Cheese Knees·2022-12-13' or 'username·2d ago'"""
    try:
        # Split by '·' and take the last part which should be the date/time
        date_part = date_str.split("·")[-1].strip()

        # Handle relative time formats
        if "ago" in date_part:
            # Extract number and unit
            parts = date_part.split()
            if len(parts) >= 2:
                number = int("".join(filter(str.isdigit, parts[0])))
                unit = parts[0][-1]  # Get last character of first part (d, h, m)

                # Calculate seconds based on unit
                seconds = {
                    "d": 86400,  # days to seconds
                    "h": 3600,  # hours to seconds
                    "m": 60,  # minutes to seconds
                }

                if unit in seconds:
                    return time.time() - (number * seconds[unit])

        # Try parsing as absolute date
        return parser.parse(date_part).timestamp()

    except Exception as e:
        logger.error(f"Error parsing date string '{date_str}': {e}")
        return time.time()  # Return current time as fallback


def store_video_metadata(video_data):
    """Store video metadata in Redis."""
    try:
        username = video_data.get("username")
        video_id = video_data.get("video_id")

        if username and video_id:
            # Store the metadata
            redis_key = f"metadata:{username}:{video_id}"
            redis_client.hmset(redis_key, video_data)

            # Add to videos_by_date sorted set
            if video_data.get("date"):
                timestamp = parse_date_string(video_data["date"])
                redis_client.zadd("videos_by_date", {video_id: timestamp})

            # Store username in all_usernames set
            redis_client.sadd("all_usernames", username)

            # Store tags in all_tags set
            if video_data.get("tags"):
                tags = json.loads(video_data["tags"])
                if tags:
                    redis_client.sadd("all_tags", *tags)

            return True
    except Exception as e:
        logger.error(f"Error storing video metadata: {e}")
        return False


@app.route("/api/metadata/<video_id>", methods=["PUT"])
def update_metadata(video_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Find the metadata key for this video_id
        matching_keys = redis_client.keys(f"metadata:*:{video_id}")
        if not matching_keys:
            return jsonify({"error": "Video not found"}), 404

        metadata_key = matching_keys[0]

        # Update metadata
        redis_client.hmset(metadata_key, data)

        # Add username to all_usernames set if present
        if "username" in data:
            redis_client.sadd("all_usernames", data["username"])

        # Update tags in all_tags set if present
        if "tags" in data:
            tags = json.loads(data["tags"])
            if tags:
                redis_client.sadd("all_tags", *tags)

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating metadata: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/videos", methods=["POST"])
def add_video():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Store metadata
        if store_video_metadata(data):
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Failed to store metadata"}), 500

    except Exception as e:
        logger.error(f"Error adding video: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
