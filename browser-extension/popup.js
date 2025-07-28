const startStopButton = document.getElementById('startStopButton');
const testMuteButton = document.getElementById('testMuteButton');

// Check initial capture state
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

// Listener for the main start/stop button
startStopButton.addEventListener('click', () => {
  if (startStopButton.textContent === 'Start') {
    chrome.runtime.sendMessage({ type: 'START_CAPTURE' }, () => {
      startStopButton.textContent = 'Stop';
      window.close();
    });
  } else {
    chrome.runtime.sendMessage({ type: 'STOP_CAPTURE' }, () => {
      startStopButton.textContent = 'Start';
      window.close();
    });
  }
});

// Listener for the new test mute button
testMuteButton.addEventListener('click', () => {
  console.log("Popup: Test Mute button clicked.");
  // Send a simple, direct message to the background script to mute the current tab
  chrome.runtime.sendMessage({ type: 'TEST_MUTE' });
  window.close();
});

// Listener for the enroll form
const enrollForm = document.getElementById('enrollForm');
const enrollStatus = document.getElementById('enrollStatus');

enrollForm.addEventListener('submit', (event) => {
  event.preventDefault();
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
});

const wipeDbButton = document.getElementById('wipeDbButton');

// Listener for the wipe database button
wipeDbButton.addEventListener('click', () => {
  if (confirm("Are you sure you want to wipe all enrolled speakers? This action cannot be undone.")) {
    enrollStatus.textContent = 'Wiping database...';
    enrollStatus.style.color = 'black';
    chrome.runtime.sendMessage({ type: 'WIPE_DB' });
  }
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === 'ENROLLMENT_STATUS') {
    if (request.status === 'success') {
      enrollStatus.textContent = request.message;
      enrollStatus.style.color = 'green';
      enrollForm.reset();
    } else {
      enrollStatus.textContent = `Error: ${request.message}`;
      enrollStatus.style.color = 'red';
    }
  } else if (request.type === 'WIPE_DB_STATUS') {
    if (request.status === 'success') {
      enrollStatus.textContent = request.message;
      enrollStatus.style.color = 'green';
    } else {
      enrollStatus.textContent = `Error: ${request.message}`;
      enrollStatus.style.color = 'red';
    }
  }
});
