let mediaRecorder;
let socket;
let audioContext;
let gainNode; // Our "volume knob"
let isCapturing = false;
let stream;

chrome.runtime.onMessage.addListener(async (message) => {
  if (message.type === 'start-capture') {
    if (isCapturing) return;
    await startCapture(message.streamId);
  } else if (message.type === 'stop-capture') {
    await stopCapture();
  }
});

async function startCapture(streamId) {
  if (!streamId) {
    console.error('Offscreen: No stream ID received.');
    return;
  }

  isCapturing = true;
  console.log('Offscreen: Starting audio capture...');

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId
        }
      },
      video: false
    });

    // --- NEW: Set up the audio graph with a GainNode for muting ---
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    gainNode = audioContext.createGain(); // Create the volume control
    source.connect(gainNode); // Connect source to the volume control
    gainNode.connect(audioContext.destination); // Connect volume control to speakers

    // Connect to backend for processing
    socket = new WebSocket('ws://localhost:8000/ws');
    socket.onopen = () => {
      console.log('Offscreen: WebSocket connection opened.');
      recordAndSend();
    };
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('Offscreen: Message from server:', data);

      // --- NEW: Control the volume directly ---
      if (data.action === 'MUTE') {
        gainNode.gain.value = 0;
        console.log("Offscreen: Muted audio via GainNode.");
      } else {
        gainNode.gain.value = 1;
        console.log("Offscreen: Unmuted audio via GainNode.");
      }
    };
    socket.onclose = () => console.log('Offscreen: WebSocket connection closed.');
    socket.onerror = (error) => console.error('Offscreen: WebSocket error:', error);

    stream.oninactive = () => {
        console.log('Offscreen: Stream inactive.');
        stopCapture();
    };
  } catch (error) {
    console.error('Offscreen: Error starting capture:', error);
    isCapturing = false;
  }
}

function recordAndSend() {
  if (!isCapturing || !stream) return;

  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
  const chunks = [];

  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };

  mediaRecorder.onstop = () => {
    if (socket.readyState === WebSocket.OPEN && chunks.length > 0) {
      const blob = new Blob(chunks, { type: 'audio/webm;codecs=opus' });
      socket.send(blob);
    }
    if (isCapturing) {
      setTimeout(recordAndSend, 100);
    }
  };

  mediaRecorder.start();
  setTimeout(() => {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
    }
  }, 1000);
}

async function stopCapture() {
  if (!isCapturing) return;
  isCapturing = false;
  console.log('Offscreen: Stopping audio capture...');

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (socket) socket.close();
  if (audioContext) await audioContext.close();
  if (stream) stream.getTracks().forEach(track => track.stop());

  console.log('Offscreen: Audio capture stopped.');
  window.close();
}