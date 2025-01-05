# Use Python 3.11 slim as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    libgl1-mesa-glx \
    libglib2.0-0 \
    wget \
    gnupg2 \
    apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Default command (will be overridden by docker-compose)
CMD ["python", "services/video_downloader.py"]
