document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('uploadForm');
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file');
    const fileNameDisplay = document.getElementById('fileName');
    const submitBtn = document.getElementById('submitBtn');
    
    const statusArea = document.getElementById('statusArea');
    const resultArea = document.getElementById('resultArea');
    const errorArea = document.getElementById('errorArea');
    
    // Status elements
    const statusText = document.getElementById('statusText');
    const downloadBtn = document.getElementById('downloadBtn');
    
    let currentJobId = null;
    let pollInterval = null;

    // Drag and drop events
    dropzone.addEventListener('click', () => fileInput.click());
    
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            fileInput.files = e.dataTransfer.files;
            updateFileName();
        }
    });

    fileInput.addEventListener('change', updateFileName);

    function updateFileName() {
        if (fileInput.files.length > 0) {
            fileNameDisplay.textContent = fileInput.files[0].name;
            submitBtn.disabled = false;
        } else {
            fileNameDisplay.textContent = '';
            submitBtn.disabled = true;
        }
    }

    // Form submission
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!fileInput.files[0]) return;

        const formData = new FormData(form);
        
        // Update UI
        form.classList.add('hidden');
        statusArea.classList.remove('hidden');
        statusText.textContent = 'Uploading...';

        try {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/upload', true);
            
            xhr.onload = function() {
                if (xhr.status >= 200 && xhr.status < 300) {
                    const response = JSON.parse(xhr.responseText);
                    currentJobId = response.job_id;
                    startPolling();
                } else {
                    let msg = 'Unknown error';
                    try {
                        msg = JSON.parse(xhr.responseText).error;
                    } catch(e) {}
                    showError("Upload failed: " + msg);
                }
            };
            
            xhr.onerror = function() {
                showError("Network error during upload.");
            };
            
            xhr.send(formData);

        } catch (error) {
            showError(error.message);
        }
    });

    function startPolling() {
        statusText.textContent = 'Processing (applying FFmpeg filters)...';
        
        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/status/${currentJobId}`);
                if (!res.ok) throw new Error("Failed to get status");
                
                const data = await res.json();
                
                if (data.status === 'completed') {
                    clearInterval(pollInterval);
                    showSuccess(data.output_url);
                } else if (data.status === 'failed') {
                    clearInterval(pollInterval);
                    showError(data.error);
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 2000);
    }

    function showSuccess(downloadUrl) {
        statusArea.classList.add('hidden');
        resultArea.classList.remove('hidden');
        downloadBtn.href = downloadUrl;
    }

    function showError(message) {
        statusArea.classList.add('hidden');
        form.classList.add('hidden');
        errorArea.classList.remove('hidden');
        document.getElementById('errorMsg').textContent = message;
    }

    // Reset handlers
    function resetApp() {
        resultArea.classList.add('hidden');
        errorArea.classList.add('hidden');
        form.classList.remove('hidden');
        fileInput.value = '';
        updateFileName();
        currentJobId = null;
    }

    document.getElementById('resetBtn').addEventListener('click', resetApp);
    document.getElementById('errorResetBtn').addEventListener('click', resetApp);
});
