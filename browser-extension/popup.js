// --- Global Elements ---
const startStopButton = document.getElementById('startStopButton');
const enrollForm = document.getElementById('enrollForm');
const enrollStatus = document.getElementById('enrollStatus');
const wipeDbButton = document.getElementById('wipeDbButton');
const speakerList = document.getElementById('speakerList');
const refreshSpeakersButton = document.getElementById('refreshSpeakers');
const offlineModeToggle = document.getElementById('offlineModeToggle');

// --- Speaker Exists Section Elements ---
const speakerExistsSection = document.getElementById('speakerExistsSection');
const speakerExistsMessage = document.getElementById('speakerExistsMessage');
const speakerSources = document.getElementById('speakerSources');
const speakerSourcesList = document.getElementById('speakerSourcesList');
const addSampleButton = document.getElementById('addSampleButton');
const showSourcesButton = document.getElementById('showSourcesButton');
const useDifferentNameButton = document.getElementById('useDifferentNameButton');

// --- Initial State Setup ---
document.addEventListener('DOMContentLoaded', () => {
  // Get capture state
  chrome.runtime.sendMessage({ type: 'GET_STATE' }, (response) => {
    if (chrome.runtime.lastError) return console.error(chrome.runtime.lastError.message);
    if (response) updateCaptureButton(response.isCapturing);
  });

  // Get offline mode status
  chrome.runtime.sendMessage({ type: 'GET_OFFLINE_STATUS' }, (response) => {
    if (chrome.runtime.lastError) return console.error(chrome.runtime.lastError.message);
    if (response) updateOfflineModeUI(response.isOffline);
  });

  refreshSpeakerList();
});


// --- Event Listeners ---

startStopButton.addEventListener('click', () => {
  const action = startStopButton.textContent === 'Start' ? 'START_CAPTURE' : 'STOP_CAPTURE';
  chrome.runtime.sendMessage({ type: action }, (response) => {
    if (chrome.runtime.lastError) return console.error(chrome.runtime.lastError.message);
    if (response && response.error) {
        showStatus(response.error, 'red');
    } else {
        updateCaptureButton(action === 'START_CAPTURE');
        window.close();
    }
  });
});

wipeDbButton.addEventListener('click', () => {
  if (confirm("Are you sure you want to DELETE ALL YOUR DATA? This action cannot be undone.")) {
    showStatus('Deleting all data...', 'black');
    chrome.runtime.sendMessage({ type: 'WIPE_DB' });
  }
});

offlineModeToggle.addEventListener('change', () => {
    chrome.runtime.sendMessage({ type: 'TOGGLE_OFFLINE_MODE' }, (response) => {
        if (chrome.runtime.lastError) return console.error(chrome.runtime.lastError.message);
        if (response) updateOfflineModeUI(response.isOffline);
    });
});

refreshSpeakersButton.addEventListener('click', refreshSpeakerList);

enrollForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const speakerName = document.getElementById('speakerName').value.trim();
  if (!speakerName) {
    showStatus("Speaker name cannot be empty.", 'red');
    return;
  }
  showStatus(`Checking for '${speakerName}'...`, 'black');
  chrome.runtime.sendMessage({ type: 'CHECK_SPEAKER', speakerName });
});

addSampleButton.addEventListener('click', () => {
  proceedWithEnrollment();
});

showSourcesButton.addEventListener('click', () => {
  const isHidden = speakerSources.style.display === 'none';
  speakerSources.style.display = isHidden ? 'block' : 'none';
  showSourcesButton.textContent = isHidden ? 'Hide Sources' : 'Show Sources';
});

useDifferentNameButton.addEventListener('click', () => {
  resetEnrollmentForm();
  document.getElementById('speakerName').focus();
});


// --- Single, Consolidated Message Handler ---

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  console.log("Popup received message:", request.type, request);
  switch (request.type) {
    case 'ENROLLMENT_STATUS':
      handleEnrollmentStatus(request);
      break;
    case 'WIPE_DB_STATUS':
    case 'DELETE_STATUS':
      handleDeleteStatus(request);
      break;
    case 'ENROLLED_SPEAKERS_LIST':
      updateSpeakerList(request);
      break;
    case 'SPEAKER_CHECK_RESULT':
      handleSpeakerCheckResult(request);
      break;
  }
});


// --- UI and Logic Functions ---

function updateCaptureButton(isCapturing) {
    startStopButton.textContent = isCapturing ? 'Stop' : 'Start';
}

function updateOfflineModeUI(isOffline) {
    offlineModeToggle.checked = isOffline;
    // Disable most controls when in offline mode
    const elementsToDisable = [
        startStopButton,
        enrollForm,
        refreshSpeakersButton,
        ...speakerList.querySelectorAll('button')
    ];
    elementsToDisable.forEach(el => el.disabled = isOffline);
    if (isOffline) {
        showStatus('Offline mode is ON. No data is being sent.', 'blue');
        updateCaptureButton(false); // Show 'Start' but disabled
    } else {
        showStatus(''); // Clear status on going online
    }
}

function proceedWithEnrollment() {
  const speakerName = document.getElementById('speakerName').value;
  const youtubeUrl = document.getElementById('youtubeUrl').value;
  const startTime = document.getElementById('startTime').value;
  const endTime = document.getElementById('endTime').value;

  if (!youtubeUrl) {
      showStatus('YouTube URL is required.', 'red');
      return;
  }

  showStatus('Enrolling...', 'black');
  chrome.runtime.sendMessage({ 
    type: 'ENROLL_SPEAKER', 
    speakerName, 
    youtubeUrl,
    startTime,
    endTime
  });
}

function handleSpeakerCheckResult(request) {
  if (request.error) {
    showStatus(`Error: ${request.error}`, 'red');
    return;
  }

  const speakerName = document.getElementById('speakerName').value.trim();

  if (request.exists) {
    enrollForm.style.display = 'none';
    speakerExistsSection.style.display = 'block';
    speakerExistsMessage.textContent = `Speaker '${speakerName}' already exists.`;
    
    speakerSourcesList.innerHTML = '';
    if (request.sources && request.sources.length > 0) {
      request.sources.forEach(source => {
        const li = document.createElement('li');
        
        const textSpan = document.createElement('span');
        textSpan.textContent = `${source.url}` + (source.timestamp ? ` (${source.timestamp})` : '');
        textSpan.title = textSpan.textContent;
        
        const deleteBtn = document.createElement('button');
        deleteBtn.textContent = 'Delete';
        deleteBtn.className = 'small-button';
        deleteBtn.onclick = () => {
          if (confirm(`Delete this source?\n${textSpan.textContent}`)) {
            showStatus('Deleting source...', 'black');
            chrome.runtime.sendMessage({
              type: 'DELETE_SOURCE',
              speakerName: speakerName,
              sourceUrl: source.url,
              timestamp: source.timestamp
            });
          }
        };
        
        li.appendChild(textSpan);
        li.appendChild(deleteBtn);
        speakerSourcesList.appendChild(li);
      });
    } else {
      speakerSourcesList.innerHTML = '<li>No sources found for this speaker.</li>';
    }
    showStatus('');

  } else {
    proceedWithEnrollment();
  }
}

function handleEnrollmentStatus(request) {
  if (request.status === 'success') {
    showStatus(request.message, 'green');
    resetEnrollmentForm();
    refreshSpeakerList();
  } else {
    showStatus(`Error: ${request.message}`, 'red');
  }
}

function handleDeleteStatus(request) {
    if (request.status === 'success') {
        showStatus(request.message, 'green');
        resetEnrollmentForm();
        refreshSpeakerList();
    } else {
        showStatus(`Error: ${request.message}`, 'red');
    }
}

function showStatus(message, color = 'black') {
  enrollStatus.textContent = message;
  enrollStatus.style.color = color;
}

function resetEnrollmentForm() {
  enrollForm.reset();
  enrollForm.style.display = 'block';
  speakerExistsSection.style.display = 'none';
  speakerSources.style.display = 'none';
  showSourcesButton.textContent = 'Show Sources';
  showStatus('');
}

function refreshSpeakerList() {
  if (speakerList) {
    speakerList.innerHTML = '<li>Loading...</li>';
    chrome.runtime.sendMessage({ type: 'GET_ENROLLED_SPEAKERS' });
  }
}

function updateSpeakerList(request) {
  if (!speakerList) return;
  
  if (request.error) {
    speakerList.innerHTML = `<li>Error: ${request.error}</li>`;
    console.error("Error loading speaker list:", request.error);
    return;
  }

  const speakers = request.speakers;
  speakerList.innerHTML = '';
  if (speakers && speakers.length > 0) {
    speakers.forEach(speakerName => {
      const li = document.createElement('li');
      
      const textSpan = document.createElement('span');
      textSpan.textContent = speakerName;
      
      const deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.className = 'small-button';
      deleteBtn.onclick = () => {
        if (confirm(`Are you sure you want to delete the speaker '${speakerName}' and all their audio samples?`)) {
          showStatus(`Deleting '${speakerName}'...`, 'black');
          chrome.runtime.sendMessage({ type: 'DELETE_SPEAKER', speakerName });
        }
      };
      
      li.appendChild(textSpan);
      li.appendChild(deleteBtn);
      speakerList.appendChild(li);
    });
  } else {
    speakerList.innerHTML = '<li>No speakers enrolled.</li>';
  }
}

// --- Unique User ID Management ---
// This is now handled in the background script's onInstalled listener.
// The popup no longer needs to manage the user ID directly.
