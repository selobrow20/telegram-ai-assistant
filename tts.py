import os
import re
import uuid
import logging
from pathlib import Path
import edge_tts
from config import DATA_DIR, TTS_VOICE, TTS_RATE, TTS_PITCH, TTS_ENGINE, GEMINI_API_KEY

logger = logging.getLogger(__name__)

AUDIO_TEMP_DIR = DATA_DIR / "audio_temp"
AUDIO_TEMP_DIR.mkdir(exist_ok=True)

def clean_text_for_speech(text: str) -> str:
    """Membersihkan dan mengubah teks pesan menjadi teks ucapan bahasa Indonesia yang santai,
    natural, ramah, dan enak didengar (tidak terdengar kaku seperti komputer).
    """
    if not text:
        return "Halo bor, ada yang bisa dibantu?"

    # 1. Hapus code blocks, inline code, dan markdown links
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)

    # 2. Hapus semua Emoji, Variation Selectors (VS16), dan karakter piktogram
    text = re.sub(r'[\ufe00-\ufe0f\u200d\u200c]', '', text)
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff]|"
        "[\u2600-\u27bf]|"
        "[\u2300-\u23ff]|"
        "[\u2b50\u2b55\u2934\u2935\u25aa\u25ab\u25fe\u25fd\u25fb\u25fc\u25b6\u25c0]|"
        "[\u3297\u3299\u303d\u3030\u2b05\u2b06\u2b07\u2194-\u21aa]|"
        "[\u20a0-\u20cf]"
    )
    text = emoji_pattern.sub('', text)

    # 3. Format Angka & Mata Uang ke ucapan percakapan manusia
    non_model_keywords = [
        'saldo', 'sisa saldo', 'total', 'subtotal', 'pengeluaran', 'pemasukan',
        'omset', 'untung', 'rugi', 'biaya', 'harga', 'keluar', 'masuk'
    ]

    def format_colon_rp(m):
        prefix = m.group(1).strip()
        price_raw = m.group(2).replace('.', '')
        
        try:
            val = int(price_raw)
            if val >= 1000000:
                jt = val / 1000000
                if val % 1000000 == 0:
                    str_price = f"{val // 1000000} juta rupiah"
                elif val % 100000 == 0:
                    str_price = f"{jt:.1f}".replace('.', ',') + " juta rupiah"
                else:
                    str_price = f"{val:,}".replace(',', '.') + " rupiah"
            elif val >= 1000:
                if val % 1000 == 0:
                    str_price = f"{val // 1000} ribu rupiah"
                else:
                    str_price = f"{val:,}".replace(',', '.') + " rupiah"
            else:
                str_price = f"{val} rupiah"
        except Exception:
            str_price = m.group(2) + " rupiah"

        clean_prefix_lower = prefix.lower().strip()
        if any(k in clean_prefix_lower for k in non_model_keywords):
            return f"{prefix} {str_price}. "
        else:
            model = prefix.replace('-', ' ')
            return f"{model}, harganya {str_price}. "

    text = re.sub(r'([A-Za-z0-9\-\s]+)\s*:\s*Rp\s*([0-9\.]+)', format_colon_rp, text)

    # Format sisa Rp biasa
    def format_general_rp(m):
        price_raw = m.group(1).replace('.', '')
        try:
            val = int(price_raw)
            if val >= 1000000:
                jt = val / 1000000
                if val % 1000000 == 0:
                    return f"{val // 1000000} juta rupiah"
                elif val % 100000 == 0:
                    return f"{jt:.1f}".replace('.', ',') + " juta rupiah"
                else:
                    return f"{val:,}".replace(',', '.') + " rupiah"
            elif val >= 1000:
                if val % 1000 == 0:
                    return f"{val // 1000} ribu rupiah"
                else:
                    return f"{val:,}".replace(',', '.') + " rupiah"
            else:
                return f"{val} rupiah"
        except Exception:
            return m.group(1) + " rupiah"

    text = re.sub(r'Rp\s*([0-9\.]+)', format_general_rp, text)

    # Tangani penulisan jam (14:00 -> 14.00) agar dibaca sebagai waktu
    text = re.sub(r'(\d{1,2}):(\d{2})', r'\1.\2', text)

    # 4. Ganti simbol yang sering dieja aneh/kaku oleh mesin TTS
    text = text.replace('•', ', ')
    text = text.replace('*', '')
    text = text.replace('_', '')
    text = text.replace('~', '')
    text = text.replace('#', 'nomor ')
    text = text.replace('>', '')
    text = text.replace('|', ', ')
    text = text.replace('&', ' dan ')
    text = text.replace('/', ' atau ')
    text = text.replace('(', ', ').replace(')', ', ')
    text = text.replace(':', ', ')

    # Ubah tanda hubung lepas (misal: "Makanan - makan siang" -> "Makanan, makan siang")
    text = re.sub(r'\s+-\s+', ', ', text)
    # Ubah tanda hubung di kode barang (misal: RG-EW1200G -> RG EW1200G) agar dieja halus
    text = re.sub(r'(\w+)-(\w+)', r'\1 \2', text)

    # 5. Format jeda alami & hilangkan tanda baca bertumpuk
    text = re.sub(r'[\r\n]+', '. ', text)
    text = re.sub(r'[,.]\s*[,.]+', '.', text)
    text = re.sub(r'\.\s*,', '.', text)
    text = re.sub(r',\s*\.', '.', text)
    text = re.sub(r'\s+,', ',', text)
    text = re.sub(r'\s+\.', '.', text)
    text = re.sub(r',\s*,+', ',', text)
    text = re.sub(r'\.([A-Za-z0-9])', r'. \1', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Jika teks respons sangat panjang (misal ekspor laporan lengkap),
    # batasi bagian suara agar tidak membosankan/kepanjangan di voice note
    sentences = [s.strip() for s in text.split('. ') if s.strip()]
    if len(sentences) > 5:
        text = '. '.join(sentences[:5]) + '. Detail lengkapnya udah aku kirim di pesan teks ya bor.'

    return text

async def _generate_gemini_tts(clean_text: str, output_path: str) -> bool:
    """Mencoba generate audio menggunakan Gemini 2.5 TTS (Voice: Kore - Female Natural)."""
    try:
        import lameenc
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-2.5-flash-preview-tts',
            contents=clean_text,
            config={
                'response_modalities': ['AUDIO'],
                'speech_config': {
                    'voice_config': {
                        'prebuilt_voice_config': {'voice_name': 'Kore'}
                    }
                }
            }
        )
        pcm_data = None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                pcm_data = part.inline_data.data
                break

        if pcm_data:
            encoder = lameenc.Encoder()
            encoder.set_bit_rate(128)
            encoder.set_in_sample_rate(24000)
            encoder.set_channels(1)
            encoder.set_quality(2)
            mp3_data = encoder.encode(pcm_data)
            mp3_data += encoder.flush()
            with open(output_path, 'wb') as f:
                f.write(mp3_data)
            return True
    except Exception as e:
        logger.warning(f"Gemini TTS gagal, beralih ke Edge-TTS: {e}")
    return False

async def text_to_speech_audio(text: str, voice: str = None) -> str:
    """Mengubah teks menjadi file audio MP3 suara wanita alami untuk Voice Note Telegram."""
    clean_text = clean_text_for_speech(text)
    if not clean_text:
        clean_text = "Halo bor, ada yang bisa dibantu?"

    output_filename = AUDIO_TEMP_DIR / f"voice_{uuid.uuid4().hex[:8]}.mp3"
    str_output = str(output_filename)

    # 1. Jika TTS_ENGINE diatur ke 'gemini', coba engine Gemini terlebih dahulu
    if TTS_ENGINE.lower() == "gemini" and GEMINI_API_KEY:
        ok = await _generate_gemini_tts(clean_text, str_output)
        if ok and os.path.exists(str_output) and os.path.getsize(str_output) > 0:
            return str_output

    # 2. Default & Ultra-Fast: Edge-TTS dengan suara wanita natural (id-ID-GadisNeural)
    selected_voice = voice or TTS_VOICE
    rate = TTS_RATE
    pitch = TTS_PITCH

    communicate = edge_tts.Communicate(
        clean_text,
        selected_voice,
        rate=rate,
        pitch=pitch
    )
    await communicate.save(str_output)
    return str_output

def cleanup_audio_file(filepath: str):
    """Menghapus file audio sementara setelah terkirim."""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.error(f"Gagal menghapus file audio sementara {filepath}: {e}")
