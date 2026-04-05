import subprocess
import os
import json

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
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,codec_name',
        '-of', 'json',
        input_path
    ]
    
    try:
        # We use capture_output so user doesn't see raw stdout unless debugging
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        if not data.get('streams'):
            raise ValueError("No video stream found in the file.")
        return data['streams'][0]
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Media validation failed. File may be corrupted or not a valid video. Details: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("ffprobe executable not found! Please ensure FFmpeg is installed and added to your system PATH.")

def process_video(input_path, output_path, preset):
    """
    Crops the facecam and gameplay regions defined in the preset, 
    scales them to 1080 width, pads the full canvas to 1080x1920 (9:16),
    and stacks them vertically using ffmpeg.
    """
    # Validate the file first
    metadata = validate_media(input_path)
    
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
    # 6. pad to exactly 1080x1920 -> [out]
    
    filtergraph = (
        f"[0:v]crop=w={fc['w']}:h={fc['h']}:x={fc['x']}:y={fc['y']}[fc_crop]; "
        f"[0:v]crop=w={gp['w']}:h={gp['h']}:x={gp['x']}:y={gp['y']}[gp_crop]; "
        f"[fc_crop]scale={target_w}:-1:flags=lanczos[fc_scale]; "
        f"[gp_crop]scale={target_w}:-1:flags=lanczos[gp_scale]; "
        f"[fc_scale][gp_scale]vstack=inputs=2[stacked]; "
        f"[stacked]pad=width={target_w}:height={target_h}:x=(ow-iw)/2:y=(oh-ih)/2[out]"
    )
    
    # Note on Dependencies/OS quirks: 
    # - `ffmpeg` must be globally accessible or absolute path provided here.
    # - Command structure works on both Windows and Linux out of the box because we provide 
    #   arguments as a list, which bypasses shell escaping issues.
    cmd = [
        'ffmpeg',
        '-y',               
        '-i', input_path,   
        '-filter_complex', filtergraph,
        '-map', '[out]',    
        '-map', '0:a?',     # include audio from source if available
        '-c:v', 'libx264',  # universal codec
        '-preset', 'fast',  # fast processing for demo/local tool usage
        '-crf', '23',       # standard reasonable quality
        '-c:a', 'aac',      
        '-b:a', '192k',
        output_path
    ]
    
    try:
        # Running synchronously because it is already inside a background thread in app.py
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg processing failed! \nStdErr: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("ffmpeg executable not found! Please ensure FFmpeg is installed and added to your system PATH.")
