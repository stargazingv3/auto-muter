# AutoMuter

AutoMuter is a Python application that automatically mutes the system audio when a specific person is speaking and unmutes it when they stop. This is useful for listening to livestreams or meetings where you want to avoid hearing a particular individual.

## Features

-   **Speaker Detection:** Identifies when a specific person is speaking.
-   **Automatic Muting:** Mutes and unmutes the system audio based on speaker detection.

## Getting Started

### Prerequisites

-   [Docker](https://docs.docker.com/get-docker/)
-   [Docker Compose](https://docs.docker.com/compose/install/)

### Setup

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/your-username/auto-muter.git
    cd auto-muter
    ```

2.  **Build and start the Docker container:**

    ```bash
    docker-compose build
    docker-compose up -d
    ```

3.  **Access the running container:**

    ```bash
    docker-compose exec app bash
    ```

Now you are inside the container's shell and can run the application.

## How it works

The application uses `pyannote.audio` for speaker diarization to distinguish between different speakers in real-time. When the target speaker is detected, it uses `pulsectl` to mute the system audio. When the target speaker stops talking, the audio is unmuted.
