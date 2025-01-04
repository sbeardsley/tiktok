import os
import json
from pathlib import Path
from tqdm import tqdm
import cv2
from PIL import Image


def extract_tags_from_description(description):
    """Extract hashtags from description text."""
    if not description:
        return []

    # Split the text by spaces to separate text from hashtag groups
    parts = description.split()
    tags = []

    for part in parts:
        # If the part starts with #, it's the beginning of tags
        if part.startswith("#"):
            # Split the part by # and filter out empty strings
            hashtags = [tag.lower() for tag in part.split("#") if tag]
            tags.extend(hashtags)
        # If the part contains # in the middle, it might be connected tags
        elif "#" in part:
            # Split by # and take everything after the first #
            hashtags = [tag.lower() for tag in part.split("#")[1:] if tag]
            tags.extend(hashtags)

    return list(set(tags))  # Remove duplicates


def generate_thumbnail(video_path):
    """Generate a thumbnail from a video file."""
    thumbnail_path = video_path.parent / f"{video_path.stem}_thumb.jpg"

    try:
        # Open the video file
        video = cv2.VideoCapture(str(video_path))
        success, frame = video.read()

        if success:
            # Convert from BGR to RGB
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

            # Create black background
            background = Image.new("RGB", (width, height), (0, 0, 0))

            # Resize image
            pil_image = pil_image.resize(resize_size, Image.Resampling.LANCZOS)

            # Paste resized image onto black background
            background.paste(pil_image, position)

            # Save thumbnail
            background.save(thumbnail_path, "JPEG", quality=85)
            return str(thumbnail_path.relative_to(video_path.parent))

    except Exception as e:
        print(f"Error generating thumbnail for {video_path}: {str(e)}")
        return None
    finally:
        if "video" in locals():
            video.release()


def process_metadata_files():
    """Process all metadata.json files in the downloads directory."""
    downloads_dir = Path("downloads")

    if not downloads_dir.exists():
        print("Downloads directory not found!")
        return

    # Find all metadata.json files
    metadata_files = list(downloads_dir.rglob("metadata.json"))
    print(f"Found {len(metadata_files)} metadata files to process")

    total_files_updated = 0
    total_videos_updated = 0

    for metadata_file in tqdm(metadata_files, desc="Processing metadata files"):
        try:
            # Read the current metadata
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Track if we made any changes
            file_updated = False
            videos_updated = 0

            # Process each video in the metadata
            for video in metadata:
                updated = False

                # Add deleted property if it doesn't exist
                if "deleted" not in video:
                    video["deleted"] = False
                    updated = True

                # Add or update video and thumbnail paths
                video_path = metadata_file.parent / f"{video['video_id']}.mp4"
                if video_path.exists():
                    # Add video path relative to downloads directory
                    video_rel_path = str(video_path.relative_to(downloads_dir))
                    if (
                        "video_path" not in video
                        or video["video_path"] != video_rel_path
                    ):
                        video["video_path"] = video_rel_path
                        updated = True

                    # Handle thumbnail
                    thumb_filename = f"{video['video_id']}_thumb.jpg"
                    thumb_path = metadata_file.parent / thumb_filename
                    thumb_rel_path = str(thumb_path.relative_to(downloads_dir))

                    # Generate thumbnail if it doesn't exist
                    if not thumb_path.exists():
                        if generate_thumbnail(video_path):
                            video["thumbnail_path"] = thumb_rel_path
                            updated = True
                    # Update thumbnail path if it's missing or incorrect
                    elif (
                        "thumbnail_path" not in video
                        or video["thumbnail_path"] != thumb_rel_path
                    ):
                        video["thumbnail_path"] = thumb_rel_path
                        updated = True

                # Process description for tags
                description = video.get("description", "")
                if description and "#" in description:
                    # Extract tags from description
                    new_tags = extract_tags_from_description(description)

                    # Initialize or update tags array
                    current_tags = set(video.get("tags", []))
                    current_tags.update(new_tags)

                    # Update tags if we found new ones
                    if len(current_tags) > len(video.get("tags", [])):
                        video["tags"] = sorted(
                            list(current_tags)
                        )  # Sort tags alphabetically
                        updated = True

                if updated:
                    file_updated = True
                    videos_updated += 1

            # Save updates if changes were made
            if file_updated:
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                total_files_updated += 1
                total_videos_updated += videos_updated
                print(f"\nUpdated {videos_updated} videos in {metadata_file}")

        except Exception as e:
            print(f"\nError processing {metadata_file}: {str(e)}")
            continue

    print(f"\nProcess complete!")
    print(f"Updated {total_videos_updated} videos across {total_files_updated} files")


if __name__ == "__main__":
    process_metadata_files()
