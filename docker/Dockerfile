# --- Builder Stage ---
# Use slim base to reduce total layers downloaded during build.
FROM python:3.10-slim AS builder

# Install only build tools needed for compiling Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
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
# This stage creates the slim production image.
FROM python:3.10-slim

# Install minimal runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Prefer C.UTF-8 which is available without generating locales
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Make the virtual environment's Python the default
ENV PATH="/opt/venv/bin:$PATH"

# Create a non-root user to run the application
RUN useradd --create-home appuser
USER appuser

# Copy the application code into the final image
COPY --chown=appuser:appuser . .

# Expose the port the app runs on
EXPOSE 8000
