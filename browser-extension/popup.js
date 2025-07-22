const startStopButton = document.getElementById('startStopButton');

chrome.runtime.sendMessage({ type: 'GET_STATE' }, (response) => {
  if (response && response.isCapturing) {
    startStopButton.textContent = 'Stop';
  } else {
    startStopButton.textContent = 'Start';
  }
});

startStopButton.addEventListener('click', () => {
  if (startStopButton.textContent === 'Start') {
    chrome.runtime.sendMessage({ type: 'START_CAPTURE' });
    startStopButton.textContent = 'Stop';
  } else {
    chrome.runtime.sendMessage({ type: 'STOP_CAPTURE' });
    startStopButton.textContent = 'Start';
  }
  window.close();
});
