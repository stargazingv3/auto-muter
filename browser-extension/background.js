let isCapturing = false;

// Main message listener
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  // Use a an async IIFE (Immediately Invoked Function Expression) to handle async logic
  // This is a common pattern for keeping the top-level of the listener synchronous
  // to avoid issues with the service worker.
  (async () => {
    if (request.type === 'GET_STATE') {
      const { isCapturing: capturing } = await chrome.storage.session.get("isCapturing");
      sendResponse({ isCapturing: !!capturing });
    } else if (request.type === 'START_CAPTURE') {
      await startCapture();
      sendResponse({ success: true });
    } else if (request.type === 'STOP_CAPTURE') {
      await stopCapture();
      sendResponse({ success: true });
    } else if (request.type === 'SET_MUTE') {
      console.log(`Background: Received SET_MUTE message. Mute: ${request.mute}`);
      try {
        const { targetTabId } = await chrome.storage.session.get("targetTabId");
        console.log(`Background: Retrieved targetTabId from storage: ${targetTabId}`);

        if (targetTabId) {
          console.log(`Background: Attempting to update mute state for tab ${targetTabId} to ${request.mute}`);
          await chrome.tabs.update(targetTabId, { muted: request.mute });

          if (chrome.runtime.lastError) {
            console.error(`Background: Error setting mute state: ${chrome.runtime.lastError.message}`);
          } else {
            console.log(`Background: Successfully updated mute state for tab ${targetTabId}.`);
          }
        } else {
          console.error("Background: Could not find targetTabId in session storage. Cannot set mute state.");
        }
      } catch (error) {
        console.error(`Background: An unexpected error occurred while setting mute state: ${error}`);
      }
    } else if (request.type === 'TEST_MUTE') {
      console.log("Background: Received TEST_MUTE request.");
      try {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length > 0) {
          const tabToMute = tabs[0];
          // Toggle mute state for testing
          const newMuteState = !tabToMute.mutedInfo.muted;
          await chrome.tabs.update(tabToMute.id, { muted: newMuteState });
          console.log(`Background (Test): Successfully toggled mute for tab ${tabToMute.id} to ${newMuteState}`);
        } else {
          console.error("Background (Test): No active tab found.");
        }
      } catch (error) {
        console.error(`Background (Test): Error during test mute: ${error}`);
      }
    } else if (request.type === 'ENROLL_SPEAKER') {
      console.log("Background: Received ENROLL_SPEAKER request.");
      enrollSpeaker(request.speakerName, request.youtubeUrl, request.startTime, request.endTime);
    } else if (request.type === 'WIPE_DB') {
      console.log("Background: Received WIPE_DB request.");
      wipeDatabase();
    } else if (request.type === 'CHECK_SPEAKER') {
      console.log("Background: Received CHECK_SPEAKER request for", request.speakerName);
      checkSpeaker(request.speakerName);
    } else if (request.type === 'GET_ENROLLED_SPEAKERS') {
      console.log("Background: Received GET_ENROLLED_SPEAKERS request.");
      getEnrolledSpeakers();
    } else if (request.type === 'DELETE_SPEAKER') {
      console.log("Background: Received DELETE_SPEAKER request for", request.speakerName);
      deleteSpeaker(request.speakerName);
    } else if (request.type === 'DELETE_SOURCE') {
      console.log("Background: Received DELETE_SOURCE request for", request.speakerName);
      deleteSource(request.speakerName, request.sourceUrl, request.timestamp);
    }
  })();

  // Return true to indicate that we will respond asynchronously.
  return true;
});

async function deleteSpeaker(speakerName) {
  try {
    const encodedSpeakerName = encodeURIComponent(speakerName);
    const response = await fetch(`http://localhost:8000/speaker/${encodedSpeakerName}`, {
      method: 'DELETE',
    });
    const data = await response.json();
    console.log('Delete speaker response:', data);
    // Forward the status to the popup
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', ...data });
  } catch (error) {
    console.error('Error deleting speaker:', error);
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', status: 'error', message: error.toString() });
  }
}

async function deleteSource(speakerName, sourceUrl, timestamp) {
  try {
    const response = await fetch('http://localhost:8000/source', {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ speakerName, sourceUrl, timestamp }),
    });
    const data = await response.json();
    console.log('Delete source response:', data);
    // Forward the status to the popup
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', ...data });
  } catch (error) {
    console.error('Error deleting source:', error);
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', status: 'error', message: error.toString() });
  }
}

async function getEnrolledSpeakers() {
  try {
    const response = await fetch('http://localhost:8000/get-speakers');
    const data = await response.json();
    console.log('Get enrolled speakers response:', data);
    chrome.runtime.sendMessage({ type: 'ENROLLED_SPEAKERS_LIST', speakers: data.speakers || [] });
  } catch (error) {
    console.error('Error getting enrolled speakers:', error);
    chrome.runtime.sendMessage({ type: 'ENROLLED_SPEAKERS_LIST', speakers: [], error: error.toString() });
  }
}

async function checkSpeaker(speakerName) {
  try {
    // URL-encode the speaker name to handle spaces or special characters
    const encodedSpeakerName = encodeURIComponent(speakerName);
    const response = await fetch(`http://localhost:8000/check-speaker/${encodedSpeakerName}`);
    const data = await response.json();
    console.log('Check speaker response:', data);
    // Forward the response from the backend to the popup
    chrome.runtime.sendMessage({ type: 'SPEAKER_CHECK_RESULT', ...data });
  } catch (error) {
    console.error('Error checking speaker:', error);
    // Send an error message back to the popup
    chrome.runtime.sendMessage({ type: 'SPEAKER_CHECK_RESULT', exists: false, sources: [], error: error.toString() });
  }
}

async function wipeDatabase() {
  try {
    const response = await fetch('http://localhost:8000/wipe-db', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });
    const data = await response.json();
    console.log('Wipe DB response:', data);
    chrome.runtime.sendMessage({ type: 'WIPE_DB_STATUS', status: data.status, message: data.message });
  } catch (error) {
    console.error('Error wiping database:', error);
    chrome.runtime.sendMessage({ type: 'WIPE_DB_STATUS', status: 'error', message: error.toString() });
  }
}

async function enrollSpeaker(speakerName, youtubeUrl, startTime, endTime) {
  try {
    const response = await fetch('http://localhost:8000/enroll', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: speakerName,
        url: youtubeUrl,
        start: startTime,
        end: endTime,
      }),
    });
    const data = await response.json();
    console.log('Enrollment response:', data);
    chrome.runtime.sendMessage({ type: 'ENROLLMENT_STATUS', status: data.status, message: data.message });
  } catch (error) {
    console.error('Error enrolling speaker:', error);
    chrome.runtime.sendMessage({ type: 'ENROLLMENT_STATUS', status: 'error', message: error.toString() });
  }
}

async function startCapture() {
  const { isCapturing: capturing } = await chrome.storage.session.get("isCapturing");
  if (capturing) {
    console.log('Capture is already in progress.');
    return;
  }

  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs.length === 0) {
    console.error('No active tab found.');
    return;
  }
  const targetTabId = tabs[0].id;

  // Save state to session storage
  await chrome.storage.session.set({ targetTabId: targetTabId, isCapturing: true });

  await setupOffscreenDocument(targetTabId);
  console.log('Background: Capture started.');
}

async function stopCapture() {
  const { isCapturing: capturing } = await chrome.storage.session.get("isCapturing");
  if (!capturing) {
    console.log('Capture is not in progress.');
    return;
  }

  // Clean up storage
  await chrome.storage.session.remove(["targetTabId", "isCapturing"]);

  // The offscreen document will close itself when capture stops.
  await chrome.runtime.sendMessage({ type: 'stop-capture' });
  console.log('Background: Capture stopped.');
}

// --- Offscreen Document Setup ---
let creating; // A global promise to avoid racing createDocument calls
async function setupOffscreenDocument(tabId) {
  const existingContexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT']
  });

  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });

  if (existingContexts.length > 0) {
    chrome.runtime.sendMessage({ type: 'start-capture', streamId: streamId });
    return;
  }

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
    chrome.runtime.sendMessage({ type: 'start-capture', streamId: streamId });
  }
}