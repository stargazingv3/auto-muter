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
from concurrent.futures import ProcessPoolExecutor, as_completed # Using ProcessPoolExecutor for CPU-bound tasks
import multiprocessing # Import multiprocessing module

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
INITIAL_CONFIDENCE_THRESHOLD = 0.3  # Start with a lower threshold
CONFIDENCE_THRESHOLD_INCREMENT = 0.2 # Increase by this much each round

# Global variable for model within multiprocessing context (each process loads its own)
# This is a common pattern when passing objects that aren't easily serializable (like PyTorch models)
_model_instance = None
_device_instance = None

# --- Helper Functions ---

def _init_worker_model():
    """
    Initializes the pyannote model in each worker process.
    Called once per process in the ProcessPoolExecutor.
    """
    global _model_instance, _device_instance
    if _model_instance is None:
        try:
            _device_instance = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            _model_instance = Inference(
                "pyannote/embedding",
                window="whole",
                use_auth_token=HF_TOKEN,
                device=_device_instance
            )
            print(f"Worker model loaded successfully on device: {_device_instance}")
        except Exception as e:
            print(f"CRITICAL: Worker failed to load pyannote model: {e}")
            raise
    return _model_instance, _device_instance

def get_embedding(audio_input):
    """
    Generates an embedding from an audio source.
    audio_input can be a path (for initial/master embedding)
    or a tuple (waveform_array, sample_rate) for in-memory chunks.
    """
    global _model_instance, _device_instance
    if _model_instance is None:
        _init_worker_model() # Ensure model is loaded in this process

    try:
        if isinstance(audio_input, str): # Path to a file
            embedding_output = _model_instance(audio_input)
        elif isinstance(audio_input, tuple) and len(audio_input) == 2: # (waveform_np, sample_rate)
            waveform_np, sample_rate = audio_input
            # Ensure waveform is float32 and correct shape (channels, samples)
            # Pyannote expects (batch, channels, samples) or (channels, samples)
            waveform_tensor = torch.from_numpy(waveform_np.astype(np.float32)).unsqueeze(0) # (1, samples) for mono
            embedding_output = _model_instance({'waveform': waveform_tensor, 'sample_rate': sample_rate})
        else:
            raise ValueError("Unsupported audio_input type for get_embedding.")

        if isinstance(embedding_output, SlidingWindowFeature):
            return embedding_output.data.mean(axis=0)
        return np.asarray(embedding_output)
    except Exception as e:
        # Suppress repeated warnings for the same file if it's expected
        # tqdm.write(f"Warning: Could not generate embedding for input type {type(audio_input)}. Error: {e}")
        return None

def get_embedding_from_folder(folder_path):
    """Generates a single, averaged embedding from a folder of audio files."""
    all_embeddings = []
    audio_files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.wav', '.mp3'))]

    if not audio_files:
        return None

    global _model_instance, _device_instance
    if _model_instance is None:
        _init_worker_model()

    for filename in tqdm(audio_files, desc=f"Generating embedding from {os.path.basename(folder_path)}"):
        filepath = os.path.join(folder_path, filename)
        embedding = get_embedding(filepath) # Use the global model
        if embedding is not None:
            all_embeddings.append(embedding)

    if not all_embeddings:
        return None

    return np.mean(np.stack(all_embeddings), axis=0)

def process_single_raw_audio_file(raw_file_path, master_embedding_np, current_confidence_threshold, round_output_dir, speaker_name):
    """
    Processes a single raw audio file, extracts chunks,
    and saves matching speaker clips.
    This function is designed to be run in parallel by ProcessPoolExecutor.
    """
    global _model_instance, _device_instance
    if _model_instance is None:
        _init_worker_model() # Ensure model is loaded in this process

    found_clips_in_file = 0
    # Move master_embedding to the correct device within the worker process
    master_embedding = torch.from_numpy(master_embedding_np).to(_device_instance).unsqueeze(0)

    try:
        audio = AudioSegment.from_file(raw_file_path).set_channels(1).set_frame_rate(SAMPLE_RATE)
        duration_ms = len(audio)
        chunk_duration_ms = int(CHUNK_DURATION_S * 1000)
        chunk_step_ms = int(CHUNK_STEP_S * 1000)

        for start_ms in range(0, duration_ms - chunk_duration_ms + 1, chunk_step_ms):
            end_ms = start_ms + chunk_duration_ms
            chunk = audio[start_ms:end_ms]

            # Convert pydub AudioSegment to numpy array for in-memory processing
            samples = np.array(chunk.get_array_of_samples())
            if chunk.sample_width == 2: # 16-bit
                samples = samples.astype(np.int16)
            elif chunk.sample_width == 4: # 32-bit (rare for audio, but good to handle)
                samples = samples.astype(np.int32)
            
            # Normalize to float between -1 and 1
            waveform_np = samples / (2**((chunk.sample_width * 8) - 1))
            
            # Use get_embedding with in-memory waveform_np
            chunk_embedding_np = get_embedding((waveform_np, SAMPLE_RATE))

            if chunk_embedding_np is None:
                continue

            chunk_embedding = torch.from_numpy(chunk_embedding_np).to(_device_instance).unsqueeze(0)

            # Compare embeddings
            similarity = torch.nn.functional.cosine_similarity(master_embedding, chunk_embedding).item()

            if similarity > current_confidence_threshold:
                found_clips_in_file += 1
                # Generate a unique filename including source file info and timestamp
                raw_file_base = os.path.splitext(os.path.basename(raw_file_path))[0]
                output_filename = f"{speaker_name}_{raw_file_base}_t{start_ms}-{end_ms}_{uuid.uuid4().hex[:4]}.wav"
                # Export the original chunk to the final output directory
                chunk.export(os.path.join(round_output_dir, output_filename), format="wav")
                # print(f"    Saved clip from {raw_file_base} at {start_ms}ms with similarity {similarity:.4f}") # Too verbose

    except Exception as e:
        tqdm.write(f"Warning: Worker failed to process raw file {raw_file_path}. Error: {e}")
        return 0 # Return 0 clips found if an error occurs for this file
    
    return found_clips_in_file

# --- Main Extraction Logic ---

def extract_samples(speaker_name, num_rounds=3, max_workers=None):
    """
    Performs iterative sample extraction for a given speaker using multiprocessing.
    """
    print(f"--- Starting data extraction pipeline for speaker: {speaker_name} ---")

    # The main process does not need to load the model initially if only workers use it for chunk processing
    # However, get_embedding_from_folder and the initial get_embedding (for first master) need it.
    # So, we'll load it once in the main process for these specific tasks.
    # This model instance is for master embedding generation only.
    main_process_model, main_process_device = _init_worker_model() # Re-use the worker init to ensure consistency

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

        # b. Generate the master embedding for this round using the main process model
        print(f"Generating master embedding from: {current_embedding_source}")
        if os.path.isdir(current_embedding_source):
            # Pass dummy model object to get_embedding_from_folder
            master_embedding_np = get_embedding_from_folder(current_embedding_source)
        else: # It's the initial file
            master_embedding_np = get_embedding(current_embedding_source)

        if master_embedding_np is None:
            print("Error: Could not generate a master embedding. Stopping pipeline.")
            return

        print("Master embedding generated successfully.")

        # c. Scan raw audio files and extract matching chunks using multiprocessing
        raw_files = [os.path.join(RAW_AUDIO_DIR, f) for f in os.listdir(RAW_AUDIO_DIR) if f.lower().endswith(('.wav', '.mp3', '.flac', '.m4a'))]

        found_clips_count = 0
        
        # Use ProcessPoolExecutor for parallel processing of raw audio files
        # The `initializer=_init_worker_model` ensures each worker loads its own model instance.
        with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker_model) as executor:
            # Prepare arguments for each task in the pool
            # We pass master_embedding_np (a numpy array, which is picklable)
            # All other arguments are also picklable.
            futures = [
                executor.submit(
                    process_single_raw_audio_file,
                    raw_file_path,
                    master_embedding_np, # This numpy array will be copied to each process
                    current_confidence_threshold,
                    round_output_dir,
                    speaker_name
                )
                for raw_file_path in raw_files
            ]

            # Use tqdm to show progress for the parallel tasks
            for future in tqdm(as_completed(futures), total=len(futures), desc=f"Scanning & Extracting (Round {round_num})"):
                try:
                    clips_found_in_file = future.result()
                    found_clips_count += clips_found_in_file
                except Exception as exc:
                    tqdm.write(f"Generated an exception: {exc}")
        
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
    # Set the start method to 'spawn' for CUDA compatibility with multiprocessing
    # This must be done at the very beginning of the main block.
    multiprocessing.set_start_method('spawn', force=True)

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
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4, # Defaults to os.cpu_count()
        help="The number of worker processes to use for parallel audio processing. Default is number of CPU cores."
    )

    args = parser.parse_args()

    # Ensure base directories exist
    os.makedirs(RAW_AUDIO_DIR, exist_ok=True)
    os.makedirs(SPEAKER_SAMPLES_DIR, exist_ok=True)
    os.makedirs(OUTPUT_SPEAKERS_DIR, exist_ok=True)

    extract_samples(args.speaker, args.rounds, args.workers)