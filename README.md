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

## TODO Checklist

### Infrastructure & Performance
- [ ] **Container Optimization**
  - [ ] Reduce Docker container size

- [ ] **EC2 Instance Optimization**
  - [ ] Modify deployment to work on free-tier EC2 instances (t2.micro/t3.micro)
  - [ ] Optimize resource usage to fit within free-tier limits
  - [ ] Update deployment documentation for free-tier setup

### Browser Extension
- [ ] **Google Chrome Web Store**
  - [ ] Adherence to policies and acceptance to store
  - [ ] Update extension description and documentation
  - [ ] Add good screenshots and a demo video
  - [ ] Logos for favicon and actual extension

### Technical Improvements
- [ ] **Threshold Investigation**
  - [ ] Investigate why target threshold needs to be set low
  - [ ] Optimize speaker detection sensitivity
  - [ ] Implement adaptive threshold adjustment
  - [ ] Add configuration options for different environments

- [ ] **Database Management**
  - [x] Move database storage from `browser-extension/backend/` to `backend/databases/`
  - [ ] Add database backup and recovery procedures

- [ ] **Data Privacy & User Consent**
  - [x] Create and host a comprehensive Privacy Policy.
  - [x] Implement a one-time user consent screen on first installation.
  - [ ] Add configurable data retention policy for database cleanup
  - [ ] Add an "Offline Mode" toggle to disable data collection.
  - [ ] Ensure "Delete All My Data" also deletes any local storage so next launch brings up one-time consent like first install.
  - [ ] Add a link to the Privacy Policy within the extension.

### Documentation & Maintenance
- [ ] **User Documentation**
  - [ ] Create user installation guides for w/o Chrome store
  - [ ] Create FAQ and common issues resolution
  - [ ] Document configuration options and troubleshooting

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
