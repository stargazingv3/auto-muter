import os
import argparse
import torch
import torchaudio
import numpy as np
from speechbrain.pretrained import EncoderClassifier
from tqdm import tqdm

# --- Configuration ---
# Ensure the model is cached to a specific directory if needed, otherwise it uses default Hugging Face cache.
# os.environ["HF_HOME"] = "/path/to/your/cache"

def resample_audio(audio_path, target_sr=16000):
    """
    Loads and resamples an audio file to the target sample rate.
    Returns a torch tensor.
    """
    waveform, sr = torchaudio.load(audio_path)
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)
        waveform = resampler(waveform)
    return waveform

def enroll_speaker_from_path(input_path, output_file):
    """
    Generates a robust speaker embedding from a single audio file or a directory of audio files.
    """
    if not os.path.exists(input_path):
        print(f"Error: Input path not found at {input_path}")
        return

    # --- Model Loading ---
    print("Loading the speaker embedding model (speechbrain/spkrec-ecapa-voxceleb)...")
    try:
        # Using a more powerful model for high-quality embeddings.
        # This will download the model on the first run.
        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=os.path.join("/tmp", "pretrained_models", "ecapa-tdnn") # Caching directory
        )
        print("Model loaded successfully.")
    except Exception as e:
        print(f"Error loading model. Ensure you have an internet connection. Error: {e}")
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
    print("Generating embeddings for each audio file...")
    for audio_path in tqdm(audio_files, desc="Processing files"):
        try:
            # Resample to 16kHz, which is required by the model
            waveform = resample_audio(audio_path, target_sr=16000)

            # --- FIX: Ensure minimum audio length ---
            # The model requires a minimum number of samples to work correctly.
            # A safe value is 1.5 seconds (1.5 * 16000 = 24000 samples).
            min_samples = 24000
            if waveform.shape[1] < min_samples:
                # Repeat the audio signal until it's long enough
                repeats = min_samples // waveform.shape[1] + 1
                waveform = waveform.repeat(1, repeats)
                # Trim to just over the minimum length
                waveform = waveform[:, :min_samples]
                tqdm.write(f"Info: Audio file {os.path.basename(audio_path)} was too short and has been looped to meet minimum length.")

            # The model expects a batch dimension, so we add one
            with torch.no_grad():
                embedding = classifier.encode_batch(waveform)
            
            # Squeeze to remove batch and channel dimensions, leaving just the embedding vector
            all_embeddings.append(embedding.squeeze())
        except Exception as e:
            print(f"\nWarning: Could not process file {audio_path}. Skipping. Error: {e}")
            continue
    
    if not all_embeddings:
        print("Could not generate any embeddings.")
        return

    # --- Averaging and Saving ---
    # To create a single, robust voiceprint, we average the embeddings.
    # Stack all embeddings into a single tensor
    stacked_embeddings = torch.stack(all_embeddings)
    
    # Calculate the mean embedding across all files
    mean_embedding = torch.mean(stacked_embeddings, dim=0)
    
    print(f"\nGenerated a final embedding from {len(all_embeddings)} samples.")
    print(f"Final embedding shape: {mean_embedding.shape}")

    # Save the final embedding as a numpy array
    np.save(output_file, mean_embedding.cpu().numpy())
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
