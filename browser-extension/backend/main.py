from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import torch
import torchaudio
import numpy as np
from speechbrain.pretrained import EncoderClassifier
import io
import os
from pydub import AudioSegment
from datetime import datetime
import uuid

# --- Configuration for saving audio ---
SAVE_ERROR_AUDIO_DIR = "/app/error_audio_dumps"
os.makedirs(SAVE_ERROR_AUDIO_DIR, exist_ok=True)
print(f"ERROR AUDIO DUMP DIRECTORY: {SAVE_ERROR_AUDIO_DIR}")

SAVE_SUCCESS_AUDIO_DIR = "/app/success_audio_dumps"
os.makedirs(SAVE_SUCCESS_AUDIO_DIR, exist_ok=True)
print(f"SUCCESS AUDIO DUMP DIRECTORY: {SAVE_SUCCESS_AUDIO_DIR}")

# --- App and Model Setup ---
app = FastAPI()

# --- NEW: SpeechBrain Model Setup ---
# This model must match the one used in the enrollment script.
classifier = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

ENROLLED_SPEAKER_NPY = "/app/browser-extension/backend/enrolled_speaker.npy"
target_speaker_embedding = None

def load_model_and_embedding():
    """Loads the SpeechBrain model and the enrolled speaker embedding."""
    global classifier, target_speaker_embedding
    
    # Load the SpeechBrain model
    print("Loading the speaker embedding model (speechbrain/spkrec-ecapa-voxceleb)...")
    try:
        classifier = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=os.path.join("/tmp", "pretrained_models", "ecapa-tdnn") # Cache model
        )
        classifier.to(device)
        classifier.eval() # Set model to evaluation mode
        print("SpeechBrain model loaded successfully.")
    except Exception as e:
        print(f"CRITICAL: Failed to load SpeechBrain model: {e}")
        # The application can't function without the model.
        # In a real-world scenario, you might want to handle this more gracefully.
        raise

    # Load the pre-computed speaker embedding
    if not os.path.exists(ENROLLED_SPEAKER_NPY):
        print(f"Error: Enrolled speaker embedding not found at {ENROLLED_SPEAKER_NPY}")
        print("Please run the enrollment script first.")
        target_speaker_embedding = None
        return

    try:
        print(f"Attempting to load enrolled speaker embedding from {ENROLLED_SPEAKER_NPY}...")
        embedding_npy = np.load(ENROLLED_SPEAKER_NPY)
        target_speaker_embedding = torch.from_numpy(embedding_npy).to(device)
        
        # Ensure the embedding is 2D [1, D] for cosine similarity
        if target_speaker_embedding.dim() == 1:
            target_speaker_embedding = target_speaker_embedding.unsqueeze(0)
            
        print("Enrolled speaker embedding loaded successfully.")
    except Exception as e:
        print(f"Error loading enrolled speaker embedding: {e}")
        target_speaker_embedding = None

@app.on_event("startup")
async def startup_event():
    load_model_and_embedding()

# --- UPDATED is_target_speaker function ---
def is_target_speaker(audio_data: bytes) -> tuple[bool, float]:
    """
    Uses a SpeechBrain model to detect the target speaker from incoming audio.
    """
    if target_speaker_embedding is None or classifier is None:
        print("Target speaker embedding or model not loaded. Cannot perform detection.")
        return False, 0.0

    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_prefix = f"[{timestamp}-{unique_id}]"
    saved_success_path = None

    try:
        print(f"{log_prefix} Received {len(audio_data)} bytes for processing.")

        # 1. Convert incoming WebM audio to a processable format
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        print(f"{log_prefix} pydub conversion successful. Length: {audio_segment.duration_seconds:.2f}s")

        # 2. Resample to 16kHz mono audio, as required by the SpeechBrain model
        if audio_segment.frame_rate != 16000 or audio_segment.channels != 1:
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)

        # 3. Export to a temporary WAV file to be read by torchaudio
        saved_success_filename = f"live_audio_{timestamp}_{unique_id}.wav"
        saved_success_path = os.path.join(SAVE_SUCCESS_AUDIO_DIR, saved_success_filename)
        audio_segment.export(saved_success_path, format="wav")

        # 4. Compute embedding for the live audio chunk using SpeechBrain
        with torch.no_grad():
            waveform = classifier.load_audio(saved_success_path, savedir="/tmp")
            live_audio_embedding = classifier.encode_batch(waveform)
            # Squeeze to remove batch and channel dimensions [1, 1, D] -> [D]
            live_audio_embedding = live_audio_embedding.squeeze()

        # Ensure the embedding is 2D for comparison
        if live_audio_embedding.dim() == 1:
            live_audio_embedding = live_audio_embedding.unsqueeze(0)
        
        # 5. Compare embeddings using cosine similarity
        similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, target_speaker_embedding)
        similarity_score = similarity.item()
        
        print(f"{log_prefix} Similarity for live audio: {similarity_score:.4f}")

        # 6. Define a threshold for detection. This will likely need tuning.
        # SpeechBrain embeddings are different from pyannote's. A good starting
        # point is often higher, around 0.5-0.7, but this requires testing.
        THRESHOLD = 0.5 

        is_target = similarity_score > THRESHOLD
        print(f"{log_prefix} Similarity: {similarity_score:.4f}, Is Target: {is_target}")
        return is_target, similarity_score

    except Exception as e:
        print(f"ERROR {log_prefix}: Speaker detection failed: {e}")
        # Save the problematic raw audio for debugging
        error_filename = f"failed_raw_audio_{timestamp}_{unique_id}.webm"
        error_path = os.path.join(SAVE_ERROR_AUDIO_DIR, error_filename)
        with open(error_path, "wb") as f:
            f.write(audio_data)
        print(f"ERROR {log_prefix}: Problematic raw audio saved to: {error_path}")
        return False, 0.0
    finally:
        # Clean up the temporary WAV file
        if saved_success_path and os.path.exists(saved_success_path):
            try:
                os.remove(saved_success_path)
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
                "similarity": round(similarity_score, 4),
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
