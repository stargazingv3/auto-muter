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

document.addEventListener('DOMContentLoaded', () => {
  refreshSpeakerList();
});


// --- Event Listeners ---

startStopButton.addEventListener('click', () => {
  const action = startStopButton.textContent === 'Start' ? 'START_CAPTURE' : 'STOP_CAPTURE';
  chrome.runtime.sendMessage({ type: action }, () => {
    window.close();
  });
});

testMuteButton.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'TEST_MUTE' });
  window.close();
});

wipeDbButton.addEventListener('click', () => {
  if (confirm("Are you sure you want to wipe all enrolled speakers? This action cannot be undone.")) {
    enrollStatus.textContent = 'Wiping database...';
    enrollStatus.style.color = 'black';
    chrome.runtime.sendMessage({ type: 'WIPE_DB' });
  }
});

refreshSpeakersButton.addEventListener('click', refreshSpeakerList);

enrollForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const speakerName = document.getElementById('speakerName').value.trim();
  if (!speakerName) {
    showEnrollmentError("Speaker name cannot be empty.");
    return;
  }
  
  enrollStatus.textContent = `Checking for '${speakerName}'...`;
  enrollStatus.style.color = 'black';
  
  // Check if the speaker exists before enrolling
  chrome.runtime.sendMessage({ type: 'CHECK_SPEAKER', speakerName });
});

addSampleButton.addEventListener('click', () => {
  // User confirmed they want to add a sample to an existing speaker
  proceedWithEnrollment();
});

showSourcesButton.addEventListener('click', () => {
  // Toggle visibility of the sources list
  const isHidden = speakerSources.style.display === 'none';
  speakerSources.style.display = isHidden ? 'block' : 'none';
  showSourcesButton.textContent = isHidden ? 'Hide Sources' : 'Show Sources';
});

useDifferentNameButton.addEventListener('click', () => {
  // Hide the 'speaker exists' section and show the form again
  resetEnrollmentForm();
  document.getElementById('speakerName').focus();
});


// --- Message Handling ---

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  switch (request.type) {
    case 'ENROLLMENT_STATUS':
      handleEnrollmentStatus(request);
      break;
    case 'WIPE_DB_STATUS':
      handleWipeDbStatus(request);
      break;
    case 'ENROLLED_SPEAKERS_LIST':
      updateSpeakerList(request.speakers);
      break;
    case 'SPEAKER_CHECK_RESULT':
      handleSpeakerCheckResult(request);
      break;
  }
  return true; // Keep the message channel open for async responses
});


// --- UI and Logic Functions ---

function proceedWithEnrollment() {
  const speakerName = document.getElementById('speakerName').value;
  const youtubeUrl = document.getElementById('youtubeUrl').value;
  const startTime = document.getElementById('startTime').value;
  const endTime = document.getElementById('endTime').value;

  enrollStatus.textContent = 'Enrolling...';
  enrollStatus.style.color = 'black';

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
    showEnrollmentError(`Error checking speaker: ${request.error}`);
    return;
  }

  const speakerName = document.getElementById('speakerName').value.trim();

  if (request.exists) {
    // Speaker exists, show the confirmation UI
    enrollForm.style.display = 'none';
    speakerExistsSection.style.display = 'block';
    speakerExistsMessage.textContent = `A speaker named '${speakerName}' already exists.`;
    
    // Populate sources list
    speakerSourcesList.innerHTML = '';
    if (request.sources && request.sources.length > 0) {
      request.sources.forEach(source => {
        const li = document.createElement('li');
        let text = source.url || 'Unknown URL';
        if (source.timestamp) {
            text += ` (${source.timestamp})`;
        }
        li.textContent = text;
        speakerSourcesList.appendChild(li);
      });
    } else {
      const li = document.createElement('li');
      li.textContent = 'No sources found for this speaker.';
      speakerSourcesList.appendChild(li);
    }
    enrollStatus.textContent = ''; // Clear status

  } else {
    // Speaker does not exist, proceed directly with enrollment
    proceedWithEnrollment();
  }
}

function handleEnrollmentStatus(request) {
  if (request.status === 'success') {
    enrollStatus.textContent = request.message;
    enrollStatus.style.color = 'green';
    resetEnrollmentForm();
    refreshSpeakerList(); // Refresh the list after successful enrollment
  } else {
    showEnrollmentError(request.message);
  }
}

function handleWipeDbStatus(request) {
  if (request.status === 'success') {
    enrollStatus.textContent = request.message;
    enrollStatus.style.color = 'green';
  } else {
    enrollStatus.textContent = `Error: ${request.message}`;
    enrollStatus.style.color = 'red';
  }
  refreshSpeakerList(); // Refresh the list after wiping
}

function showEnrollmentError(message) {
  enrollStatus.textContent = `Error: ${message}`;
  enrollStatus.style.color = 'red';
}

function resetEnrollmentForm() {
  enrollForm.reset();
  enrollForm.style.display = 'block';
  speakerExistsSection.style.display = 'none';
  speakerSources.style.display = 'none';
  showSourcesButton.textContent = 'Show Sources';
  enrollStatus.textContent = '';
}

function refreshSpeakerList() {
  // This check is to prevent asking for a list that doesn't exist in the HTML yet
  if (speakerList) {
    chrome.runtime.sendMessage({ type: 'GET_ENROLLED_SPEAKERS' });
  }
}

function updateSpeakerList(speakers) {
  if (!speakerList) return;
  speakerList.innerHTML = ''; // Clear existing list
  if (speakers && speakers.length > 0) {
    speakers.forEach(speaker => {
      const li = document.createElement('li');
      li.textContent = speaker;
      speakerList.appendChild(li);
    });
  } else {
    const li = document.createElement('li');
    li.textContent = 'No speakers enrolled.';
    speakerList.appendChild(li);
  }
}