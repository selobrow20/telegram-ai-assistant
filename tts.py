import os
import re
import uuid
from pathlib import Path
import edge_tts
from config import DATA_DIR, TTS_VOICE

AUDIO_TEMP_DIR = DATA_DIR / "audio_temp"
AUDIO_TEMP_DIR.mkdir(exist_ok=True)

def clean_text_for_speech(text: str) -> str:
    # Remove markdown links, code blocks, bold/italics, bullets
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[*_~>#]', '', text)
    text = re.sub(r'Rp\s*([0-9\.]+)', r'\1 rupiah', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

async def text_to_speech_audio(text: str, voice: str = None) -> str:
    clean_text = clean_text_for_speech(text)
    if not clean_text:
        clean_text = "Halo, ini respon saya."
        
    selected_voice = voice or TTS_VOICE
    output_filename = AUDIO_TEMP_DIR / f"voice_{uuid.uuid4().hex[:8]}.mp3"
    
    communicate = edge_tts.Communicate(clean_text, selected_voice)
    await communicate.save(str(output_filename))
    return str(output_filename)

def cleanup_audio_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        print(f"Error cleaning up audio file {filepath}: {e}")
