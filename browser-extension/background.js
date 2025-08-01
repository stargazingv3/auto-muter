import { BACKEND_HOST, BACKEND_PORT } from './config.js';

// --- Installation and Consent ---
chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === 'install') {
    // Check for existing user ID, create if not found
    const { userId } = await chrome.storage.local.get('userId');
    if (!userId) {
      const newUserId = self.crypto.randomUUID();
      await chrome.storage.local.set({ userId: newUserId });
      console.log('New user ID generated:', newUserId);
    }
    
    // Set default offline mode to false
    await chrome.storage.local.set({ isOffline: false });

    // Open the consent page
    chrome.tabs.create({ url: 'consent.html' });
  }
});

// Helper function to get the user ID
async function getUserId() {
  const { userId } = await chrome.storage.local.get('userId');
  return userId;
}

// --- Main Message Listener ---
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  (async () => {
    // Check for consent before proceeding with most actions
    const { userConsent } = await chrome.storage.local.get('userConsent');
    if (!userConsent && ![
      'GET_STATE', 
      'GET_CONSENT_STATUS',
      'TOGGLE_OFFLINE_MODE',
      'GET_OFFLINE_STATUS'
      ].includes(request.type)) {
      console.log("Action blocked: User has not consented.");
      // Optionally, open the consent page again
      chrome.tabs.create({ url: 'consent.html' });
      sendResponse({ error: "User consent required." });
      return;
    }
    
    // Check for offline mode
    const { isOffline } = await chrome.storage.local.get('isOffline');
    if (isOffline && ![
      'GET_STATE', 
      'TOGGLE_OFFLINE_MODE', 
      'GET_OFFLINE_STATUS',
      'RESET_DB',
      'DELETE_USER_DATA'
      ].includes(request.type)) {
        console.log(`Action blocked: Extension is in offline mode. Type: ${request.type}`);
        sendResponse({ error: "Extension is in offline mode." });
        return;
    }

    switch (request.type) {
      case 'GET_STATE':
        const { isCapturing } = await chrome.storage.session.get("isCapturing");
        sendResponse({ isCapturing: !!isCapturing });
        break;
      case 'START_CAPTURE':
        await startCapture();
        sendResponse({ success: true });
        break;
      case 'STOP_CAPTURE':
        await stopCapture();
        sendResponse({ success: true });
        break;
      case 'SET_MUTE':
        await handleSetMute(request.mute);
        break;
      case 'TEST_MUTE':
        await handleTestMute();
        break;
      case 'ENROLL_SPEAKER':
        await enrollSpeaker(request.speakerName, request.youtubeUrl, request.startTime, request.endTime);
        break;
      case 'RESET_DB':
        await resetDatabase();
        break;
      case 'DELETE_USER_DATA':
        await deleteUserData();
        break;
      case 'CHECK_SPEAKER':
        await checkSpeaker(request.speakerName);
        break;
      case 'GET_ENROLLED_SPEAKERS':
        await getEnrolledSpeakers();
        break;

      case 'DELETE_SPEAKER':
        await deleteSpeaker(request.speakerName);
        break;
      case 'DELETE_SOURCE':
        await deleteSource(request.speakerName, request.sourceUrl, request.timestamp);
        break;
      case 'TOGGLE_OFFLINE_MODE':
        const { isOffline: newOfflineState } = await chrome.storage.local.get('isOffline');
        await chrome.storage.local.set({ isOffline: !newOfflineState });
        sendResponse({ isOffline: !newOfflineState });
        // If we are turning offline mode on, stop any active capture.
        if (!newOfflineState) {
          await stopCapture();
        }
        break;
      case 'GET_OFFLINE_STATUS':
        sendResponse({ isOffline });
        break;
    }
  })();

  return true; // Indicate async response
});

// --- Action Handlers ---

async function handleSetMute(mute) {
    console.log(`Background: Received SET_MUTE message. Mute: ${mute}`);
    try {
        const { targetTabId } = await chrome.storage.session.get("targetTabId");
        if (targetTabId) {
            await chrome.tabs.update(targetTabId, { muted: mute });
        } else {
            console.error("Background: Could not find targetTabId. Cannot set mute.");
        }
    } catch (error) {
        console.error(`Background: Error setting mute state: ${error}`);
    }
}

async function handleTestMute() {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab) {
            const newMuteState = !tab.mutedInfo.muted;
            await chrome.tabs.update(tab.id, { muted: newMuteState });
        }
    } catch (error) {
        console.error(`Background (Test): Error during test mute: ${error}`);
    }
}

async function deleteSpeaker(speakerName) {
  try {
    const userId = await getUserId();
    if (!userId) throw new Error("User ID not found.");
    const encodedSpeakerName = encodeURIComponent(speakerName);
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/speaker/${encodedSpeakerName}?userId=${userId}`, {
      method: 'DELETE',
    });
    const data = await response.json();
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', ...data });
  } catch (error) {
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', status: 'error', message: error.toString() });
  }
}

async function deleteSource(speakerName, sourceUrl, timestamp) {
  try {
    const userId = await getUserId();
    if (!userId) throw new Error("User ID not found.");
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/source`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speakerName, sourceUrl, timestamp, userId }),
    });
    const data = await response.json();
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', ...data });
  } catch (error) {
    chrome.runtime.sendMessage({ type: 'DELETE_STATUS', status: 'error', message: error.toString() });
  }
}

async function getEnrolledSpeakers() {
  try {
    const userId = await getUserId();
    if (!userId) throw new Error("User ID not found.");
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/get-speakers?userId=${userId}`);
    const data = await response.json();
    chrome.runtime.sendMessage({ type: 'ENROLLED_SPEAKERS_LIST', speakers: data.speakers || [] });
  } catch (error) {
    chrome.runtime.sendMessage({ type: 'ENROLLED_SPEAKERS_LIST', speakers: [], error: error.toString() });
  }
}

async function checkSpeaker(speakerName) {
  try {
    const userId = await getUserId();
    if (!userId) throw new Error("User ID not found.");
    const encodedSpeakerName = encodeURIComponent(speakerName);
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/check-speaker/${encodedSpeakerName}?userId=${userId}`);
    const data = await response.json();
    chrome.runtime.sendMessage({ type: 'SPEAKER_CHECK_RESULT', ...data });
  } catch (error) {
    chrome.runtime.sendMessage({ type: 'SPEAKER_CHECK_RESULT', exists: false, sources: [], error: error.toString() });
  }
}

async function resetDatabase() {
  try {
    const userId = await getUserId();
    if (!userId) throw new Error("User ID not found.");
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/reset-db`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId }),
    });
    const data = await response.json();
    chrome.runtime.sendMessage({ type: 'RESET_DB_STATUS', status: data.status, message: data.message });
  } catch (error) {
    chrome.runtime.sendMessage({ type: 'RESET_DB_STATUS', status: 'error', message: error.toString() });
  }
}

async function deleteUserData() {
  try {
    const userId = await getUserId();
    if (!userId) {
      // If there's no user ID, there's nothing on the server to delete.
      // Report success so the popup can proceed with local wipe.
      chrome.runtime.sendMessage({ type: 'DELETE_DATA_STATUS', status: 'success', message: 'No server data to delete.' });
      return;
    }

    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/delete-user-data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId }),
    });
    const data = await response.json();
    // Simply forward the backend's response to the popup
    chrome.runtime.sendMessage({ type: 'DELETE_DATA_STATUS', status: data.status, message: data.message });
  } catch (error) {
    console.error('Error deleting user data:', error);
    chrome.runtime.sendMessage({ type: 'DELETE_DATA_STATUS', status: 'error', message: error.toString() });
  }
}

async function enrollSpeaker(speakerName, youtubeUrl, startTime, endTime) {
  try {
    const userId = await getUserId();
    if (!userId) throw new Error("User ID not found.");
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/enroll`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: speakerName, url: youtubeUrl, start: startTime, end: endTime, userId }),
    });
    const data = await response.json();
    chrome.runtime.sendMessage({ type: 'ENROLLMENT_STATUS', status: data.status, message: data.message });
  } catch (error) {
    chrome.runtime.sendMessage({ type: 'ENROLLMENT_STATUS', status: 'error', message: error.toString() });
  }
}

async function startCapture() {
  const { isCapturing: capturing } = await chrome.storage.session.get("isCapturing");
  if (capturing) return;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  await chrome.storage.session.set({ targetTabId: tab.id, isCapturing: true });
  await setupOffscreenDocument(tab.id);
  console.log('Background: Capture started.');
}

async function stopCapture() {
  const { isCapturing: capturing } = await chrome.storage.session.get("isCapturing");
  if (!capturing) return;

  await chrome.storage.session.remove(["targetTabId", "isCapturing"]);
  await chrome.runtime.sendMessage({ type: 'stop-capture' });
  console.log('Background: Capture stopped.');
}

// --- Offscreen Document Setup ---
let creating; 
async function setupOffscreenDocument(tabId) {
  const existingContexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  const userId = await getUserId();

  if (existingContexts.length > 0) {
    chrome.runtime.sendMessage({ type: 'start-capture', streamId, userId });
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
    chrome.runtime.sendMessage({ type: 'start-capture', streamId, userId });
  }
}
