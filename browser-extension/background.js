let isCapturing = false;
let targetTabId;

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'GET_STATE') {
    sendResponse({ isCapturing });
    return true; // Keep the message channel open for async response
  }

  if (request.type === 'START_CAPTURE') {
    startCapture();
  } else if (request.type === 'STOP_CAPTURE') {
    stopCapture();
  } else if (request.type === 'SET_MUTE') {
    if (targetTabId) {
      chrome.tabs.update(targetTabId, { muted: request.mute });
      console.log(`Background: Tab ${targetTabId} mute state set to ${request.mute}`);
    }
  }
  return true;
});

async function startCapture() {
  if (isCapturing) {
    console.log('Capture is already in progress.');
    return;
  }

  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs.length === 0) {
    console.error('No active tab found.');
    return;
  }
  targetTabId = tabs[0].id;

  await setupOffscreenDocument(targetTabId);
  isCapturing = true;
  console.log('Background: Capture started.');
}

async function stopCapture() {
  if (!isCapturing) {
    console.log('Capture is not in progress.');
    return;
  }
  // The offscreen document will close itself when capture stops.
  await chrome.runtime.sendMessage({ type: 'stop-capture' });
  isCapturing = false;
  console.log('Background: Capture stopped.');
}

let creating; // A global promise to avoid racing createDocument calls
async function setupOffscreenDocument(tabId) {
  // Check if we have an existing offscreen document.
  const existingContexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT']
  });

  // Get the stream ID from the service worker.
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });

  if (existingContexts.length > 0) {
    // Send a message to the existing document to start capture.
    chrome.runtime.sendMessage({ type: 'start-capture', streamId: streamId });
    return;
  }

  // Avoid race conditions with creating the document.
  if (creating) {
    await creating;
  } else {
    creating = chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'To capture tab audio for speaker identification.'
    });
    await creating;
    creating = null;
    // Now that the document is created, send the start message.
    chrome.runtime.sendMessage({ type: 'start-capture', streamId: streamId });
  }
}

