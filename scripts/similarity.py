import torch
from pyannote.audio import Inference
import io
import os
from pydub import AudioSegment
import argparse
from pyannote.core import SlidingWindowFeature # Import this for type hinting/clarity
import warnings # Import warnings to suppress them if needed

# --- Configuration ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN") # Replace with your actual token if not using env var
TARGET_SPEAKER_MP3 = "target_speaker.mp3" # Make sure this file exists in the same directory or provide full path

# --- Initialize Model ---
try:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    # Crucially, ensure 'window="whole"' is used for single embedding extraction
    inference_model = Inference("pyannote/embedding", device=device, use_auth_token=HF_TOKEN, window="whole")
    print("pyannote/embedding model loaded successfully.")
except Exception as e:
    print(f"Error loading pyannote/embedding model: {e}")
    print("Please ensure you have a valid Hugging Face token and necessary dependencies installed.")
    exit(1)

target_speaker_embedding = None

def load_target_speaker_embedding(mp3_path: str):
    """Loads and computes the embedding for the target speaker MP3."""
    global target_speaker_embedding
    if not os.path.exists(mp3_path):
        print(f"Error: Target speaker MP3 not found at {mp3_path}")
        target_speaker_embedding = None
        return

    try:
        print(f"Attempting to load target speaker embedding from {mp3_path}...")
        embedding_output = inference_model(mp3_path)
        if isinstance(embedding_output, SlidingWindowFeature):
            target_speaker_embedding = torch.from_numpy(embedding_output.data).mean(axis=0, keepdim=True).to(device)
        elif isinstance(embedding_output, torch.Tensor):
            target_speaker_embedding = embedding_output.to(device)
        else: # Handle case if it's a numpy array directly
            target_speaker_embedding = torch.from_numpy(embedding_output).to(device)

        # Ensure the embedding is 2D (batch_size, embedding_dim)
        if target_speaker_embedding.dim() == 1:
            target_speaker_embedding = target_speaker_embedding.unsqueeze(0)

        print("Target speaker embedding loaded successfully.")
    except Exception as e:
        print(f"Error loading target speaker embedding from {mp3_path}: {e}")
        target_speaker_embedding = None

def calculate_similarity(target_speaker_embedding, audio_file_path: str) -> tuple[bool, float]:
    """
    Calculates the similarity of an audio file to the target speaker.
    Saves the incoming raw audio data if decoding or processing fails.
    """
    if target_speaker_embedding is None:
        print("Target speaker embedding not loaded. Cannot perform detection.")
        return False, 0.0

    print(f"Processing audio file: {audio_file_path}")

    try:
        with open(audio_file_path, "rb") as f:
            audio_data = f.read()

        print(f"Received {len(audio_data)} bytes for processing from {audio_file_path}.")

        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format=audio_file_path.split('.')[-1])
        print(f"pydub conversion successful. Length: {audio_segment.duration_seconds:.2f}s")

        if audio_segment.frame_rate != 16000 or audio_segment.channels != 1:
            print(f"Resampling audio from {audio_segment.frame_rate}Hz, {audio_segment.channels} channels to 16000Hz, 1 channel.")
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)

        wav_file_in_memory = io.BytesIO()
        audio_segment.export(wav_file_in_memory, format="wav")
        wav_file_in_memory.seek(0)
        print("Audio exported to WAV in memory.")

        # Compute embedding for the live audio chunk
        live_audio_embedding_output = inference_model(wav_file_in_memory)

        # --- FIX START ---
        # Ensure live_audio_embedding is a PyTorch Tensor
        if isinstance(live_audio_embedding_output, SlidingWindowFeature):
            # If it's a SlidingWindowFeature, extract data and convert to Tensor
            live_audio_embedding = torch.from_numpy(live_audio_embedding_output.data).mean(axis=0, keepdim=True).to(device)
            print(f"Converted SlidingWindowFeature to Tensor. Shape: {live_audio_embedding.shape}")
        elif isinstance(live_audio_embedding_output, torch.Tensor):
            # It's already a Tensor, just ensure it's on the correct device
            live_audio_embedding = live_audio_embedding_output.to(device)
        else: # This handles the case where it might be a numpy array directly
            live_audio_embedding = torch.from_numpy(live_audio_embedding_output).to(device)
            print(f"Converted numpy array to Tensor. Shape: {live_audio_embedding.shape}")

        # Ensure both embeddings have the same number of dimensions (e.g., [1, D])
        if live_audio_embedding.dim() == 1:
            live_audio_embedding = live_audio_embedding.unsqueeze(0)
        if target_speaker_embedding.dim() == 1:
            target_speaker_embedding = target_speaker_embedding.unsqueeze(0) # This should ideally be handled in load_target_speaker_embedding
        # --- FIX END ---


        # Compare embeddings using cosine similarity
        similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, target_speaker_embedding)

        THRESHOLD = 0.65
        is_target = similarity.item() > THRESHOLD
        print(f"Similarity: {similarity.item():.4f}, Is Target: {is_target}")
        return is_target, similarity.item()

    except Exception as e:
        print(f"Error processing audio file {audio_file_path}: {e}")
        return False, 0.0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculate audio similarity to a target speaker.")
    parser.add_argument("audio_file", type=str,
                        help="Path to the audio file (e.g., .webm, .mp3) to analyze.")
    parser.add_argument("--target_speaker", type=str, default=TARGET_SPEAKER_MP3,
                        help=f"Path to the target speaker MP3 file (default: {TARGET_SPEAKER_MP3}).")
    args = parser.parse_args()

    # Suppress specific UserWarning from torchaudio if it's not relevant to your use case
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning) # Or target specific warnings if desired
        load_target_speaker_embedding(args.target_speaker)

    if target_speaker_embedding is not None:
        is_target, similarity_score = calculate_similarity(target_speaker_embedding, args.audio_file)
        print(f"\nAnalysis Result for {args.audio_file}:")
        print(f"  Is Target Speaker: {is_target}")
        print(f"  Similarity Score: {similarity_score:.4f}")
    else:
        print("\nCould not perform analysis as target speaker embedding was not loaded.")