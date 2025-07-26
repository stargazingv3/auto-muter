import os
import argparse
import torch
import numpy as np
from pyannote.audio import Inference, Pipeline # Import Pipeline
from pyannote.core import SlidingWindowFeature, Segment, Timeline
from pydub import AudioSegment
from tqdm import tqdm
import shutil
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import traceback # Added for more detailed error reporting in workers

# --- Configuration ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")
    print("Please set the HF_AUTH_TOKEN environment variable with your Hugging Face token.")
    print("You can get one from: https://huggingface.co/settings/tokens")
    # Exit if token is critical and not set (optional, but good for critical dependencies)
    # exit(1) 

# --- Constants ---
BASE_DATA_DIR = "/data/auto-muter"
RAW_AUDIO_DIR = os.path.join(BASE_DATA_DIR, "raw/talking-counter")
SPEAKER_SAMPLES_DIR = os.path.join(BASE_DATA_DIR, "speaker-samples")
OUTPUT_SPEAKERS_DIR = os.path.join(BASE_DATA_DIR, "speakers")

# Model-specific settings
SAMPLE_RATE = 16000
MIN_VAD_SEGMENT_DURATION_S = 1.0 # Minimum duration for a VAD segment to be considered for embedding
INITIAL_CONFIDENCE_THRESHOLD = 0.3  # Start with a lower threshold
CONFIDENCE_THRESHOLD_INCREMENT = 0.2 # Increase by this much each round

# Global variable for models within multiprocessing context (each process loads its own)
_embedding_model_instance = None
_vad_pipeline_instance = None # Changed to _vad_pipeline_instance
_device_instance = None

# --- Helper Functions ---

def _init_worker_models():
    """
    Initializes the pyannote embedding and VAD models/pipelines in each worker process.
    Called once per process in the ProcessPoolExecutor.
    """
    global _embedding_model_instance, _vad_pipeline_instance, _device_instance
    if _embedding_model_instance is None or _vad_pipeline_instance is None:
        try:
            _device_instance = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            # Load embedding model using Inference
            _embedding_model_instance = Inference(
                "pyannote/embedding",
                window="whole",
                use_auth_token=HF_TOKEN,
                device=_device_instance
            )
            
            # Load VAD model using Pipeline
            # Note: Pipeline.from_pretrained handles downloading all necessary components correctly
            _vad_pipeline_instance = Pipeline.from_pretrained(
                "pyannote/voice-activity-detection",
                use_auth_token=HF_TOKEN
            )
            # Ensure the VAD pipeline also uses the specified device
            _vad_pipeline_instance.to(_device_instance)


            print(f"Worker models (embedding, VAD pipeline) loaded successfully on device: {_device_instance}")
        except Exception as e:
            print(f"CRITICAL: Worker failed to load pyannote models: {e}")
            traceback.print_exc() # Print full traceback for critical errors
            raise
    return _embedding_model_instance, _vad_pipeline_instance, _device_instance

def get_embedding(audio_input):
    """
    Generates an embedding from an audio source.
    audio_input can be a path (for initial/master embedding)
    or a tuple (waveform_array, sample_rate) for in-memory chunks.
    """
    global _embedding_model_instance, _device_instance
    if _embedding_model_instance is None:
        # This branch should ideally not be hit if _init_worker_models is called
        # but as a safeguard, it ensures models are loaded.
        _init_worker_models() 

    try:
        if isinstance(audio_input, str): # Path to a file
            embedding_output = _embedding_model_instance(audio_input)
        elif isinstance(audio_input, tuple) and len(audio_input) == 2: # (waveform_np, sample_rate)
            waveform_np, sample_rate = audio_input
            # Ensure waveform is float32 and correct shape (channels, samples)
            waveform_tensor = torch.from_numpy(waveform_np.astype(np.float32)).unsqueeze(0) # (1, samples) for mono
            embedding_output = _embedding_model_instance({'waveform': waveform_tensor.to(_device_instance), 'sample_rate': sample_rate})
        else:
            raise ValueError("Unsupported audio_input type for get_embedding.")

        if isinstance(embedding_output, SlidingWindowFeature):
            return embedding_output.data.mean(axis=0)
        return np.asarray(embedding_output)
    except Exception as e:
        tqdm.write(f"Warning: Could not generate embedding for input type {type(audio_input)}. Error: {e}")
        # traceback.print_exc() # Uncomment for more detailed error during debugging
        return None

def get_embedding_from_folder(folder_path):
    """Generates a single, averaged embedding from a folder of audio files."""
    all_embeddings = []
    audio_files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.wav', '.mp3'))]

    if not audio_files:
        return None

    global _embedding_model_instance, _device_instance
    if _embedding_model_instance is None:
        _init_worker_models() # Initialize all models

    for filename in tqdm(audio_files, desc=f"Generating master embedding from {os.path.basename(folder_path)}"):
        filepath = os.path.join(folder_path, filename)
        embedding = get_embedding(filepath)
        if embedding is not None:
            all_embeddings.append(embedding)

    if not all_embeddings:
        return None

    return np.mean(np.stack(all_embeddings), axis=0)

def process_single_raw_audio_file(raw_file_path, master_embedding_np, current_confidence_threshold, round_output_dir, speaker_name):
    """
    Processes a single raw audio file, performs VAD, extracts speech segments,
    and saves matching speaker clips.
    This function is designed to be run in parallel by ProcessPoolExecutor.
    """
    global _embedding_model_instance, _vad_pipeline_instance, _device_instance
    if _embedding_model_instance is None or _vad_pipeline_instance is None:
        _init_worker_models() # Ensure models are loaded in this process

    found_clips_in_file = 0
    master_embedding = torch.from_numpy(master_embedding_np).to(_device_instance).unsqueeze(0)

    try:
        audio = AudioSegment.from_file(raw_file_path).set_channels(1).set_frame_rate(SAMPLE_RATE)
        
        # 1. Perform Voice Activity Detection using the VAD pipeline
        speech_annotation: Annotation = _vad_pipeline_instance(raw_file_path)

        # Convert the Annotation to a Timeline, which can then be iterated for coverage
        # This will merge overlapping or contiguous speech segments.
        speech_timeline: Timeline = speech_annotation.get_timeline().support()

        # 2. Iterate through detected speech segments in the timeline
        for segment in speech_timeline:
            start_s = segment.start
            end_s = segment.end
            
            # Ensure segment is long enough
            if (end_s - start_s) < MIN_VAD_SEGMENT_DURATION_S:
                continue

            # Extract audio chunk based on VAD segment
            start_ms = int(start_s * 1000)
            end_ms = int(end_s * 1000)
            chunk = audio[start_ms:end_ms]

            # Convert pydub AudioSegment to numpy array for embedding
            chunk_samples = np.array(chunk.get_array_of_samples())
            chunk_waveform_np = chunk_samples / (2**((chunk.sample_width * 8) - 1)) # Normalize
            
            chunk_embedding_np = get_embedding((chunk_waveform_np, SAMPLE_RATE))

            if chunk_embedding_np is None:
                continue

            chunk_embedding = torch.from_numpy(chunk_embedding_np).to(_device_instance).unsqueeze(0)

            # Compare embeddings
            similarity = torch.nn.functional.cosine_similarity(master_embedding, chunk_embedding).item()

            if similarity > current_confidence_threshold:
                found_clips_in_file += 1
                raw_file_base = os.path.splitext(os.path.basename(raw_file_path))[0]
                output_filename = f"{speaker_name}_{raw_file_base}_t{start_ms}-{end_ms}_{uuid.uuid4().hex[:4]}.wav"
                chunk.export(os.path.join(round_output_dir, output_filename), format="wav")

    except Exception as e:
        tqdm.write(f"Warning: Worker failed to process raw file {raw_file_path}. Error: {e}")
        traceback.print_exc() # Print full traceback for worker errors
        return 0
    
    return found_clips_in_file

# --- Main Extraction Logic ---

def extract_samples(speaker_name, num_rounds=3, max_workers=None):
    """
    Performs iterative sample extraction for a given speaker using multiprocessing.
    """
    print(f"--- Starting data extraction pipeline for speaker: {speaker_name} ---")

    # The main process still needs to load models for master embedding generation
    # Call _init_worker_models once in the main process
    _embedding_model_instance, _vad_pipeline_instance, _device_instance = _init_worker_models()

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
        
        with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker_models) as executor:
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

            for future in tqdm(as_completed(futures), total=len(futures), desc=f"VAD & Extracting (Round {round_num})"):
                try:
                    clips_found_in_file = future.result()
                    found_clips_count += clips_found_in_file
                except Exception as exc:
                    tqdm.write(f"Generated an exception during file processing: {exc}")
        
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
        default=1, # Good default for most systems
        help="The number of worker processes to use for parallel audio processing. Default is 4."
    )

    args = parser.parse_args()

    # Ensure base directories exist
    os.makedirs(RAW_AUDIO_DIR, exist_ok=True)
    os.makedirs(SPEAKER_SAMPLES_DIR, exist_ok=True)
    os.makedirs(OUTPUT_SPEAKERS_DIR, exist_ok=True)

    extract_samples(args.speaker, args.rounds, args.workers)