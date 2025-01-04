import os
import mlx_whisper
from moviepy.editor import VideoFileClip
from pathlib import Path
import json
from tqdm import tqdm
import signal
import sys
import torch

# Print all available devices
print("\nAvailable PyTorch devices:")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"MPS available: {torch.backends.mps.is_available()}")
print(
    f"Current device: {torch.device('cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu')}"
)

if torch.cuda.is_available():
    print(f"CUDA device count: {torch.cuda.device_count()}")
    print(f"CUDA device name: {torch.cuda.get_device_name(0)}")

# For debugging MPS support
if hasattr(torch.backends, "mps"):
    print("\nMPS Backend details:")
    print(f"MPS available: {torch.backends.mps.is_available()}")
    print(f"MPS built: {torch.backends.mps.is_built()}")


def extract_audio(video_path, audio_path):
    """Extract audio from video file."""
    try:
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(audio_path, verbose=False, logger=None)
        video.close()
        return True
    except Exception as e:
        print(f"Error extracting audio from {video_path}: {str(e)}")
        return False


def process_video(video_path, output_dir):
    """Process a single video and generate transcript."""
    video_name = Path(video_path).stem
    audio_path = os.path.join(output_dir, f"{video_name}.mp3")
    transcript_path = os.path.join(output_dir, f"{video_name}.json")

    # Skip if transcript already exists
    if os.path.exists(transcript_path):
        print(f"Transcript already exists for {video_name}")
        return

    # Extract audio
    if not extract_audio(video_path, audio_path):
        return

    try:
        # Transcribe audio using MLX Whisper
        result = mlx_whisper.transcribe(
            audio_path, path_or_hf_repo="mlx-community/whisper-medium-mlx-8bit"
        )

        # Save transcript with metadata
        transcript_data = {
            "video_name": video_name,
            "text": result["text"],
            "segments": result["segments"],
            "language": result.get("language", "unknown"),
        }

        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, indent=2, ensure_ascii=False)

        # Clean up audio file
        os.remove(audio_path)

    except Exception as e:
        print(f"Error transcribing {video_name}: {str(e)}")


def signal_handler(sig, frame):
    print("\nGracefully shutting down...")
    sys.exit(0)


def process_downloads_folder(downloads_dir="downloads", model_size="base"):
    """Process all videos in the downloads directory structure."""
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    print(f"Loading Whisper model ({model_size})...")
    # Note: MLX Whisper will automatically use the optimized model

    # Walk through downloads directory
    for root, _, files in os.walk(downloads_dir):
        video_files = [f for f in files if f.endswith((".mp4", ".webm"))]

        if not video_files:
            continue

        # Create transcripts directory
        transcripts_dir = os.path.join(root, "transcripts")
        os.makedirs(transcripts_dir, exist_ok=True)

        print(f"\nProcessing {len(video_files)} videos in {root}")

        # Process each video
        for video_file in tqdm(video_files, desc="Extracting transcripts"):
            video_path = os.path.join(root, video_file)
            process_video(video_path, transcripts_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract transcripts from downloaded TikTok videos"
    )
    parser.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium", "large"],
        default="medium",
        help="Whisper model size (default: medium)",
    )
    parser.add_argument(
        "--dir",
        default="downloads",
        help="Downloads directory (default: downloads)",
    )
    args = parser.parse_args()

    process_downloads_folder(args.dir)
