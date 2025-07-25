let mediaRecorder;
let socket;
let audioContext;
let isCapturing = false; // Use a flag to control the recording loop
let stream; // Keep a reference to the stream

chrome.runtime.onMessage.addListener(async (message) => {
  if (message.type === 'start-capture') {
    // Prevent starting multiple capture loops
    if (isCapturing) {
      console.log("Offscreen: Capture is already in progress.");
      return;
    }
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

    // Play the captured audio back to the user
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    source.connect(audioContext.destination);

    // Connect to backend for processing
    socket = new WebSocket('ws://localhost:8000/ws');
    socket.onopen = () => {
      console.log('Offscreen: WebSocket connection opened.');
      // Start the recording loop once the socket is open
      recordAndSend();
    };
    socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log('Offscreen: Message from server:', data);
      const muteState = data.action === 'MUTE';
      console.log(`Offscreen: Sending SET_MUTE message to background. Mute: ${muteState}`);
      chrome.runtime.sendMessage({ type: 'SET_MUTE', mute: muteState });
    };
    socket.onclose = () => console.log('Offscreen: WebSocket connection closed.');
    socket.onerror = (error) => console.error('Offscreen: WebSocket error:', error);

    stream.oninactive = () => {
        console.log('Offscreen: Stream inactive.');
        stopCapture();
    };
  } catch (error) {
    console.error('Offscreen: Error starting capture:', error);
    isCapturing = false; // Reset state on error
  }
}

function recordAndSend() {
  // Stop the loop if capture has been stopped
  if (!isCapturing || !stream) {
    return;
  }

  mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
  const chunks = [];

  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) {
      chunks.push(event.data);
    }
  };

  mediaRecorder.onstop = () => {
    if (socket.readyState === WebSocket.OPEN && chunks.length > 0) {
      const blob = new Blob(chunks, { type: 'audio/webm;codecs=opus' });
      socket.send(blob);
      console.log(`Offscreen: Sent ${blob.size} byte chunk.`);
    }
    // Schedule the next recording cycle.
    // This creates a continuous loop of 1-second recordings.
    if (isCapturing) {
      setTimeout(recordAndSend, 100); // Small delay to allow event loop to breathe
    }
  };

  mediaRecorder.start();
  console.log("Offscreen: Started 1-second recording.");

  // Stop the recording after 1 second to finalize the chunk
  setTimeout(() => {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
    }
  }, 1000);
}

async function stopCapture() {
  if (!isCapturing) {
    return;
  }
  isCapturing = false;
  console.log('Offscreen: Stopping audio capture...');

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    // This will trigger the final onstop, but the loop won't continue
    mediaRecorder.stop();
  }
  if (socket) {
    socket.close();
  }
  if (audioContext) {
    await audioContext.close();
  }
  if (stream) {
      stream.getTracks().forEach(track => track.stop());
  }

  console.log('Offscreen: Audio capture stopped.');
  // This will close the offscreen document.
  window.close();
}
