let mediaRecorder;
let socket;
let audioContext;

chrome.runtime.onMessage.addListener(async (message) => {
  if (message.type === 'start-capture') {
    await startCapture(message.streamId);
  } else if (message.type === 'stop-capture') {
    stopCapture();
  }
});

async function startCapture(streamId) {
  if (!streamId) {
    console.error('Offscreen: No stream ID received.');
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
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
    socket.onopen = () => console.log('Offscreen: WebSocket connection opened.');
    socket.onmessage = (event) => {
      console.log('Offscreen: Message from server:', event.data);
      // Send mute/unmute command to the background script
      chrome.runtime.sendMessage({ type: 'SET_MUTE', mute: event.data === 'MUTE' });
    };
    socket.onclose = () => console.log('Offscreen: WebSocket connection closed.');
    socket.onerror = (error) => console.error('Offscreen: WebSocket error:', error);

    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
        socket.send(event.data);
      }
    };
    mediaRecorder.start(1000);
    console.log('Offscreen: Audio capture started.');

    stream.oninactive = () => {
        console.log('Offscreen: Stream inactive.');
        stopCapture();
    };
  } catch (error) {
    console.error('Offscreen: Error starting capture:', error);
  }
}

function stopCapture() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (socket) {
    socket.close();
  }
  if (audioContext) {
    audioContext.close();
  }
  console.log('Offscreen: Audio capture stopped.');
  // This will close the offscreen document.
  window.close();
}