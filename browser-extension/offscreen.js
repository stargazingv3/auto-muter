let mediaRecorder;
let socket;

chrome.runtime.onMessage.addListener(async (message) => {
  if (message.type === 'start-capture') {
    await startCapture(message.tabId);
  } else if (message.type === 'stop-capture') {
    stopCapture();
  }
});

async function startCapture(tabId) {
  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId
        }
      },
      video: false
    });

    // Connect to backend for processing
    socket = new WebSocket('ws://localhost:8000/ws');
    socket.onopen = () => console.log('Offscreen: WebSocket connection opened.');
    socket.onmessage = (event) => console.log('Offscreen: Message from server:', event.data);
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
  console.log('Offscreen: Audio capture stopped.');
  // This will close the offscreen document.
  window.close();
}
