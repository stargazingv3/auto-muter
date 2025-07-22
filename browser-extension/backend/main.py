from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_bytes()
        print(f"Received {len(data)} bytes of audio data")
        # TODO: Process audio data and send back mute/unmute commands
        await websocket.send_text(f"Received {len(data)} bytes")

