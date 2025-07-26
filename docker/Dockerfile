FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    portaudio19-dev \
    libasound2-dev \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY docker/requirements.txt .
RUN pip install -r requirements.txt

RUN mkdir -p /.cache && chmod 777 /.cache
RUN mkdir -p /.local && chmod 777 /.local

# Copy the rest of the application
COPY /browser-extension/backend /app