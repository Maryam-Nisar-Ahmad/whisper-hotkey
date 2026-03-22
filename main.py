from dotenv import load_dotenv
import os
load_dotenv()

import whisper
import keyboard
import sounddevice as sd
import soundfile as sf
import numpy as np
import tempfile
import threading
import time
import requests
import win32clipboard
import win32con
import win32api
from overlay import start_overlay, hide_overlay

# ─── CONFIG ───────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
WHISPER_MODEL    = "small"
SAMPLE_RATE      = 16000
CHUNK_SECONDS    = 8
MIN_AUDIO_LENGTH = SAMPLE_RATE * 1  # minimum 1 second of audio
# ──────────────────────────────────────────────────────

print("Loading Whisper model...")
model = whisper.load_model(WHISPER_MODEL)
whisper_lock = threading.Lock()
print("Ready. Press Ctrl+Win to start/stop recording.")

is_recording       = False
audio_buffer       = []
transcribed_chunks = []
buffer_lock        = threading.Lock()

# ─── TRANSCRIBE A SINGLE CHUNK ────────────────────────
def transcribe_chunk(audio_data):
    if len(audio_data) < MIN_AUDIO_LENGTH:
        return ""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()
    sf.write(tmp_path, audio_data, SAMPLE_RATE)
    with whisper_lock:
        result = model.transcribe(tmp_path, fp16=False)
    text = result["text"].strip()
    os.remove(tmp_path)
    return text

# ─── BACKGROUND CHUNK PROCESSOR ───────────────────────
def chunk_processor():
    global audio_buffer, transcribed_chunks
    while is_recording:
        time.sleep(CHUNK_SECONDS)
        if not is_recording:
            break
        with buffer_lock:
            if not audio_buffer:
                continue
            chunk_data = np.concatenate(audio_buffer, axis=0)
            audio_buffer = []
        if len(chunk_data) < MIN_AUDIO_LENGTH:
            continue
        print("Processing background chunk...")
        text = transcribe_chunk(chunk_data)
        if text:
            print(f"Chunk: {text}")
            transcribed_chunks.append(text)

# ─── RECORD AUDIO ─────────────────────────────────────
def record_audio():
    global audio_buffer
    try:
        device_id = sd.query_devices(kind='input')['index']
    except Exception:
        device_id = None
    with sd.InputStream(device=device_id, samplerate=SAMPLE_RATE,
                        channels=1, dtype='float32') as stream:
        while is_recording:
            chunk, _ = stream.read(1024)
            with buffer_lock:
                audio_buffer.append(chunk)

# ─── PASTE TEXT ───────────────────────────────────────
def paste_text(text):
    win32clipboard.OpenClipboard(0)
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()
    time.sleep(0.1)
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord('V'), 0, 0, 0)
    win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

# ─── DEEPSEEK CLEANUP ─────────────────────────────────
def clean_with_deepseek(text):
    if not text or len(text.strip()) < 5:
        return text
    print("Cleaning with DeepSeek...")
    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a transcription cleaner. "
                            "Remove filler words like um, uh, like, you know. "
                            "Fix grammar and punctuation. "
                            "Keep original meaning 100% intact. "
                            "Keep user's original words as much as possible. "
                            "Do NOT rephrase or restructure sentences. "
                            "Do NOT add words that were not said. "
                            "Return ONLY the cleaned text. No explanations. "
                            "If the input is empty or nonsense, return it as-is."
                        )
                    },
                    {"role": "user", "content": text}
                ],
                "max_tokens": 2000
            },
            timeout=15
        )
        response.raise_for_status()
        cleaned = response.json()["choices"][0]["message"]["content"].strip()
        print(f"Cleaned: {cleaned}")
        return cleaned
    except Exception as e:
        print(f"DeepSeek failed, using raw text: {e}")
        return text

# ─── STOP AND FINALIZE ────────────────────────────────
def stop_and_transcribe():
    global is_recording, audio_buffer, transcribed_chunks
    is_recording = False
    time.sleep(0.5)

    try:
        hide_overlay()
    except Exception as e:
        print(f"Overlay hide error: {e}")

    with buffer_lock:
        remaining = audio_buffer.copy()
        audio_buffer = []

    if remaining:
        remaining_audio = np.concatenate(remaining, axis=0)
        if len(remaining_audio) >= MIN_AUDIO_LENGTH:
            print("Transcribing final chunk...")
            text = transcribe_chunk(remaining_audio)
            if text:
                print(f"Final chunk: {text}")
                transcribed_chunks.append(text)

    if not transcribed_chunks:
        print("No speech detected.")
        transcribed_chunks = []
        return

    full_text = " ".join(transcribed_chunks)
    print(f"Full raw text: {full_text}")
    transcribed_chunks = []

    final_text = clean_with_deepseek(full_text)

    if final_text:
        paste_text(final_text)
        print("Pasted successfully.")

    print("Done.")

# ─── START RECORDING ──────────────────────────────────
def start_recording():
    global is_recording, audio_buffer, transcribed_chunks
    is_recording = True
    audio_buffer = []
    transcribed_chunks = []
    print("Recording... Press Ctrl+Win again to stop.")
    start_overlay()
    threading.Thread(target=record_audio, daemon=True).start()
    threading.Thread(target=chunk_processor, daemon=True).start()

# ─── TOGGLE ───────────────────────────────────────────
def toggle():
    global is_recording
    if not is_recording:
        start_recording()
    else:
        is_recording = False
        print("Stopping recording...")
        def run_transcribe():
            try:
                stop_and_transcribe()
            except Exception as e:
                import traceback
                print(f"THREAD ERROR: {e}")
                traceback.print_exc()
        threading.Thread(target=run_transcribe, daemon=True).start()

# ─── HOTKEYS ──────────────────────────────────────────
keyboard.add_hotkey('ctrl+left windows', toggle)
keyboard.add_hotkey('ctrl+right windows', toggle)

print("Ready. Press Ctrl+Win to start/stop recording.")
keyboard.wait()
