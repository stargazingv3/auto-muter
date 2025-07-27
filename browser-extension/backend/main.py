from fastapi import FastAPI, WebSocket, Body
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import torch
import numpy as np
from pyannote.audio import Inference
from pyannote.core import SlidingWindowFeature
import io
import os
from pydub import AudioSegment
from datetime import datetime
import uuid
import subprocess
import sqlite3

# --- Configuration for saving audio ---
SAVE_ERROR_AUDIO_DIR = "/app/error_audio_dumps"
os.makedirs(SAVE_ERROR_AUDIO_DIR, exist_ok=True)
print(f"ERROR AUDIO DUMP DIRECTORY: {SAVE_ERROR_AUDIO_DIR}")

SAVE_SUCCESS_AUDIO_DIR = "/app/success_audio_dumps"
os.makedirs(SAVE_SUCCESS_AUDIO_DIR, exist_ok=True)
print(f"SUCCESS AUDIO DUMP DIRECTORY: {SAVE_SUCCESS_AUDIO_DIR}")

# --- App and Model Setup ---
HF_TOKEN = os.getenv("HF_AUTH_TOKEN")
if not HF_TOKEN:
    print("WARNING: HF_AUTH_TOKEN environment variable not set. Model might not load.")

app = FastAPI()

# Add CORS middleware to allow requests from the extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# --- Database and Model Setup ---
DB_PATH = "/app/browser-extension/backend/speakers.db"
inference_model = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
speaker_embeddings = {}

def load_model_and_embeddings():
    """Loads the pyannote model and all enrolled speaker embeddings from the database."""
    global inference_model, speaker_embeddings
    
    # Load the pyannote model
    print("Loading the speaker embedding model (pyannote/embedding)...")
    try:
        inference_model = Inference(
            "pyannote/embedding", 
            window="whole", 
            use_auth_token=HF_TOKEN,
            device=device
        )
        print("Pyannote model loaded successfully.")
    except Exception as e:
        print(f"CRITICAL: Failed to load pyannote model: {e}")
        raise

    # Load speaker embeddings from the database
    speaker_embeddings.clear()
    print(f"Loading speaker embeddings from database: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. No speakers will be loaded.")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Query for all speakers and their associated embedding paths
        cursor.execute("""
            SELECT s.name, src.embedding_path
            FROM speakers s
            JOIN sources src ON s.id = src.speaker_id
        """)
        
        rows = cursor.fetchall()
        
        for speaker_name, embedding_path in rows:
            if not os.path.exists(embedding_path):
                print(f"Warning: Embedding file not found for {speaker_name} at {embedding_path}. Skipping.")
                continue
            
            try:
                embedding_npy = np.load(embedding_path)
                embedding_tensor = torch.from_numpy(embedding_npy).to(device)
                
                if embedding_tensor.dim() == 1:
                    embedding_tensor = embedding_tensor.unsqueeze(0)
                
                # If speaker already has embeddings, average them.
                if speaker_name in speaker_embeddings:
                    existing_embedding = speaker_embeddings[speaker_name]
                    combined_embedding = torch.cat([existing_embedding, embedding_tensor], dim=0)
                    speaker_embeddings[speaker_name] = combined_embedding.mean(dim=0, keepdim=True)
                else:
                    speaker_embeddings[speaker_name] = embedding_tensor
                
                print(f"- Loaded embedding for speaker: {speaker_name} from {embedding_path}")
            except Exception as e:
                print(f"Error loading embedding for {speaker_name} from {embedding_path}: {e}")
                
    except sqlite3.Error as e:
        print(f"Database error while loading speakers: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

    if not speaker_embeddings:
        print("No speaker embeddings found in the database.")
    else:
        print(f"Successfully loaded {len(speaker_embeddings)} speaker(s).")

@app.on_event("startup")
async def startup_event():
    load_model_and_embeddings()

@app.post("/enroll")
async def enroll_speaker(payload: dict = Body(...)):
    speaker_name = payload.get("name")
    youtube_url = payload.get("url")
    start_time = payload.get("start")
    end_time = payload.get("end")
    timestamp = f"{start_time}-{end_time}" if start_time and end_time else None

    if not speaker_name or not youtube_url:
        return {"status": "error", "message": "Missing speaker name or YouTube URL."}

    # --- Check for existing speaker name ---
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM speakers WHERE name = ?", (speaker_name,))
        if cursor.fetchone():
            # For now, we allow adding more sources to an existing speaker.
            # The UI can be updated to reflect this is an "add more samples" action.
            pass
    except sqlite3.Error as e:
        return {"status": "error", "message": f"Database error: {e}"}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

    temp_dir = "/app/browser-extension/backend/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    downloaded_audio_path = os.path.join(temp_dir, f"{speaker_name}_{uuid.uuid4().hex}.wav")

    try:
        print(f"Downloading audio from {youtube_url} for speaker {speaker_name}...")
        command = [
            "yt-dlp", "-x", "--audio-format", "wav",
            "-o", downloaded_audio_path,
            "--force-keyframes-at-cuts"
        ]
        if timestamp:
            command.extend(["--download-sections", f"*{timestamp}"])
        command.append(youtube_url)
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in iter(process.stdout.readline, ''):
            print(line, end='')
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)
        print("Download complete.")

        print(f"Enrolling speaker {speaker_name} from {downloaded_audio_path}...")
        enroll_command = [
            "python3", "/app/scripts/enroll_speaker.py",
            "-n", speaker_name,
            "-i", downloaded_audio_path,
            "--url", youtube_url
        ]
        if timestamp:
            enroll_command.extend(["--timestamp", timestamp])
        
        # Capture stderr for better error reporting
        result = subprocess.run(enroll_command, check=True, capture_output=True, text=True)
        print("Enrollment script finished.")
        print("Enrollment script stdout:", result.stdout)
        print("Enrollment script stderr:", result.stderr)


        # Reload embeddings to include the new one
        load_model_and_embeddings()

        return {"status": "success", "message": f"Speaker {speaker_name} enrolled successfully."}

    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else "No stderr captured."
        print(f"Enrollment subprocess error: {error_output}")
        return {"status": "error", "message": f"Enrollment failed: {error_output}"}
    except Exception as e:
        print(f"An unexpected error occurred during enrollment: {e}")
        return {"status": "error", "message": f"An unexpected error occurred: {e}"}
    finally:
        if os.path.exists(downloaded_audio_path):
            os.remove(downloaded_audio_path)

# --- REVERTED is_target_speaker function ---
def is_target_speaker(audio_data: bytes) -> tuple[bool, float]:
    """
    Uses the pyannote model to detect any of the target speakers from incoming audio.
    """
    if not speaker_embeddings or inference_model is None:
        if not speaker_embeddings:
            print("No speaker embeddings loaded. Cannot perform detection.")
        if inference_model is None:
            print("Model not loaded. Cannot perform detection.")
        return False, 0.0

    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_prefix = f"[{timestamp}-{unique_id}]"
    saved_success_path = None
    max_similarity_score = 0.0

    try:
        # 1. Convert incoming WebM audio to a processable format
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        
        # 2. Resample to 16kHz mono audio
        if audio_segment.frame_rate != 16000 or audio_segment.channels != 1:
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)

        # 3. Export to a temporary WAV file for processing
        saved_success_filename = f"live_audio_{timestamp}_{unique_id}.wav"
        saved_success_path = os.path.join(SAVE_SUCCESS_AUDIO_DIR, saved_success_filename)
        audio_segment.export(saved_success_path, format="wav")

        # 4. Compute embedding for the live audio chunk
        live_audio_embedding_output = inference_model(saved_success_path)

        if isinstance(live_audio_embedding_output, SlidingWindowFeature):
            live_embedding_np = live_audio_embedding_output.data.mean(axis=0)
        else:
            live_embedding_np = np.asarray(live_audio_embedding_output)

        live_audio_embedding = torch.from_numpy(live_embedding_np).to(device)
        
        if live_audio_embedding.dim() == 1:
            live_audio_embedding = live_audio_embedding.unsqueeze(0)
        
        # 5. Compare live embedding against all enrolled speakers
        for speaker_name, enrolled_embedding in speaker_embeddings.items():
            similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, enrolled_embedding)
            similarity_score = similarity.item()
            
            if similarity_score > max_similarity_score:
                max_similarity_score = similarity_score

            # 6. Check against threshold
            THRESHOLD = 0.4 # This may need tuning
            if similarity_score > THRESHOLD:
                print(f"{log_prefix} MATCH: Detected speaker {speaker_name} with similarity: {similarity_score:.4f}")
                return True, similarity_score

        print(f"{log_prefix} NO MATCH: Max similarity was {max_similarity_score:.4f}")
        return False, max_similarity_score

    except Exception as e:
        print(f"ERROR {log_prefix}: Speaker detection failed: {e}")
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
@app.post("/wipe-db")
async def wipe_db():
    """
    Wipes the entire speaker database and reinitializes it.
    """
    global speaker_embeddings
    DB_PATH = "/app/browser-extension/backend/speakers.db"
    SPEAKERS_DIR = "/app/browser-extension/backend/speakers"

    try:
        # 1. Clear in-memory embeddings
        speaker_embeddings.clear()
        print("In-memory speaker embeddings cleared.")

        # 2. Delete all .npy files
        if os.path.exists(SPEAKERS_DIR):
            for npy_file in os.listdir(SPEAKERS_DIR):
                if npy_file.endswith(".npy"):
                    os.remove(os.path.join(SPEAKERS_DIR, npy_file))
            print("All .npy embedding files have been deleted.")

        # 3. Delete the database file
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
            print(f"Database file at {DB_PATH} has been deleted.")

        # 4. Re-initialize the database by running the script
        print("Re-initializing the database...")
        init_script_path = "/app/scripts/initialize_database.py"
        result = subprocess.run(
            ["python3", init_script_path],
            check=True,
            capture_output=True,
            text=True
        )
        print("Database re-initialization script output:", result.stdout)
        
        # 5. Reload the (now empty) embeddings
        load_model_and_embeddings()

        return {"status": "success", "message": "Database wiped and reinitialized successfully."}
    except FileNotFoundError:
        return {"status": "error", "message": "Database file not found, could not delete."}
    except subprocess.CalledProcessError as e:
        print(f"Error re-initializing database: {e.stderr}")
        return {"status": "error", "message": f"Failed to re-initialize database: {e.stderr}"}
    except Exception as e:
        print(f"An unexpected error occurred during DB wipe: {e}")
        return {"status": "error", "message": f"An unexpected error occurred: {e}"}

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