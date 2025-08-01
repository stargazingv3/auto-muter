import os
import argparse
import torch
import numpy as np
from pyannote.audio import Inference
from pyannote.core import SlidingWindowFeature
from pydub import AudioSegment
from tqdm import tqdm
import tempfile
import sqlite3
import uuid

# --- Configuration ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")

# --- Database Configuration ---
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'backend', 'databases', 'speakers.db')

def convert_to_wav(audio_path, target_sr=16000):
    """
    Converts an audio file to a temporary WAV file with the target sample rate.
    Returns the path to the temporary WAV file.
    """
    try:
        audio = AudioSegment.from_file(audio_path)
        audio = audio.set_frame_rate(target_sr).set_channels(1)
        
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        audio.export(temp_wav.name, format="wav")
        return temp_wav.name
    except Exception as e:
        print(f"Warning: Could not process file {audio_path} with pydub. Skipping. Error: {e}")
        return None

def enroll_speaker_from_path(speaker_name, input_path, source_url, timestamp, db_path):
    """
    Generates a speaker embedding and registers the speaker in the database.
    The embedding is stored directly in the database as a BLOB.
    """
    if not os.path.exists(input_path):
        print(f"Error: Input path not found at {input_path}")
        return

    # --- Database Connection ---
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # --- Check if speaker already exists ---
    cursor.execute("SELECT id FROM speakers WHERE name = ?", (speaker_name,))
    speaker_row = cursor.fetchone()
    
    if speaker_row:
        print(f"Speaker '{speaker_name}' already exists. Adding new source to existing speaker.")
        speaker_id = speaker_row[0]
    else:
        print(f"Speaker '{speaker_name}' not found. Creating new speaker entry.")
        cursor.execute("INSERT INTO speakers (name) VALUES (?)", (speaker_name,))
        speaker_id = cursor.lastrowid
        print(f"New speaker '{speaker_name}' created with ID: {speaker_id}")

    # --- Model Loading ---
    print("Loading the speaker embedding model (pyannote/embedding)...")
    try:
        inference_model = Inference(
            "pyannote/embedding", 
            window="whole", 
            use_auth_token=HF_TOKEN
        )
        print("Model loaded successfully.")
    except Exception as e:
        print(f"Error loading model. Ensure you have a valid Hugging Face token. Error: {e}")
        conn.close()
        return

    # --- Audio File Processing ---
    temp_wav_path = None
    try:
        temp_wav_path = convert_to_wav(input_path)
        if temp_wav_path is None:
            raise ValueError("Failed to convert audio to WAV format.")

        embedding_output = inference_model(temp_wav_path)
        
        if isinstance(embedding_output, SlidingWindowFeature):
            embedding_np = embedding_output.data.mean(axis=0)
        else:
            embedding_np = np.asarray(embedding_output)

        # Convert numpy array to bytes for BLOB storage
        embedding_blob = embedding_np.tobytes()

        # --- Save Embedding and Record Source ---
        # Add the source information to the database, including the embedding blob
        cursor.execute(
            "INSERT INTO sources (speaker_id, source_url, timestamp, embedding) VALUES (?, ?, ?, ?)",
            (speaker_id, source_url, timestamp, embedding_blob)
        )
        conn.commit()
        print("Source information and embedding successfully recorded in the database.")

    except Exception as e:
        print(f"\nError during embedding generation or database operation: {e}")
        conn.rollback() # Rollback changes on error
    finally:
        if temp_wav_path and os.path.exists(temp_wav_path):
            os.remove(temp_wav_path)
        conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enroll a speaker by generating an embedding and registering in the database.")
    parser.add_argument(
        "-n", "--name", 
        type=str, 
        required=True, 
        help="The name of the speaker."
    )
    parser.add_argument(
        "-i", "--input_path", 
        type=str, 
        required=True, 
        help="Path to the audio file for enrollment."
    )
    parser.add_argument(
        "--url", 
        type=str, 
        help="Optional: The source URL of the audio (e.g., YouTube link)."
    )
    parser.add_argument(
        "--timestamp", 
        type=str, 
        help="Optional: The timestamp within the source URL (e.g., '0:15-1:22')."
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Path to the speaker database file."
    )
    
    args = parser.parse_args()
    
    enroll_speaker_from_path(args.name, args.input_path, args.url, args.timestamp, args.db_path)
