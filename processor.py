import subprocess
import os
import json
import time
import re
import tempfile
from PIL import Image, ImageDraw, ImageFont

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

def generate_episode_overlay(episode_number, font_path):
    """
    Generates a PNG image with the episode number inside a rounded rectangle
    with background color #c67ed0, white text, Sriracha font at size 62.
    Returns the path to the temporary PNG file.
    """
    font_size = 62
    try:
        font = ImageFont.truetype(font_path, font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()
    
    text = "ep" + str(episode_number).rjust(2, '0')
    
    # Measure text size
    dummy_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
    dummy_draw = ImageDraw.Draw(dummy_img)
    bbox = dummy_draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    
    # Padding around the text
    pad_x = 14
    pad_y = 22
    img_w = text_w + pad_x * 2
    img_h = text_h + pad_y * 2
    
    # Border radius as 32% of the shorter dimension
    radius = int(min(img_w, img_h) * 0.16)
    
    img = Image.new('RGBA', (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw rounded rectangle background
    bg_color = (198, 126, 208, 255)  # #c67ed0
    draw.rounded_rectangle(
        [(0, 0), (img_w - 1, img_h - 1)],
        radius=radius,
        fill=bg_color
    )
    
    # Draw text centered
    text_x = (img_w - text_w) // 2 - bbox[0]
    text_y = (img_h - text_h) // 2 - bbox[1]
    draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)
    
    # Save to temp file
    tmp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()
    img.save(tmp_path, 'PNG')
    return tmp_path

def process_video(input_path, output_path, preset, start_s=0, end_s=0, total_duration=None, apply_preset=True, overlay_image=None, episode=None, progress_callback=None):
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
    
    # Generate episode overlay image if episode number is provided
    episode_overlay_path = None
    if episode is not None and apply_preset:
        font_path = os.path.join(os.path.dirname(__file__), 'static', 'fonts', 'Sriracha-Regular.ttf')
        episode_overlay_path = generate_episode_overlay(episode, font_path)
    
    filtergraph = (
        f"[0:v]crop=w={fc['w']}:h={fc['h']}:x={fc['x']}:y={fc['y']}[fc_crop]; "
        f"[0:v]crop=w={gp['w']}:h={gp['h']}:x={gp['x']}:y={gp['y']}[gp_crop]; "
        f"[fc_crop]scale={target_w}:-1:flags=lanczos[fc_scale]; "
        f"[gp_crop]scale={target_w}:-1:flags=lanczos[gp_scale]; "
        f"[gp_scale][fc_scale]vstack=inputs=2[stacked]"
    )
    
    # Track which input index the overlay images are at
    next_input_idx = 1  # 0 is the video
    softie_input_idx = None
    episode_input_idx = None
    
    if apply_preset and overlay_image and os.path.exists(overlay_image):
        softie_input_idx = next_input_idx
        next_input_idx += 1
    
    if episode_overlay_path:
        episode_input_idx = next_input_idx
        next_input_idx += 1
    
    # Build composite overlay chain
    current_label = 'stacked'
    
    if softie_input_idx is not None:
        filtergraph += (
            f"; [{softie_input_idx}:v]scale=-1:100[ov_scaled]; "
            f"[{current_label}][ov_scaled]overlay=x=0:y={gp_h_scaled}[after_softie]"
        )
        current_label = 'after_softie'
    
    if episode_input_idx is not None:
        # Position at top-right of camera scene (camera starts at gp_h_scaled)
        # 15px margin from right edge and from top of camera
        filtergraph += (
            f"; [{current_label}][{episode_input_idx}:v]overlay=x=W-w:y={gp_h_scaled}[after_episode]"
        )
        current_label = 'after_episode'
    
    filtergraph += (
        f"; [{current_label}]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[scaled_final]; "
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
        if softie_input_idx is not None:
            cmd.extend(['-i', overlay_image])
        if episode_overlay_path:
            cmd.extend(['-i', episode_overlay_path])
            
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
    finally:
        # Clean up temporary episode overlay
        if episode_overlay_path and os.path.exists(episode_overlay_path):
            try:
                os.remove(episode_overlay_path)
            except:
                pass
