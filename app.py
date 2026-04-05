import os
import uuid
import json
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
import threading
import threading
import time
from processor import process_video, validate_media

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
    return render_template('index.html', presets=presets, active_tab='manual')

@app.route('/auto-split')
def auto_split():
    presets_file = os.path.join(os.path.dirname(__file__), 'presets.json')
    with open(presets_file, 'r') as f:
        presets = json.load(f)
    return render_template('auto_split.html', presets=presets, active_tab='auto')

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
        
        # Parse split duration
        split_duration_str = request.form.get('auto_split_duration')
        auto_split_duration = None
        if split_duration_str:
            try:
                auto_split_duration = int(split_duration_str)
            except ValueError:
                pass
                
        # Parse sections
        sections_str = request.form.get('sections')
        sections = []
        if sections_str:
            try:
                sections = json.loads(sections_str)
            except:
                pass
                
        if not sections and not auto_split_duration:
            # Default to full video if neither sections nor auto_split is provided
            sections = [{'start': 0, 'end': 0}]
            
        # Initialize job state
        jobs[job_id] = {
            'status': 'processing',
            'progress': 0,
            'eta': 0,
            'start_time': time.time(),
            'output_url': [],
            'error': None
        }
        
        # Load preset
        presets_file = os.path.join(os.path.dirname(__file__), 'presets.json')
        with open(presets_file, 'r') as f:
            presets = json.load(f)
        preset = presets.get(preset_id, presets['default'])
        
        # Start processing thread
        thread = threading.Thread(target=run_processing_job, args=(job_id, input_path, preset, sections, auto_split_duration))
        thread.daemon = True
        thread.start()
        
        return jsonify({'job_id': job_id})

def run_processing_job(job_id, input_path, preset, sections, auto_split_duration):
    output_urls = []
    
    try:
        # Determine total duration if needed
        total_duration = 0
        if auto_split_duration:
            metadata = validate_media(input_path)
            total_duration = metadata.get('duration', 0)
            
            # Construct dynamic sections
            sections = []
            cur_start = 0
            while cur_start < total_duration:
                end_time = cur_start + auto_split_duration
                # Optional: Handle small leftover chips (e.g. if the last chunk is < 1s)
                if end_time > total_duration:
                     end_time = total_duration
                sections.append({'start': cur_start, 'end': end_time})
                cur_start = end_time
                if cur_start >= total_duration:
                     break
                     
        total_clips = len(sections)
        
        for idx, sec in enumerate(sections):
            start_s = sec.get('start', 0)
            end_s = sec.get('end', 0)
            
            output_filename = f"{job_id}_clip_{idx+1}.mp4"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            
            def progress_callback(progress, eta):
                if job_id in jobs:
                    # Overall progress logic
                    overall_progress = int((idx * 100 + progress) / total_clips)
                    jobs[job_id]['progress'] = overall_progress
                    jobs[job_id]['eta'] = eta # ETA is naive per-clip in this implementation
            
            # Apply layout preset only if NOT an auto-split job
            apply_preset = not bool(auto_split_duration)
            process_video(input_path, output_path, preset, start_s=start_s, end_s=end_s, total_duration=total_duration, apply_preset=apply_preset, progress_callback=progress_callback)
            
            output_urls.append({
                'name': f"Clip {idx+1}",
                'url': f"/download/{output_filename}"
            })
            
        duration = time.time() - jobs[job_id]['start_time']
        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['output_url'] = output_urls
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
