# Privacy Policy for Auto Muter Extension

**Last Updated:** 2025-07-31

This Privacy Policy describes how the Auto Muter browser extension ("the Extension") collects, uses, and handles your data. Your privacy is important to us, and we are committed to protecting it.

## 1. What data we collect and why

The core function of Auto Muter is to automatically mute a browser tab when a specific, pre-determined person is speaking. To achieve this, the Extension needs to process audio data.

### a. Data You Provide for Enrollment

*   **Speaker Name and YouTube URL/Timestamps:** To enroll a speaker, you provide their name and one or more YouTube URLs (with optional start/end times) containing their voice. We use this information to download audio samples.
*   **Voice Embeddings (Voice Prints):** We process these audio samples to create a mathematical representation of the speaker's voice, called an embedding or "voice print". This embedding is stored on our server and is associated with a unique, anonymous user ID. **We do not store the raw audio files from enrollment.**

### b. Data Processed During Active Use

*   **Live Audio Snippets:** When the Extension is active on a tab, it captures short snippets of audio from that tab. These snippets are streamed to our server for real-time analysis.
*   **Purpose of Processing:** The audio snippets are immediately compared against the enrolled voice embeddings. If a match is found, the Extension mutes the tab.
*   **Data Retention:** **Live audio snippets are processed in-memory and are NOT stored on our server.** They are discarded immediately after analysis.

### c. Anonymous User ID

*   To keep your enrolled speakers separate from those of other users, the Extension generates a random, anonymous User ID when it is first installed. This ID is stored locally in your browser's storage and is sent with every request to our server. It contains no personal information and cannot be used to identify you.

## 2. How we use your data

*   **To Provide Core Functionality:** We use the voice embeddings you create and the live audio from your tabs to detect the target speaker and mute the audio accordingly.
*   **For Troubleshooting:** In cases of processing errors, we may temporarily save the problematic audio snippet to diagnose and fix issues with the service. This data is not associated with your user ID and is deleted after analysis.

## 3. Data Storage and Security

*   **Voice Embeddings:** Your enrolled voice embeddings are stored in a dedicated, separate database file on our server, identified only by your anonymous user ID.
*   **Security:** We take reasonable measures to protect the data stored on our servers from unauthorized access.

## 4. User Control and Data Deletion

You have full control over your data. The Extension's popup provides the following options:

*   **Offline Mode:** You can disable the Extension at any time using the toggle in the popup. When disabled, no audio data is captured or sent to the server.
*   **Delete a Speaker:** You can delete any enrolled speaker, which will remove their voice embeddings from our server.
*   **Delete All My Data:** You can permanently delete all your data. This is a two-step process:
        1.  First, the extension sends a request to our server to delete your entire user database, including all enrolled voice embeddings.
        2.  Once the server confirms deletion, the extension will then clear its own local storage in your browser, removing your anonymous User ID and consent status.
    This action is irreversible and fully resets the extension. All controls in the popup will be disabled until you close and reopen it, which will trigger the first-time consent screen again.

## 5. Data Sharing

We do not share, sell, or rent your data to any third parties. All data collected is used exclusively to provide and improve the functionality of the Auto Muter Extension.

## 6. Changes to this Policy

We may update this Privacy Policy from time to time. We will notify you of any significant changes by displaying a notice within the Extension.

## 7. Contact Us

If you have any questions about this Privacy Policy, please open an issue on our [GitHub repository](https://github.com/ikon/auto-muter).
