document.addEventListener('DOMContentLoaded', () => {
    const privacyContent = document.getElementById('privacy-content');

    // Fetch the privacy policy markdown file
    fetch('../PRIVACY.md')
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.text();
        })
        .then(text => {
            // A simple markdown to HTML converter
            const html = text
                .split('\n')
                .map(line => {
                    if (line.startsWith('## ')) {
                        return `<h2>${line.substring(3)}</h2>`;
                    }
                    if (line.startsWith('# ')) {
                        return `<h1>${line.substring(2)}</h1>`;
                    }
                    if (line.trim() === '') {
                        return '<br>';
                    }
                    return `<p>${line}</p>`;
                })
                .join('');
            privacyContent.innerHTML = html;
        })
        .catch(error => {
            console.error('Error fetching privacy policy:', error);
            privacyContent.innerHTML = '<p>Could not load the privacy policy. Please try again later.</p>';
        });
});
