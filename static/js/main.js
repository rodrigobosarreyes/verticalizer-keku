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
    const progressPercent = document.getElementById('progressPercent');
    const etaText = document.getElementById('etaText');
    const progressBar = document.getElementById('progressBar');
    const downloadBtn = document.getElementById('downloadBtn');
    const elapsedTimeDisplay = document.getElementById('elapsedTimeDisplay');
    
    let currentJobId = null;
    let pollInterval = null;
    
    // Clips dynamic UI
    const clipsList = document.getElementById('clipsList');
    const addClipBtn = document.getElementById('addClipBtn');
    const splitDurationParam = document.getElementById('splitDurationParam');
    
    function createClipRow() {
        const row = document.createElement('div');
        row.className = 'clip-row';
        row.innerHTML = `
            <input type="text" class="clip-start" placeholder="Start (e.g. 1:30)" title="Start Time">
            <span>to</span>
            <input type="text" class="clip-end" placeholder="End (e.g. 2:15)" title="End Time">
            <button type="button" class="remove-clip-btn" title="Remove">&times;</button>
        `;
        
        row.querySelector('.remove-clip-btn').addEventListener('click', () => {
            row.remove();
        });
        return row;
    }

    if (addClipBtn) {
        addClipBtn.addEventListener('click', () => {
            clipsList.appendChild(createClipRow());
        });
    }

    // Helper: Convert "MM:SS" or "HH:MM:SS" or "10m" or "600s" to total seconds
    function parseTimeToSeconds(timeStr) {
        if (!timeStr || timeStr.trim() === '') return 0;
        timeStr = timeStr.trim().toLowerCase();
        
        // Handle suffix parsing (e.g. "10m" or "600s" or "1h")
        if (timeStr.endsWith('h')) return parseFloat(timeStr) * 3600;
        if (timeStr.endsWith('m')) return parseFloat(timeStr) * 60;
        if (timeStr.endsWith('s')) return parseFloat(timeStr);
        
        // Handle MM:SS
        const parts = timeStr.split(':').map(Number);
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        if (parts.length === 2) return parts[0] * 60 + parts[1];
        return isNaN(parts[0]) ? 0 : parts[0];
    }

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
        
        // Parse segments or auto-split duration based on what page we're in
        if (splitDurationParam) {
            const timeStr = splitDurationParam.value;
            const seconds = parseTimeToSeconds(timeStr);
            if (seconds > 0) {
                 formData.append('auto_split_duration', seconds);
            }
        } else if (clipsList) {
            const sections = [];
            document.querySelectorAll('.clip-row').forEach(row => {
                const startStr = row.querySelector('.clip-start').value;
                const endStr = row.querySelector('.clip-end').value;
                if (startStr || endStr) {
                     sections.push({
                         start: parseTimeToSeconds(startStr),
                         end: parseTimeToSeconds(endStr)
                     });
                }
            });
            
            if (sections.length > 0) {
                formData.append('sections', JSON.stringify(sections));
            }
        }
        
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
                
                if (data.progress !== undefined) {
                    progressPercent.textContent = `${data.progress}%`;
                    progressBar.style.width = `${data.progress}%`;
                }

                if (data.eta > 0) {
                    const minutes = Math.floor(data.eta / 60);
                    const seconds = data.eta % 60;
                    etaText.textContent = `Estimated time: ${minutes}m ${seconds}s`;
                } else if (data.progress > 0) {
                    etaText.textContent = `Finishing up...`;
                }
                
                if (data.status === 'completed') {
                    clearInterval(pollInterval);
                    showSuccess(data.output_url, data.elapsed_seconds);
                } else if (data.status === 'failed') {
                    clearInterval(pollInterval);
                    showError(data.error);
                }
            } catch (err) {
                console.error("Polling error:", err);
            }
        }, 1000);
    }

    function showSuccess(downloadUrls, seconds) {
        statusArea.classList.add('hidden');
        resultArea.classList.remove('hidden');
        
        const dlList = document.getElementById('downloadList');
        dlList.innerHTML = ''; // clear
        
        if (Array.isArray(downloadUrls)) {
            downloadUrls.forEach(urlObj => {
                const btn = document.createElement('a');
                btn.className = 'btn-primary';
                btn.href = urlObj.url;
                btn.download = '';
                btn.textContent = `Download ${urlObj.name}`;
                dlList.appendChild(btn);
            });
        }
        
        if (seconds !== undefined) {
             const mins = Math.floor(seconds / 60);
             const secs = seconds % 60;
             elapsedTimeDisplay.textContent = `Total Processing Time: ${mins}m ${secs}s`;
        } else {
             elapsedTimeDisplay.textContent = '';
        }
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
        if (clipsList) clipsList.innerHTML = ''; // clear clips on reset
        if (splitDurationParam) splitDurationParam.value = '';
    }

    document.getElementById('resetBtn').addEventListener('click', resetApp);
    document.getElementById('errorResetBtn').addEventListener('click', resetApp);
});
