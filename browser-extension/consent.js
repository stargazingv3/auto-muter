document.getElementById('agreeButton').addEventListener('click', () => {
    // Set a flag in storage to indicate consent has been given
    chrome.storage.local.set({ 'userConsent': true }, () => {
        console.log('User consent has been recorded.');
        // After consent, you can either close the tab or redirect to the main popup
        // Closing the window is a common practice.
        window.close();
    });
});
