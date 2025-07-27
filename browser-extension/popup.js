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
enrollForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const speakerName = document.getElementById('speakerName').value;
  const youtubeUrl = document.getElementById('youtubeUrl').value;
  chrome.runtime.sendMessage({ type: 'ENROLL_SPEAKER', speakerName, youtubeUrl });
  window.close();
});
