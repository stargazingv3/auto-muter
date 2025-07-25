import os
import argparse
import torch
import numpy as np
from pyannote.audio import Inference
from pyannote.core import SlidingWindowFeature
from pydub import AudioSegment
from tqdm import tqdm
import shutil
import tempfile
import uuid

# --- Configuration ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")

# --- Constants ---
BASE_DATA_DIR = "/data/auto-muter"
RAW_AUDIO_DIR = os.path.join(BASE_DATA_DIR, "raw/talking-counter")
SPEAKER_SAMPLES_DIR = os.path.join(BASE_DATA_DIR, "speaker-samples")
OUTPUT_SPEAKERS_DIR = os.path.join(BASE_DATA_DIR, "speakers")

# Model-specific settings
SAMPLE_RATE = 16000
CHUNK_DURATION_S = 2.0  # Duration of audio chunks to analyze (in seconds)
CHUNK_STEP_S = 1.0      # How far to slide the window for the next chunk
INITIAL_CONFIDENCE_THRESHOLD = 0.1  # Start with a lower threshold
CONFIDENCE_THRESHOLD_INCREMENT = 0.2 # Increase by this much each round

# --- Helper Functions ---

def get_pyannote_model():
    """Loads and returns the pyannote embedding model."""
    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = Inference(
            "pyannote/embedding",
            window="whole",
            use_auth_token=HF_TOKEN,
            device=device
        )
        print(f"Pyannote model loaded successfully on device: {device}")
        return model, device
    except Exception as e:
        print(f"CRITICAL: Failed to load pyannote model: {e}")
        raise

def get_embedding(model, audio_path):
    """Generates an embedding from a single audio file."""
    try:
        # pyannote.audio.Inference can take a path directly
        embedding_output = model(audio_path)
        if isinstance(embedding_output, SlidingWindowFeature):
            return embedding_output.data.mean(axis=0)
        return np.asarray(embedding_output)
    except Exception as e:
        # Suppress repeated warnings for the same file if it's expected
        # print(f"Warning: Could not generate embedding for {audio_path}. Error: {e}")
        return None

def get_embedding_from_folder(model, folder_path):
    """Generates a single, averaged embedding from a folder of audio files."""
    all_embeddings = []
    audio_files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.wav', '.mp3'))]

    if not audio_files:
        return None

    for filename in tqdm(audio_files, desc=f"Generating embedding from {os.path.basename(folder_path)}"):
        filepath = os.path.join(folder_path, filename)
        embedding = get_embedding(model, filepath)
        if embedding is not None:
            all_embeddings.append(embedding)

    if not all_embeddings:
        return None

    return np.mean(np.stack(all_embeddings), axis=0)

# --- Main Extraction Logic ---

def extract_samples(speaker_name, num_rounds=3):
    """
    Performs iterative sample extraction for a given speaker.
    """
    print(f"--- Starting data extraction pipeline for speaker: {speaker_name} ---")

    # 1. Load Model
    model, device = get_pyannote_model()

    # 2. Define paths
    initial_sample_path = os.path.join(SPEAKER_SAMPLES_DIR, f"{speaker_name}.mp3")
    speaker_output_dir = os.path.join(OUTPUT_SPEAKERS_DIR, speaker_name)

    if not os.path.exists(initial_sample_path):
        print(f"Error: Initial sample not found for speaker '{speaker_name}' at: {initial_sample_path}")
        return

    # 3. Iterative Extraction Loop
    current_embedding_source = initial_sample_path
    current_confidence_threshold = INITIAL_CONFIDENCE_THRESHOLD

    for i in range(1, num_rounds + 1):
        round_num = i
        print(f"\n--- Starting Round {round_num} of {num_rounds} ---")
        print(f"Current Confidence Threshold: {current_confidence_threshold:.2f}")

        # a. Create output directory for this round
        round_output_dir = os.path.join(speaker_output_dir, f"run_{round_num}")
        os.makedirs(round_output_dir, exist_ok=True)
        print(f"Output directory for this round: {round_output_dir}")

        # b. Generate the master embedding for this round
        print(f"Generating master embedding from: {current_embedding_source}")
        if os.path.isdir(current_embedding_source):
            master_embedding_np = get_embedding_from_folder(model, current_embedding_source)
        else: # It's the initial file
            master_embedding_np = get_embedding(model, current_embedding_source)

        if master_embedding_np is None:
            print("Error: Could not generate a master embedding. Stopping pipeline.")
            return

        master_embedding = torch.from_numpy(master_embedding_np).to(device).unsqueeze(0)
        print("Master embedding generated successfully.")

        # c. Scan raw audio files and extract matching chunks
        raw_files = [os.path.join(RAW_AUDIO_DIR, f) for f in os.listdir(RAW_AUDIO_DIR) if f.lower().endswith(('.wav', '.mp3', '.flac', '.m4a'))]

        found_clips_count = 0
        
        # Pre-process all raw audio files once per round
        processed_audios = {}
        for raw_file_path in tqdm(raw_files, desc=f"Loading Raw Audio (Round {round_num})"):
            try:
                # Load and resample once
                audio = AudioSegment.from_file(raw_file_path).set_channels(1).set_frame_rate(SAMPLE_RATE)
                processed_audios[raw_file_path] = audio
            except Exception as e:
                tqdm.write(f"Warning: Failed to load raw file {raw_file_path}. Error: {e}")
                continue

        for raw_file_path, audio in tqdm(processed_audios.items(), desc=f"Scanning & Extracting (Round {round_num})"):
            try:
                duration_ms = len(audio)
                chunk_duration_ms = int(CHUNK_DURATION_S * 1000)
                chunk_step_ms = int(CHUNK_STEP_S * 1000)

                # Use a single temporary directory for all chunks in this raw_file_path
                with tempfile.TemporaryDirectory() as temp_dir:
                    for start_ms in range(0, duration_ms - chunk_duration_ms + 1, chunk_step_ms): # +1 to include the last possible chunk
                        end_ms = start_ms + chunk_duration_ms
                        chunk = audio[start_ms:end_ms]

                        # Export chunk to a file in the temporary directory
                        temp_chunk_file_path = os.path.join(temp_dir, f"chunk_{start_ms}_{end_ms}.wav")
                        chunk.export(temp_chunk_file_path, format="wav")

                        chunk_embedding_np = get_embedding(model, temp_chunk_file_path)

                        if chunk_embedding_np is None:
                            continue

                        chunk_embedding = torch.from_numpy(chunk_embedding_np).to(device).unsqueeze(0)

                        # Compare embeddings
                        similarity = torch.nn.functional.cosine_similarity(master_embedding, chunk_embedding).item()
                        print(similarity)

                        if similarity > current_confidence_threshold:
                            found_clips_count += 1
                            output_filename = f"{speaker_name}_round{round_num}_{uuid.uuid4().hex[:8]}.wav"
                            # Re-export the original chunk to the final output directory
                            chunk.export(os.path.join(round_output_dir, output_filename), format="wav")

            except Exception as e:
                tqdm.write(f"Warning: Failed to process raw file {raw_file_path}. Error: {e}")
                continue

        print(f"--- Round {round_num} Complete. Found {found_clips_count} new clips. ---")

        if found_clips_count == 0:
            print("No new clips found in this round. Stopping pipeline as further rounds will not improve.")
            break

        # d. The output of this round becomes the input for the next
        current_embedding_source = round_output_dir
        # e. Increase the confidence threshold for the next round
        current_confidence_threshold = min(1.0, current_confidence_threshold + CONFIDENCE_THRESHOLD_INCREMENT)


    print(f"\n--- Data extraction pipeline for speaker '{speaker_name}' finished. ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Iteratively extract speaker samples from a raw dataset.")
    parser.add_argument(
        "-s", "--speaker",
        type=str,
        required=True,
        help="The name of the speaker (e.g., 'yanko'), which corresponds to the initial sample file name."
    )
    parser.add_argument(
        "-r", "--rounds",
        type=int,
        default=3,
        help="The number of extraction rounds to perform."
    )

    args = parser.parse_args()

    extract_samples(args.speaker, args.rounds)