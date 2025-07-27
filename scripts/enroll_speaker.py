import os
import argparse
import torch
import numpy as np
from pyannote.audio import Inference
from pyannote.core import SlidingWindowFeature
from pydub import AudioSegment
from tqdm import tqdm
import tempfile

# --- Configuration ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")

def convert_to_wav(audio_path, target_sr=16000):
    """
    Converts an audio file to a temporary WAV file with the target sample rate.
    Returns the path to the temporary WAV file.
    """
    try:
        audio = AudioSegment.from_file(audio_path)
        audio = audio.set_frame_rate(target_sr).set_channels(1)
        
        # Create a temporary file to store the WAV data
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        audio.export(temp_wav.name, format="wav")
        return temp_wav.name
    except Exception as e:
        print(f"Warning: Could not process file {audio_path} with pydub. Skipping. Error: {e}")
        return None

def enroll_speaker_from_path(input_path, output_file):
    """
    Generates a robust speaker embedding from audio files using the pyannote/embedding model.
    """
    if not os.path.exists(input_path):
        print(f"Error: Input path not found at {input_path}")
        return

    # --- Model Loading ---
    print("Loading the speaker embedding model (pyannote/embedding)...")
    try:
        # This model configuration should match main.py
        inference_model = Inference(
            "pyannote/embedding", 
            window="whole", 
            use_auth_token=HF_TOKEN
        )
        print("Model loaded successfully.")
    except Exception as e:
        print(f"Error loading model. Ensure you have a valid Hugging Face token. Error: {e}")
        return

    # --- Audio File Discovery ---
    audio_files = []
    if os.path.isdir(input_path):
        print(f"Input is a directory. Searching for audio files in: {input_path}")
        for root, _, files in os.walk(input_path):
            for file in files:
                if file.lower().endswith(('.wav', '.mp3', '.flac', '.m4a')):
                    audio_files.append(os.path.join(root, file))
        print(f"Found {len(audio_files)} audio files.")
    elif os.path.isfile(input_path):
        print(f"Input is a single file: {input_path}")
        audio_files.append(input_path)
    
    if not audio_files:
        print("No audio files found to process.")
        return

    # --- Embedding Generation ---
    all_embeddings = []
    temp_files_to_clean = []
    print("Generating embeddings for each audio file...")
    for audio_path in tqdm(audio_files, desc="Processing files"):
        temp_wav_path = None
        try:
            # pyannote.audio's Inference can be sensitive to formats, so we convert to WAV first.
            temp_wav_path = convert_to_wav(audio_path)
            if temp_wav_path is None:
                continue
            temp_files_to_clean.append(temp_wav_path)

            # Generate the embedding
            embedding_output = inference_model(temp_wav_path)
            
            # The output might be a SlidingWindowFeature or a raw numpy array.
            if isinstance(embedding_output, SlidingWindowFeature):
                # Take the mean of embeddings over all windows to get a single vector
                embedding = embedding_output.data.mean(axis=0)
            else:
                embedding = np.asarray(embedding_output)

            all_embeddings.append(embedding)
        except Exception as e:
            print(f"\nWarning: Could not process file {audio_path}. Skipping. Error: {e}")
            continue
        finally:
            # Clean up the temporary WAV file immediately after use
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.remove(temp_wav_path)

    if not all_embeddings:
        print("Could not generate any embeddings.")
        return

    # --- Averaging and Saving ---
    # To create a single, robust voiceprint, we average the embeddings.
    stacked_embeddings = np.stack(all_embeddings)
    mean_embedding = np.mean(stacked_embeddings, axis=0)
    
    print(f"\nGenerated a final embedding from {len(all_embeddings)} samples.")
    print(f"Final embedding shape: {mean_embedding.shape}")

    # Save the final embedding as a numpy array
    np.save(output_file, mean_embedding)
    print(f"Speaker embedding saved successfully to: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enroll a speaker by generating an embedding from audio files.")
    parser.add_argument(
        "-i", "--input_path", 
        type=str, 
        required=True, 
        help="Path to a single audio file or a directory containing audio files."
    )
    parser.add_argument(
        "-o", "--output_file", 
        type=str, 
        required=True, 
        help="Path to save the final .npy embedding file."
    )
    
    args = parser.parse_args()
    
    enroll_speaker_from_path(args.input_path, args.output_file)