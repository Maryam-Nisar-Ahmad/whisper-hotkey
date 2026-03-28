from dotenv import load_dotenv
import os

load_dotenv()


def _parse_whisper_cpu_threads() -> int:
    """Cap CPU use during transcription (Whisper + math libs). Default 4 is easy on 4–8 thread CPUs."""
    try:
        return max(1, int(os.getenv("WHISPER_CPU_THREADS", "4").strip() or "4"))
    except ValueError:
        return 4


WHISPER_CPU_THREADS = _parse_whisper_cpu_threads()
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, str(WHISPER_CPU_THREADS))

import whisper
import torch

torch.set_num_threads(WHISPER_CPU_THREADS)
try:
    torch.set_num_interop_threads(max(1, min(2, WHISPER_CPU_THREADS)))
except RuntimeError:
    pass

import keyboard
import sounddevice as sd
import soundfile as sf
import numpy as np
import tempfile
import os
import threading
import time
import requests
import json
import win32clipboard
import win32con
import win32api
from overlay import start_overlay, hide_overlay

# ─── CONFIG (.env) ────────────────────────────────────
# WHISPER_CPU_THREADS=4               (read at startup; limits CPU load — try 3–6 on your i7)
# WHISPER_ENGINE=openai | faster        (faster-whisper is often quicker on CPU; still respects thread cap)
# WHISPER_MODEL=small|medium|large-v3   (stay on small for daily use; medium only if you accept heavier runs)
# WHISPER_LANGUAGE=en                  (recommended for English: faster + fewer mistakes)
# WHISPER_INITIAL_PROMPT=Acme Inc, …   (names / jargon Whisper should favor)
# WHISPER_BEAM_SIZE=5                  (try 4 for a bit less CPU time)
# WHISPER_CONDITION_PREVIOUS=0         (0 = each clip independent, usually faster for short dictation)
# SKIP_DEEPSEEK=1                      (optional emergency off-switch only; default keeps DeepSeek on)
# DEEPSEEK_TIMEOUT=10                  (seconds)
# DEEPSEEK_MAX_TOKENS=4096            (raise if long dictations get cut off)
# WHISPER_HOTKEY=r                     (e.g. scroll lock, pause, ctrl+alt+shift+semicolon)
# AMD Radeon: stock PyTorch Whisper uses CPU here (CUDA is NVIDIA). Thread cap keeps load predictable.
# ──────────────────────────────────────────────────────


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_TIMEOUT = float(os.getenv("DEEPSEEK_TIMEOUT", "10"))
DEEPSEEK_MAX_TOKENS = max(256, int(os.getenv("DEEPSEEK_MAX_TOKENS", "4096")))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip() or "small"
WHISPER_ENGINE = os.getenv("WHISPER_ENGINE", "openai").strip().lower()
_lang_raw = os.getenv("WHISPER_LANGUAGE", "").strip()
WHISPER_LANGUAGE = None if _lang_raw.lower() in ("", "auto") else _lang_raw
WHISPER_INITIAL_PROMPT = os.getenv("WHISPER_INITIAL_PROMPT", "").strip() or None
WHISPER_BEAM_SIZE = max(1, int(os.getenv("WHISPER_BEAM_SIZE", "5")))
WHISPER_CONDITION_PREVIOUS = _env_bool("WHISPER_CONDITION_PREVIOUS", False)
SKIP_DEEPSEEK = _env_bool("SKIP_DEEPSEEK", False)

_raw_hotkey = os.getenv("WHISPER_HOTKEY", "r").strip() or "r"
WHISPER_HOTKEY = _raw_hotkey.lower()

SAMPLE_RATE = 16000
_TOGGLE_DEBOUNCE_S = 0.4
# ──────────────────────────────────────────────────────

model = None
_transcribe_callable = None
_model_ready = threading.Event()
_model_load_error = [None]  # set by loader thread on failure


def _load_openai_whisper():
    global model, _transcribe_callable
    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_fp16 = device == "cuda"
    print(
        f"[Whisper] openai-whisper | model={WHISPER_MODEL} | device={device} | fp16={use_fp16}",
        flush=True,
    )
    if device == "cpu":
        print(
            f"[Whisper] CPU inference (thread budget={WHISPER_CPU_THREADS}). "
            "Tip: WHISPER_ENGINE=faster often speeds up CPU runs. "
            "NVIDIA + CUDA is faster still; AMD Radeon is not used by stock PyTorch here.",
            flush=True,
        )
    m = whisper.load_model(WHISPER_MODEL, device=device)

    def transcribe_path(path: str) -> str:
        t0 = time.perf_counter()
        r = m.transcribe(
            path,
            fp16=use_fp16,
            language=WHISPER_LANGUAGE,
            initial_prompt=WHISPER_INITIAL_PROMPT,
            condition_on_previous_text=WHISPER_CONDITION_PREVIOUS,
            beam_size=WHISPER_BEAM_SIZE,
            verbose=False,
        )
        dt = time.perf_counter() - t0
        print(f"[Timing] Whisper (openai) decode: {dt:.2f}s", flush=True)
        return (r.get("text") or "").strip()

    model = m
    _transcribe_callable = transcribe_path


def _load_faster_whisper():
    global model, _transcribe_callable
    from faster_whisper import WhisperModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(
        f"[Whisper] faster-whisper | model={WHISPER_MODEL} | device={device} | "
        f"compute_type={compute_type} | cpu_threads={WHISPER_CPU_THREADS}",
        flush=True,
    )
    m = WhisperModel(
        WHISPER_MODEL,
        device=device,
        compute_type=compute_type,
        cpu_threads=WHISPER_CPU_THREADS,
    )

    def transcribe_path(path: str) -> str:
        t0 = time.perf_counter()
        segments, _info = m.transcribe(
            path,
            language=WHISPER_LANGUAGE,
            beam_size=WHISPER_BEAM_SIZE,
            initial_prompt=WHISPER_INITIAL_PROMPT,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350},
        )
        text = "".join(seg.text for seg in segments).strip()
        dt = time.perf_counter() - t0
        print(f"[Timing] Whisper (faster) decode: {dt:.2f}s", flush=True)
        return text

    model = m
    _transcribe_callable = transcribe_path


def _load_model_worker():
    global model, _transcribe_callable
    try:
        print(
            f"[Whisper] Loading '{WHISPER_MODEL}'… "
            "First load can take several minutes on CPU; GPU is much faster.",
            flush=True,
        )
        engine = WHISPER_ENGINE.replace("-", "_")
        if engine in ("faster", "faster_whisper", "ctranslate"):
            try:
                _load_faster_whisper()
            except (ImportError, ModuleNotFoundError) as e:
                print(
                    f"[Whisper] faster-whisper unavailable ({e}). "
                    "Run: pip install faster-whisper  — using openai-whisper instead.",
                    flush=True,
                )
                _load_openai_whisper()
        else:
            _load_openai_whisper()
        print(
            f"[Whisper] Model ready. Press {WHISPER_HOTKEY} to start/stop recording.",
            flush=True,
        )
    except Exception as e:
        _model_load_error[0] = e
        print(f"[Whisper] Failed to load model: {e}", flush=True)
    finally:
        _model_ready.set()


def wait_until_model_ready():
    """Block until Whisper finished loading (or failed). Prints progress while waiting."""
    if model is not None and _model_load_error[0] is None:
        return
    start = time.time()
    last_print = start
    while True:
        if _model_ready.wait(timeout=1.0):
            break
        now = time.time()
        if now - last_print >= 15.0:
            print(
                f"[Whisper] Still loading… ~{int(now - start)}s elapsed "
                "(normal on CPU; not frozen).",
                flush=True,
            )
            last_print = now
    err = _model_load_error[0]
    if err is not None:
        raise RuntimeError(f"Whisper model did not load: {err}") from err


threading.Thread(target=_load_model_worker, daemon=True).start()
print(
    "App started — hotkey is active. Whisper loads in the background.",
    flush=True,
)
print(
    f"Press {WHISPER_HOTKEY} anytime; if the model is not ready yet, this window will wait and show updates.",
    flush=True,
)
if SKIP_DEEPSEEK:
    print(
        "SKIP_DEEPSEEK is on (optional). DeepSeek cleanup is OFF — raw Whisper only.",
        flush=True,
    )
else:
    print(
        "DeepSeek cleanup is ON after each clip (quality).",
        flush=True,
    )

is_recording  = False
audio_frames  = []
_last_toggle_ts = 0.0
_audio_frames_lock = threading.Lock()  # safe snapshot + append
_pipeline_lock = threading.Lock()  # one transcribe+paste at a time (no stale/out-of-order paste)

# ─── AUDIO RECORDING ──────────────────────────────────
def record_audio():
    global audio_frames
    try:
        device_id = sd.query_devices(kind='input')['index']
    except Exception:
        device_id = None
    with sd.InputStream(device=device_id, samplerate=SAMPLE_RATE,
                        channels=1, dtype='float32') as stream:
        while is_recording:
            chunk, _ = stream.read(1024)
            with _audio_frames_lock:
                if is_recording:
                    audio_frames.append(chunk)

# ─── PASTE TEXT ───────────────────────────────────────
def paste_text(text):
    win32clipboard.OpenClipboard(0)
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()
    time.sleep(0.05)
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord('V'), 0, 0, 0)
    win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

# ─── DEEPSEEK CLEANUP ─────────────────────────────────
def clean_with_deepseek(text):
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
                            "You clean full speech-to-text dictation from Whisper. The user is dictating; "
                            "this is NOT a chat where you answer questions or extract one line. "
                            "You MUST return the ENTIRE message, same scope as the input: every sentence "
                            "and paragraph, in order. Never summarize, never shorten for brevity, never "
                            "reply with only a question or only the 'main ask' — keep all instructions, "
                            "asides, and context the user said. "
                            "Fix wrong words (homophones), grammar, and punctuation; remove light filler "
                            "(um, uh, like, you know). Do not add facts or sentences they did not say. "
                            "Return ONLY the full cleaned text — no quotes, no preamble."
                        )
                    },
                    {"role": "user", "content": text}
                ],
                "max_tokens": DEEPSEEK_MAX_TOKENS
            },
            timeout=DEEPSEEK_TIMEOUT
        )
        response.raise_for_status()
        cleaned = response.json()["choices"][0]["message"]["content"].strip()
        print(f"Cleaned: {cleaned}")
        return cleaned
    except Exception as e:
        print(f"DeepSeek failed, using raw text: {e}")
        return text

# ─── TRANSCRIBE & PASTE ───────────────────────────────
def stop_and_transcribe():
    tmp_path = None
    try:
        time.sleep(0.3)
        try:
            hide_overlay()
        except Exception as e:
            print(f"Overlay hide error: {e}")

        with _audio_frames_lock:
            frames = list(audio_frames)
            audio_frames.clear()

        print(f"Audio frames collected: {len(frames)}")

        if not frames:
            print("No audio recorded.")
            return

        audio_data = np.concatenate(frames, axis=0)
        print(f"Audio shape: {audio_data.shape}")

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()
        sf.write(tmp_path, audio_data, SAMPLE_RATE)
        print(f"Saved temp file: {tmp_path}")

        # Serialize Whisper + DeepSeek + paste so a new clip cannot interleave or paste stale text.
        with _pipeline_lock:
            print("Transcribing...", flush=True)
            wait_until_model_ready()
            if _transcribe_callable is None:
                print("Transcribe not ready.", flush=True)
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return
            raw_text = _transcribe_callable(tmp_path)
            print(f"Raw: {raw_text}")

            try:
                os.remove(tmp_path)
                print("Temp file deleted.")
            except OSError:
                pass

            if SKIP_DEEPSEEK:
                final_text = raw_text
                print("[DeepSeek] skipped (SKIP_DEEPSEEK) — pasting Whisper text only.", flush=True)
            else:
                t_ds = time.perf_counter()
                final_text = clean_with_deepseek(raw_text)
                print(
                    f"[Timing] DeepSeek: {time.perf_counter() - t_ds:.2f}s",
                    flush=True,
                )
            print(f"Final: {final_text}")

            if final_text:
                paste_text(final_text)
                print("Pasted successfully.")

            print("Done.")

    except Exception as e:
        print(f"ERROR in stop_and_transcribe: {e}")
        import traceback
        traceback.print_exc()
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass

# ─── START RECORDING ──────────────────────────────────
def start_recording():
    global is_recording, audio_frames
    try:
        wait_until_model_ready()
    except RuntimeError as e:
        print(e, flush=True)
        return
    with _audio_frames_lock:
        audio_frames = []
    is_recording = True
    print(f"Recording... Press {WHISPER_HOTKEY} again to stop.")
    start_overlay()
    threading.Thread(target=record_audio, daemon=True).start()

# ─── TOGGLE ───────────────────────────────────────────
def toggle():
    global is_recording, _last_toggle_ts
    now = time.time()
    if now - _last_toggle_ts < _TOGGLE_DEBOUNCE_S:
        return
    _last_toggle_ts = now
    print(f"Toggle called. is_recording = {is_recording}")
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
# suppress=True avoids the hotkey leaking into the focused app when it fires.
keyboard.add_hotkey(WHISPER_HOTKEY, toggle, suppress=True)
keyboard.wait()