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

# --- Configuration for saving error audio ---
SAVE_ERROR_AUDIO_DIR = "/app/error_audio_dumps" # Adjust this path as needed
# For Docker, ensure this path is either a volume mount or created in Dockerfile
# Create the directory if it doesn't exist
os.makedirs(SAVE_ERROR_AUDIO_DIR, exist_ok=True)
print(f"ERROR AUDIO DUMP DIRECTORY: {SAVE_ERROR_AUDIO_DIR}") # Confirm path at startup

# --- Existing App Setup ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")

app = FastAPI()

inference_model = Inference("pyannote/embedding", device=torch.device("cuda" if torch.cuda.is_available() else "cpu"), use_auth_token=HF_TOKEN)

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
        target_speaker_embedding = inference_model(TARGET_SPEAKER_MP3)
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
    """
    if target_speaker_embedding is None:
        print("Target speaker embedding not loaded. Cannot perform detection.")
        return False, 0.0

    # Generate a unique ID for this audio chunk for logging and saving
    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_prefix = f"[{timestamp}-{unique_id}]"

    try:
        print(f"{log_prefix} Received {len(audio_data)} bytes for processing.")

        # --- Attempt pydub conversion from raw bytes ---
        # Assuming the incoming audio_data is WebM (opus) from MediaRecorder.
        # This is the line that's causing the "Decoding failed" error.
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        print(f"{log_prefix} pydub conversion successful. Length: {audio_segment.duration_seconds:.2f}s")

        # 2. Resample and set channels if necessary for pyannote.audio
        # pyannote/embedding model typically expects 16kHz mono audio.
        if audio_segment.frame_rate != 16000 or audio_segment.channels != 1:
            print(f"{log_prefix} Resampling audio from {audio_segment.frame_rate}Hz, {audio_segment.channels} channels to 16000Hz, 1 channel.")
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)

        # 3. Export to WAV format in an in-memory BytesIO object
        wav_file_in_memory = io.BytesIO()
        audio_segment.export(wav_file_in_memory, format="wav")
        wav_file_in_memory.seek(0) # Rewind the buffer to the beginning
        print(f"{log_prefix} Audio exported to WAV in memory.")

        # 4. Compute embedding for the live audio chunk using the WAV data
        live_audio_embedding = inference_model(wav_file_in_memory)
        print(f"{log_prefix} Embedding computed for live audio.")

        # 5. Compare embeddings using cosine similarity
        similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, target_speaker_embedding)

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