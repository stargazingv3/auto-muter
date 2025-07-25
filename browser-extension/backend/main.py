from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import random
import torch
from pyannote.audio import Inference
import io
import os
from pydub import AudioSegment
from datetime import datetime
import uuid
import shutil # Import shutil for file copying
from pyannote.core import SlidingWindowFeature # Import SlidingWindowFeature

# --- Configuration for saving error audio ---
SAVE_ERROR_AUDIO_DIR = "/app/error_audio_dumps" # Adjust this path as needed
# For Docker, ensure this path is either a volume mount or created in Dockerfile
# Create the directory if it doesn't exist
os.makedirs(SAVE_ERROR_AUDIO_DIR, exist_ok=True)
print(f"ERROR AUDIO DUMP DIRECTORY: {SAVE_ERROR_AUDIO_DIR}") # Confirm path at startup

# --- Configuration for saving successful audio ---
SAVE_SUCCESS_AUDIO_DIR = "/app/success_audio_dumps" # New directory for successful decodes
os.makedirs(SAVE_SUCCESS_AUDIO_DIR, exist_ok=True)
print(f"SUCCESS AUDIO DUMP DIRECTORY: {SAVE_SUCCESS_AUDIO_DIR}") # Confirm path at startup


# --- Existing App Setup ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")

app = FastAPI()

# MODIFIED: Add window="whole" to Inference
inference_model = Inference("pyannote/embedding", device=torch.device("cuda" if torch.cuda.is_available() else "cpu"), use_auth_token=HF_TOKEN, window="whole")

TARGET_SPEAKER_MP3 = "/app/browser-extension/backend/target_speaker.mp3"
target_speaker_embedding = None

async def load_target_speaker_embedding():
    global target_speaker_embedding
    if not os.path.exists(TARGET_SPEAKER_MP3):
        print(f"Error: Target speaker MP3 not found at {TARGET_SPEAKER_MP3}")
        target_speaker_embedding = None
        return

    try:
        print(f"Attempting to load target speaker embedding from {TARGET_SPEAKER_MP3}...")
        embedding_output = inference_model(TARGET_SPEAKER_MP3)
        # Handle different output types from inference_model
        if isinstance(embedding_output, SlidingWindowFeature):
            target_speaker_embedding = torch.from_numpy(embedding_output.data).mean(axis=0, keepdim=True).to(inference_model.device)
        elif isinstance(embedding_output, torch.Tensor):
            target_speaker_embedding = embedding_output.to(inference_model.device)
        else: # Handle case if it's a numpy array directly
            target_speaker_embedding = torch.from_numpy(embedding_output).to(inference_model.device)

        # Ensure the embedding is 2D (batch_size, embedding_dim)
        if target_speaker_embedding.dim() == 1:
            target_speaker_embedding = target_speaker_embedding.unsqueeze(0)

        print("Target speaker embedding loaded successfully.")
    except Exception as e:
        print(f"Error loading target speaker embedding: {e}")
        target_speaker_embedding = None

@app.on_event("startup")
async def startup_event():
    await load_target_speaker_embedding()

# --- MODIFIED is_target_speaker function ---
def is_target_speaker(audio_data: bytes) -> tuple[bool, float]:
    """
    Uses the ML model to detect the target speaker after converting
    the incoming audio data (e.g., WebM) to WAV format in memory.
    Saves the incoming raw audio data if decoding or processing fails.
    Also saves successfully decoded and processed WAV audio.
    """
    if target_speaker_embedding is None:
        print("Target speaker embedding not loaded. Cannot perform detection.")
        return False, 0.0

    # Generate a unique ID for this audio chunk for logging and saving
    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_prefix = f"[{timestamp}-{unique_id}]"

    saved_success_path = None # Initialize to None

    try:
        print(f"{log_prefix} Received {len(audio_data)} bytes for processing.")

        # --- Attempt pydub conversion from raw bytes ---
        # Assuming the incoming audio_data is WebM (opus) from MediaRecorder.
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        print(f"{log_prefix} pydub conversion successful. Length: {audio_segment.duration_seconds:.2f}s")

        # 2. Resample and set channels if necessary for pyannote.audio
        # pyannote/embedding model typically expects 16kHz mono audio.
        if audio_segment.frame_rate != 16000 or audio_segment.channels != 1:
            print(f"{log_prefix} Resampling audio from {audio_segment.frame_rate}Hz, {audio_segment.channels} channels to 16000Hz, 1 channel.")
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)

        # 3. Export to WAV format directly to a file
        saved_success_filename = f"success_decode_processed_audio_{timestamp}_{unique_id}.wav"
        saved_success_path = os.path.join(SAVE_SUCCESS_AUDIO_DIR, saved_success_filename)
        audio_segment.export(saved_success_path, format="wav")
        print(f"{log_prefix} Audio exported to WAV file: {saved_success_path}")


        # 4. Compute embedding for the live audio chunk using the SAVED WAV file
        live_audio_embedding_output = inference_model(saved_success_path)
        print(f"{log_prefix} Embedding computed for live audio from saved file.")

        # --- FIX START: Handle possible SlidingWindowFeature output and ensure tensor dimensions ---
        if isinstance(live_audio_embedding_output, SlidingWindowFeature):
            live_audio_embedding = torch.from_numpy(live_audio_embedding_output.data).mean(axis=0, keepdim=True).to(inference_model.device)
            print(f"{log_prefix} Converted SlidingWindowFeature to Tensor. Shape: {live_audio_embedding.shape}")
        elif isinstance(live_audio_embedding_output, torch.Tensor):
            live_audio_embedding = live_audio_embedding_output.to(inference_model.device)
        else:
            live_audio_embedding = torch.from_numpy(live_audio_embedding_output).to(inference_model.device)
            print(f"{log_prefix} Converted numpy array to Tensor. Shape: {live_audio_embedding.shape}")

        # Ensure both embeddings have the same number of dimensions (e.g., [1, D])
        if live_audio_embedding.dim() == 1:
            live_audio_embedding = live_audio_embedding.unsqueeze(0)
        # target_speaker_embedding should already be unsqueezed from load_target_speaker_embedding
        # but a defensive check here doesn't hurt, though it might indicate an issue there if it triggers.
        if target_speaker_embedding.dim() == 1:
            target_speaker_embedding_for_comparison = target_speaker_embedding.unsqueeze(0)
        else:
            target_speaker_embedding_for_comparison = target_speaker_embedding
        # --- FIX END ---


        # 5. Compare embeddings using cosine similarity
        similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, target_speaker_embedding_for_comparison)
        
        # Log the similarity item here, after it's calculated
        print(f"{log_prefix} Similarity for live audio: {similarity.item():.4f}")

        # 6. Define a threshold for detection. This will likely need tuning.
        THRESHOLD = 0.65 # Tunable: lower if missing target, higher if too many false positives

        is_target = similarity.item() > THRESHOLD
        print(f"{log_prefix} Similarity: {similarity.item():.4f}, Is Target: {is_target}")
        return is_target, similarity.item()

    except Exception as e:
        print(f"ERROR {log_prefix}: Speaker detection failed (pydub conversion or inference): {e}")
        print(f"ERROR {log_prefix}: Saving the problematic raw audio data for investigation.")

        try:
            # Construct a descriptive filename for the error dump
            saved_error_filename = f"failed_decode_raw_audio_{timestamp}_{unique_id}.webm" # Assume webm, adjust if needed
            saved_error_path = os.path.join(SAVE_ERROR_AUDIO_DIR, saved_error_filename)

            # Save the raw bytes directly
            with open(saved_error_path, "wb") as f:
                f.write(audio_data)
            print(f"ERROR {log_prefix}: Problematic raw audio data saved to: {saved_error_path}")

        except Exception as save_e:
            print(f"CRITICAL ERROR {log_prefix}: Failed to save problematic audio file: {save_e}")

        return False, 0.0
    finally:
        # Clean up the successfully processed WAV file if you don't need to keep it
        # For debugging, you might want to comment this out initially.
        if saved_success_path and os.path.exists(saved_success_path):
            try:
                os.remove(saved_success_path)
                print(f"{log_prefix} Cleaned up temporary WAV file: {saved_success_path}")
            except Exception as cleanup_e:
                print(f"WARNING {log_prefix}: Failed to remove temporary WAV file: {cleanup_e}")


# --- Remaining App Endpoints ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket accepted.")
    try:
        while True:
            data = await websocket.receive_bytes()
            is_target, similarity_score = is_target_speaker(data)
            response_data = {
                "action": "MUTE" if is_target else "UNMUTE",
                "similarity": round(similarity_score, 4), # Round for cleaner output
                "isTargetSpeaker": is_target
            }
            await websocket.send_json(response_data)
    except Exception as e:
        print(f"WebSocket closed unexpectedly or error: {e}")
    finally:
        pass

@app.get("/")
async def get():
    return HTMLResponse("<h1>FastAPI Pyannote Backend</h1><p>WebSocket endpoint is /ws</p>")