import subprocess
import os
import json
import time
import re

def validate_media(input_path):
    """
    Validates that the input is a readable video and extracts properties.
    Uses ffprobe to show streams layout.
    """
    # Note: Ensure ffprobe is in the system PATH.
    # In Windows this is typically managed by adding the FFmpeg bin folder to Environmental Variables.
    # When deployed to Ubuntu, it can be installed via `sudo apt install ffmpeg`.
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration:stream=width,height,codec_name',
        '-of', 'json',
        input_path
    ]
    
    try:
        # We use capture_output so user doesn't see raw stdout unless debugging
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        if not data.get('streams'):
            raise ValueError("No video stream found in the file.")
        
        info = data['streams'][0]
        # Duration can be in 'format' or 'streams'
        duration = data.get('format', {}).get('duration')
        if not duration and info.get('duration'):
            duration = info.get('duration')
        info['duration'] = float(duration) if duration else 0
        return info
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Media validation failed. File may be corrupted or not a valid video. Details: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("ffprobe executable not found! Please ensure FFmpeg is installed and added to your system PATH.")

def process_video(input_path, output_path, preset, start_s=0, end_s=0, total_duration=None, apply_preset=True, overlay_image=None, progress_callback=None):
    """
    If apply_preset is True: 
       Crops the facecam and gameplay regions defined in the preset, 
       scales them to 1080 width, pads the full canvas to 1080x1920 (9:16),
       and stacks them vertically using ffmpeg.
    If apply_preset is False:
       Simply trims the video to the specified start_s and end_s using fast stream copy.
    """
    # Validate the file first if duration is not provided
    if total_duration is None:
        metadata = validate_media(input_path)
        total_duration = metadata.get('duration', 0)
    
    process_duration = total_duration
    if end_s > start_s:
        process_duration = end_s - start_s
    elif start_s > 0:
        process_duration = total_duration - start_s if total_duration > start_s else 0
    
    fc = preset['facecam']
    gp = preset['gameplay']
    
    # We enforce target width 1080 and height 1920 for TikTok format.
    target_w = 1080
    target_h = 1920
    
    # Filtergraph explanation:
    # 1. crop facecam -> [fc_crop]
    # 2. crop gameplay -> [gp_crop]
    # 3. scale facecam to target width -> [fc_scale]
    # 4. scale gameplay to target width -> [gp_scale]
    # 5. vstack (vertical stack) -> [stacked]
    # 6. (Optional) overlay image -> [overlaid]
    # 7. pad to exactly 1080x1920 -> [out]
    
    # Calculate the junction point for the overlay (scaled gameplay height)
    gp_h_scaled = int(target_w * (gp['h'] / gp['w']))
    
    filtergraph = (
        f"[0:v]crop=w={fc['w']}:h={fc['h']}:x={fc['x']}:y={fc['y']}[fc_crop]; "
        f"[0:v]crop=w={gp['w']}:h={gp['h']}:x={gp['x']}:y={gp['y']}[gp_crop]; "
        f"[fc_crop]scale={target_w}:-1:flags=lanczos[fc_scale]; "
        f"[gp_crop]scale={target_w}:-1:flags=lanczos[gp_scale]; "
        f"[gp_scale][fc_scale]vstack=inputs=2[stacked]"
    )
    
    if apply_preset and overlay_image and os.path.exists(overlay_image):
        # We overlay the image in the top-left corner of the camera section (with 10px margin)
        filtergraph += (
            f"; [1:v]scale=-1:100[ov_scaled]; " # Slightly smaller scale
            f"[stacked][ov_scaled]overlay=x=0:y={gp_h_scaled}[overlaid]; "
            f"[overlaid]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[scaled_final]; "
            f"[scaled_final]pad={target_w}:{target_h}:x=(ow-iw)/2:y=(oh-ih)/2[out]"
        )
    else:
        filtergraph += (
            f"; [stacked]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[scaled_final]; "
            f"[scaled_final]pad={target_w}:{target_h}:x=(ow-iw)/2:y=(oh-ih)/2[out]"
        )
    
    # Note on Dependencies/OS quirks: 
    # - `ffmpeg` must be globally accessible or absolute path provided here.
    # - Command structure works on both Windows and Linux out of the box because we provide 
    #   arguments as a list, which bypasses shell escaping issues.
    cmd = ['ffmpeg', '-y']
    
    if start_s > 0:
        cmd.extend(['-ss', str(start_s)])
    if end_s > start_s:
        cmd.extend(['-t', str(end_s - start_s)])
        
    if apply_preset:
        cmd.extend(['-i', input_path])
        if overlay_image and os.path.exists(overlay_image):
            cmd.extend(['-i', overlay_image])
            
        cmd.extend([
            '-filter_complex', filtergraph,
            '-map', '[out]',    
            '-map', '0:a?',     # include audio from source if available
            '-c:v', 'h264_amf', # AMD Hardware Acceleration
            '-quality', 'speed',# AMD specific option for fastest processing
            '-threads', '0',    # optimal multi-threading
            '-c:a', 'copy',     # copy audio without re-encoding to save time
            '-progress', 'pipe:1', # Output progress to stdout
            output_path
        ])
    else:
        cmd.extend([
            '-i', input_path,   
            '-c:v', 'copy',     # raw stream copy for blistering speed and original dimension
            '-c:a', 'copy',     
            '-progress', 'pipe:1',
            output_path
        ])
    
    start_time = time.time()
    try:
        # Running using Popen to capture real-time progress
        # We merge stderr into stdout to ensure we catch all messages and prevent pipe blocking
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        
        for line in process.stdout:
            # With -progress pipe:1, ffmpeg prints key=value pairs
            if 'out_time_ms=' in line:
                try:
                    time_ms = int(line.split('=')[1].strip())
                    time_sec = time_ms / 1000000.0
                    if process_duration > 0:
                        progress = min(99, int((time_sec / process_duration) * 100))
                        elapsed = time.time() - start_time
                        
                        # Simple ETA calculation
                        if progress > 2: # Wait for some data to stabilize
                            total_est = (elapsed / progress) * 100
                            eta = max(0, int(total_est - elapsed))
                        else:
                            eta = 0
                            
                        if progress_callback:
                            progress_callback(progress, eta)
                except (ValueError, IndexError):
                    pass

        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg processing failed with exit code {process.returncode}.")
            
    except FileNotFoundError:
        raise RuntimeError("ffmpeg executable not found! Please ensure FFmpeg is installed and added to your system PATH.")
