from flask import Flask, render_template, jsonify, send_file, Response, request
from pathlib import Path
import redis
import json
import os
import cv2
from PIL import Image
import io
from threading import Lock
from services.redis_helpers import (
    get_all_videos,
    get_videos_by_tag,
    get_all_tags,
    delete_videos,
    add_tags_to_videos,
)

app = Flask(__name__)
thumbnail_lock = Lock()

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"), port=6379, db=0, decode_responses=True
)


def get_thumbnail_path(video_path):
    """Get the thumbnail path for a video without generating it."""
    return video_path.parent / f"{video_path.stem}_thumb.jpg"


def load_all_metadata():
    """Load metadata from Redis."""
    all_videos = get_all_videos(redis_client)
    all_tags = set()
    usernames = set()

    # Filter out deleted videos and collect tags and usernames
    active_videos = []
    for video in all_videos:
        if not video.get("deleted", False):
            # Check if video file exists
            video_path = Path("downloads") / video.get("video_path", "")
            if video_path.exists():
                # Check thumbnail
                thumb_path = Path("downloads") / video.get("thumbnail_path", "")
                video["has_thumbnail"] = thumb_path.exists()

                # Add username
                if "username" in video:
                    usernames.add(f"@{video['username']}")

                # Add tags
                if "tags" in video:
                    all_tags.update(video["tags"])

                active_videos.append(video)

    # Combine usernames and tags
    all_filters = sorted(list(usernames)) + sorted(list(all_tags))

    return active_videos, all_filters


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
    video_path = (
        full_thumb_path.parent / f"{full_thumb_path.stem.replace('_thumb', '')}.mp4"
    )

    if not full_thumb_path.exists() and video_path.exists():
        if not generate_thumbnail(video_path):
            return Response(status=404)

    if full_thumb_path.exists():
        return send_file(full_thumb_path, mimetype="image/jpeg")
    else:
        return Response(status=404)


@app.route("/check_thumbnail/<path:thumbnail_path>")
def check_thumbnail(thumbnail_path):
    """Check if a thumbnail exists."""
    full_thumb_path = Path("downloads") / thumbnail_path
    return jsonify({"exists": full_thumb_path.exists()})


@app.route("/")
def index():
    videos, filters = load_all_metadata()
    return render_template("index.html", videos=videos, filters=filters)


@app.route("/video/<path:video_path>")
def serve_video(video_path):
    """Serve video files from the downloads directory."""
    return send_file(Path("downloads") / video_path, mimetype="video/mp4")


@app.route("/batch_delete_videos", methods=["POST"])
def batch_delete_videos():
    """Delete multiple videos at once."""
    try:
        data = request.get_json()
        videos_to_delete = data.get("videos", [])

        if not videos_to_delete:
            return jsonify({"success": False, "error": "No videos specified"}), 400

        # Use the helper function instead of direct Redis operations
        results = delete_videos(redis_client, videos_to_delete)
        success_count = sum(1 for r in results if r["success"])

        return jsonify(
            {
                "success": True,
                "results": results,
                "summary": f"Successfully deleted {success_count} out of {len(videos_to_delete)} videos",
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/add_tag_to_videos", methods=["POST"])
def add_tag_to_videos():
    try:
        data = request.get_json()
        video_ids = data.get("video_ids", [])
        new_tag = data.get("tag", "")

        if not video_ids or not new_tag:
            return jsonify({"success": False, "error": "Missing video_ids or tag"}), 400

        # Use the helper function instead of direct Redis operations
        success = add_tags_to_videos(redis_client, video_ids, new_tag)
        return jsonify({"success": success})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
