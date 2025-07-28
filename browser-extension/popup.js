// --- Global Elements ---
const startStopButton = document.getElementById('startStopButton');
const testMuteButton = document.getElementById('testMuteButton');
const enrollForm = document.getElementById('enrollForm');
const enrollStatus = document.getElementById('enrollStatus');
const wipeDbButton = document.getElementById('wipeDbButton');
const speakerList = document.getElementById('speakerList');
const refreshSpeakersButton = document.getElementById('refreshSpeakers');

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
  chrome.runtime.sendMessage({ type: 'GET_STATE' }, (response) => {
    if (chrome.runtime.lastError) {
      console.error(chrome.runtime.lastError.message);
      return;
    }
    if (response && response.isCapturing) {
      startStopButton.textContent = 'Stop';
    } else {
      startStopButton.textContent = 'Start';
    }
  });
  refreshSpeakerList();
});


// --- Event Listeners ---

startStopButton.addEventListener('click', () => {
  const action = startStopButton.textContent === 'Start' ? 'START_CAPTURE' : 'STOP_CAPTURE';
  chrome.runtime.sendMessage({ type: action }, () => window.close());
});

testMuteButton.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'TEST_MUTE' }, () => window.close());
});

wipeDbButton.addEventListener('click', () => {
  if (confirm("Are you sure you want to WIPE THE ENTIRE DATABASE? This action cannot be undone.")) {
    showStatus('Wiping database...', 'black');
    chrome.runtime.sendMessage({ type: 'WIPE_DB' });
  }
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
        textSpan.title = textSpan.textContent; // Full text on hover
        
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
        resetEnrollmentForm(); // Also reset the form in case we were in the middle of checking a speaker
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
    speakerList.innerHTML = '<li>Error loading list.</li>';
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