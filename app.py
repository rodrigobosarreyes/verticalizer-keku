import os
import uuid
import json
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
import threading
import time
from processor import process_video

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['OUTPUT_FOLDER'] = os.path.join(os.path.dirname(__file__), 'outputs')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Simple in-memory store for job state
jobs = {}

@app.route('/')
def index():
    presets_file = os.path.join(os.path.dirname(__file__), 'presets.json')
    with open(presets_file, 'r') as f:
        presets = json.load(f)
    return render_template('index.html', presets=presets)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    preset_id = request.form.get('preset', 'default')
    
    if file:
        filename = secure_filename(file.filename)
        job_id = str(uuid.uuid4())
        
        # Save file with job_id to prevent collision
        safe_filename = f"{job_id}_{filename}"
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
        output_filename = f"{job_id}_vertical.mp4"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        file.save(input_path)
        
        # Initialize job state
        jobs[job_id] = {
            'status': 'processing',
            'progress': 0,
            'eta': 0,
            'start_time': time.time(),
            'output_url': None,
            'error': None
        }
        
        # Load preset
        presets_file = os.path.join(os.path.dirname(__file__), 'presets.json')
        with open(presets_file, 'r') as f:
            presets = json.load(f)
        preset = presets.get(preset_id, presets['default'])
        
        # Start processing thread
        thread = threading.Thread(target=run_processing_job, args=(job_id, input_path, output_path, preset))
        thread.daemon = True
        thread.start()
        
        return jsonify({'job_id': job_id})

def run_processing_job(job_id, input_path, output_path, preset):
    def progress_callback(progress, eta):
        if job_id in jobs:
            jobs[job_id]['progress'] = progress
            jobs[job_id]['eta'] = eta

    try:
        process_video(input_path, output_path, preset, progress_callback=progress_callback)
        duration = time.time() - jobs[job_id]['start_time']
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['output_url'] = f"/download/{os.path.basename(output_path)}"
        jobs[job_id]['progress'] = 100
        jobs[job_id]['eta'] = 0
        jobs[job_id]['elapsed_seconds'] = int(duration)
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['error'] = str(e)
    finally:
        # Note: clean up input file to save space
        if os.path.exists(input_path):
            try:
                os.remove(input_path)
            except:
                pass

@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(jobs[job_id])

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
