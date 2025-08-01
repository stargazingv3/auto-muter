# --- Builder Stage ---
# This stage installs all dependencies, including build tools.
FROM python:3.10 AS builder

# Install system dependencies required for building wheels
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the requirements file to leverage Docker cache
COPY docker/requirements.txt .

# Install python packages
# This creates a virtual environment in /opt/venv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt


# --- Final Stage ---
# This stage creates the small production image.
FROM python:3.10-slim

# Install runtime system dependencies and locales package
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    locales \
    && rm -rf /var/lib/apt/lists/*

# Generate and set the locale to prevent encoding errors
RUN sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    locale-gen
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Make the virtual environment's Python the default
ENV PATH="/opt/venv/bin:$PATH"

# Create a non-root user to run the application
RUN useradd --create-home appuser
USER appuser

# Set up necessary directories with correct permissions
#RUN mkdir -p /app/browser-extension/backend/tmp
#RUN mkdir -p /app/error_audio_dumps
#RUN mkdir -p /app/success_audio_dumps

# Copy the application code into the final image
COPY --chown=appuser:appuser . .

# Expose the port the app runs on
EXPOSE 8000
