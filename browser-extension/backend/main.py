from fastapi import FastAPI, WebSocket, Body, Query
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
def get_db_path(userId: str) -> str:
    """Returns the path to the user-specific database."""
    # Basic validation for userId to prevent path traversal issues
    if not userId or not all(c.isalnum() or c in '-_' for c in userId):
        raise ValueError("Invalid userId format.")
    return f"/app/browser-extension/backend/speakers_{userId}.db"

inference_model = None
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# Structure: { userId: { speaker_name: embedding_tensor } }
speaker_embeddings = {}

def initialize_db(db_path: str):
    """Initializes a new database with the required schema if it doesn't exist."""
    if os.path.exists(db_path):
        return
    print(f"Initializing new database at {db_path}...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        """)
        cursor.execute("""
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            speaker_id INTEGER NOT NULL,
            source_url TEXT,
            timestamp TEXT,
            embedding BLOB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (speaker_id) REFERENCES speakers (id)
        );
        """)
        cursor.execute("CREATE INDEX idx_speaker_name ON speakers (name);")
        cursor.execute("CREATE INDEX idx_source_speaker_id ON sources (speaker_id);")
        conn.commit()
    except sqlite3.Error as e:
        print(f"Failed to initialize database {db_path}: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def load_embeddings_for_user(userId: str):
    """
    Loads speaker embeddings for a specific user from their database.
    """
    global speaker_embeddings
    db_path = get_db_path(userId)
    
    initialize_db(db_path) # Ensure DB exists before loading

    user_specific_embeddings = {}
    print(f"Loading speaker embeddings for user {userId} from database: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, src.embedding
            FROM speakers s
            JOIN sources src ON s.id = src.speaker_id
        """)
        rows = cursor.fetchall()
        
        for speaker_name, embedding_blob in rows:
            try:
                embedding_npy = np.frombuffer(embedding_blob, dtype=np.float32)
                embedding_tensor = torch.from_numpy(embedding_npy).to(device)
                if embedding_tensor.dim() == 1:
                    embedding_tensor = embedding_tensor.unsqueeze(0)
                
                if speaker_name in user_specific_embeddings:
                    existing = user_specific_embeddings[speaker_name]
                    combined = torch.cat([existing, embedding_tensor], dim=0)
                    user_specific_embeddings[speaker_name] = combined.mean(dim=0, keepdim=True)
                else:
                    user_specific_embeddings[speaker_name] = embedding_tensor
            except Exception as e:
                print(f"Error loading embedding for {speaker_name} (user {userId}): {e}")
                
    except sqlite3.Error as e:
        print(f"Database error for user {userId}: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

    speaker_embeddings[userId] = user_specific_embeddings
    if not user_specific_embeddings:
        print(f"No speaker embeddings found for user {userId}.")
    else:
        print(f"Successfully loaded embeddings for {len(user_specific_embeddings)} speaker(s) for user {userId}.")


@app.on_event("startup")
async def startup_event():
    """
    Loads the pyannote model. User embeddings are loaded on-demand.
    """
    global inference_model
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

@app.get("/check-speaker/{speaker_name}")
async def check_speaker(speaker_name: str, userId: str = Query(...)):
    db_path = get_db_path(userId)
    initialize_db(db_path)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM speakers WHERE name = ?", (speaker_name,))
        speaker_row = cursor.fetchone()
        
        if not speaker_row:
            return {"exists": False, "sources": []}
        
        speaker_id = speaker_row[0]
        cursor.execute("SELECT source_url, timestamp FROM sources WHERE speaker_id = ?", (speaker_id,))
        sources = [{"url": url, "timestamp": ts} for url, ts in cursor.fetchall()]
        return {"exists": True, "sources": sources}
    except sqlite3.Error as e:
        return {"exists": False, "sources": [], "error": str(e)}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.post("/enroll")
async def enroll_speaker(payload: dict = Body(...)):
    userId = payload.get("userId")
    speaker_name = payload.get("name")
    youtube_url = payload.get("url")
    start_time = payload.get("start")
    end_time = payload.get("end")
    timestamp = f"{start_time}-{end_time}" if start_time and end_time else None

    if not userId or not speaker_name or not youtube_url:
        return {"status": "error", "message": "Missing userId, speaker name, or YouTube URL."}

    db_path = get_db_path(userId)
    initialize_db(db_path)

    temp_dir = "/app/browser-extension/backend/tmp"
    os.makedirs(temp_dir, exist_ok=True)
    downloaded_audio_path = os.path.join(temp_dir, f"{speaker_name}_{uuid.uuid4().hex}.wav")

    try:
        print(f"Downloading audio from {youtube_url} for speaker {speaker_name} (user {userId})...")
        command = [
            "yt-dlp", "-x", "--audio-format", "wav", "-o", downloaded_audio_path,
            "--force-keyframes-at-cuts"
        ]
        if timestamp:
            command.extend(["--download-sections", f"*{timestamp}"])
        command.append(youtube_url)
        
        subprocess.run(command, check=True, capture_output=True, text=True)
        print("Download complete.")

        print(f"Enrolling speaker {speaker_name} from {downloaded_audio_path} (user {userId})...")
        enroll_command = [
            "python3", "/app/scripts/enroll_speaker.py",
            "-n", speaker_name,
            "-i", downloaded_audio_path,
            "--url", youtube_url,
            "--db-path", db_path # Pass user-specific DB path
        ]
        if timestamp:
            enroll_command.extend(["--timestamp", timestamp])
        
        subprocess.run(enroll_command, check=True, capture_output=True, text=True)
        print("Enrollment script finished.")

        load_embeddings_for_user(userId)
        return {"status": "success", "message": f"Speaker {speaker_name} enrolled successfully."}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "message": f"Enrollment failed: {e.stderr}"}
    except Exception as e:
        return {"status": "error", "message": f"An unexpected error occurred: {e}"}
    finally:
        if os.path.exists(downloaded_audio_path):
            os.remove(downloaded_audio_path)

def is_target_speaker(audio_data: bytes, userId: str) -> tuple[bool, float]:
    if userId not in speaker_embeddings or not speaker_embeddings[userId] or inference_model is None:
        return False, 0.0

    user_embeddings = speaker_embeddings[userId]
    unique_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_prefix = f"[{timestamp}-{unique_id}]"
    saved_success_path = None
    max_similarity_score = 0.0

    try:
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="webm")
        audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)
        
        saved_success_filename = f"live_audio_{timestamp}_{unique_id}.wav"
        saved_success_path = os.path.join(SAVE_SUCCESS_AUDIO_DIR, saved_success_filename)
        audio_segment.export(saved_success_path, format="wav")

        live_audio_embedding_output = inference_model(saved_success_path)
        live_embedding_np = live_audio_embedding_output.data.mean(axis=0) if isinstance(live_audio_embedding_output, SlidingWindowFeature) else np.asarray(live_audio_embedding_output)
        live_audio_embedding = torch.from_numpy(live_embedding_np).to(device).unsqueeze(0)
        
        for speaker_name, enrolled_embedding in user_embeddings.items():
            similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, enrolled_embedding)
            similarity_score = similarity.item()
            max_similarity_score = max(max_similarity_score, similarity_score)
            
            THRESHOLD = 0.4
            if similarity_score > THRESHOLD:
                print(f"{log_prefix} MATCH: User {userId}, Speaker {speaker_name}, Similarity: {similarity_score:.4f}")
                return True, similarity_score

        print(f"{log_prefix} NO MATCH: User {userId}, Max Similarity: {max_similarity_score:.4f}")
        return False, max_similarity_score
    except Exception as e:
        print(f"ERROR {log_prefix}: Speaker detection failed for user {userId}: {e}")
        # Save problematic audio for debugging
        return False, 0.0
    finally:
        if saved_success_path and os.path.exists(saved_success_path):
            os.remove(saved_success_path)

@app.post("/wipe-db")
async def wipe_db(payload: dict = Body(...)):
    userId = payload.get("userId")
    if not userId:
        return {"status": "error", "message": "Missing userId."}
    
    db_path = get_db_path(userId)
    
    try:
        if userId in speaker_embeddings:
            speaker_embeddings[userId].clear()
            print(f"In-memory embeddings cleared for user {userId}.")

        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"Database file for user {userId} at {db_path} has been deleted.")

        initialize_db(db_path)
        print(f"Database for user {userId} re-initialized.")

        return {"status": "success", "message": f"Database for user {userId} wiped and reinitialized."}
    except Exception as e:
        print(f"An unexpected error occurred during DB wipe for user {userId}: {e}")
        return {"status": "error", "message": f"An unexpected error occurred: {e}"}

@app.delete("/speaker/{speaker_name}")
async def delete_speaker(speaker_name: str, userId: str = Query(...)):
    db_path = get_db_path(userId)
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM speakers WHERE name = ?", (speaker_name,))
        speaker_row = cursor.fetchone()
        
        if not speaker_row:
            return {"status": "error", "message": "Speaker not found."}
        
        speaker_id = speaker_row[0]
        cursor.execute("DELETE FROM sources WHERE speaker_id = ?", (speaker_id,))
        cursor.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,))
        conn.commit()
        
        load_embeddings_for_user(userId)
        return {"status": "success", "message": f"Speaker '{speaker_name}' deleted."}
    except sqlite3.Error as e:
        return {"status": "error", "message": f"Database error: {e}"}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.delete("/source")
async def delete_source(payload: dict = Body(...)):
    userId = payload.get("userId")
    speaker_name = payload.get("speakerName")
    source_url = payload.get("sourceUrl")
    timestamp = payload.get("timestamp")

    if not userId or not speaker_name or not source_url:
        return {"status": "error", "message": "Missing userId, speaker name, or source URL."}

    db_path = get_db_path(userId)
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM speakers WHERE name = ?", (speaker_name,))
        speaker_row = cursor.fetchone()
        
        if not speaker_row:
            return {"status": "error", "message": "Speaker not found."}
        
        speaker_id = speaker_row[0]
        
        if timestamp:
            cursor.execute("DELETE FROM sources WHERE speaker_id = ? AND source_url = ? AND timestamp = ?", (speaker_id, source_url, timestamp))
        else:
            cursor.execute("DELETE FROM sources WHERE speaker_id = ? AND source_url = ? AND timestamp IS NULL", (speaker_id, source_url))

        if cursor.rowcount == 0:
            return {"status": "error", "message": "Source not found."}

        conn.commit()
        load_embeddings_for_user(userId)
        return {"status": "success", "message": "Source deleted successfully."}
    except sqlite3.Error as e:
        return {"status": "error", "message": f"Database error: {e}"}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.get("/get-speakers")
async def get_speakers(userId: str = Query(...)):
    db_path = get_db_path(userId)
    initialize_db(db_path)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM speakers ORDER BY name ASC")
        speakers = [row[0] for row in cursor.fetchall()]
        return {"speakers": speakers}
    except sqlite3.Error as e:
        return {"speakers": [], "error": str(e)}
    finally:
        if 'conn' in locals() and conn:
            conn.close()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    print(f"WebSocket accepted for user {user_id}.")
    try:
        # Load user's embeddings on connection if not already loaded
        if user_id not in speaker_embeddings:
            load_embeddings_for_user(user_id)
            
        while True:
            data = await websocket.receive_bytes()
            is_target, similarity_score = is_target_speaker(data, user_id)
            response_data = {
                "action": "MUTE" if is_target else "UNMUTE",
                "similarity": round(similarity_score, 4),
                "isTargetSpeaker": is_target
            }
            await websocket.send_json(response_data)
    except Exception as e:
        print(f"WebSocket for user {user_id} closed unexpectedly or error: {e}")
    finally:
        # Clean up user's embeddings from memory on disconnect to save resources
        if user_id in speaker_embeddings:
            del speaker_embeddings[user_id]
            print(f"Cleaned up embeddings for user {user_id}.")

@app.get("/")
async def get():
    return HTMLResponse("<h1>FastAPI Pyannote Backend</h1><p>WebSocket endpoint is /ws/{user_id}</p>")
