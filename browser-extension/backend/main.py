from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import random
import torch
from pyannote.audio import Inference
import io
import os

HF_TOKEN = os.getenv("HF_AUTH_TOKEN")

app = FastAPI()

# Initialize pyannote.audio inference model
inference_model = Inference("pyannote/embedding", device=torch.device("cuda" if torch.cuda.is_available() else "cpu"), use_auth_token=HF_TOKEN)

TARGET_SPEAKER_MP3 = "./browser-extension/backend/target_speaker.mp3"
target_speaker_embedding = None

async def load_target_speaker_embedding():
    global target_speaker_embedding
    try:
        # Load the target speaker audio and compute its embedding
        target_speaker_embedding = inference_model(TARGET_SPEAKER_MP3)
        print("Target speaker embedding loaded successfully.")
    except Exception as e:
        print(f"Error loading target speaker embedding: {e}")
        target_speaker_embedding = None

# Load the embedding when the application starts
@app.on_event("startup")
async def startup_event():
    await load_target_speaker_embedding()

def is_target_speaker(audio_data: bytes) -> bool:
    """
    This function will now use the ML model to detect the target speaker.
    """
    if target_speaker_embedding is None:
        print("Target speaker embedding not loaded. Cannot perform detection.")
        return False

    try:
        # Convert bytes to a file-like object for pyannote.audio
        audio_file = io.BytesIO(audio_data)
        
        # Compute embedding for the live audio chunk
        live_audio_embedding = inference_model(audio_file)

        # Compare embeddings (e.g., using cosine similarity)
        # pyannote.audio provides a `cosine_similarity` function or you can implement it manually
        similarity = torch.nn.functional.cosine_similarity(live_audio_embedding, target_speaker_embedding)
        
        # Define a threshold for detection. This will likely need tuning.
        THRESHOLD = 0.7 # Example threshold

        is_target = similarity.item() > THRESHOLD
        print(f"Similarity: {similarity.item():.4f}, Is Target: {is_target}")
        return is_target
    except Exception as e:
        print(f"Error during speaker detection: {e}")
        return False

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_bytes()
        # print(f"Received {len(data)} bytes of audio data") # Commented to reduce log spam
        if is_target_speaker(data):
            await websocket.send_text("MUTE")
        else:
            await websocket.send_text("UNMUTE")

