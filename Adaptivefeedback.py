"""
Adaptive Feedback System for Presentation Quality  v2.0
========================================================
Detects speaking pace (too fast / too slow) and provides real-time suggestions.

Mic mode  — Deepgram Nova-3 via WebSocket streaming (<300ms latency, true realtime)
File mode — OpenAI Whisper (batch, high accuracy, unchanged from v1.0)

Architecture (Mic):
  Thread 1 (AudioCaptureThread) → streams raw PCM to Deepgram WebSocket
  Deepgram cloud               → returns transcript events in <300ms
  Main     (UI / Feedback)     → receives transcript, computes WPM, prints feedback

Architecture (File):
  Single-threaded sliding window → Whisper batch → WPM → print  [UNCHANGED]

Supports:
  - Microphone : Deepgram Nova-3  (true streaming, no chunk lag)
  - Audio file : Whisper base/small/medium  (.wav / .mp3 / .ogg / .flac / .m4a)

Setup mic mode:
  pip install deepgram-sdk pyaudio
  Set env var: DEEPGRAM_API_KEY=your_key_here
  Free tier: https://console.deepgram.com  (200 USD credit, no card required)
"""

import os
import sys
import time
import queue
import threading
import asyncio
import argparse
import tempfile
import wave
import struct
import math
import json
from collections import deque
from datetime import datetime

#  dependency check 
MISSING = []
try:
    import numpy as np
except ImportError:
    MISSING.append("numpy")

try:
    import pyaudio
    PYAUDIO_OK = True
except ImportError:
    PYAUDIO_OK = False

# Whisper — chỉ dùng cho FILE mode
try:
    import whisper
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False
    MISSING.append("openai-whisper")

# Deepgram — chỉ dùng cho MIC mode
try:
    from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
    DEEPGRAM_OK = True
except ImportError:
    DEEPGRAM_OK = False
    # Không thêm vào MISSING — chỉ cần khi dùng mic mode

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False

if MISSING:
    print(f"[ERROR] Missing packages: {', '.join(MISSING)}")
    print("Install with:  pip install " + " ".join(MISSING))
    sys.exit(1)

#  ANSI colours 
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BLUE   = "\033[94m"
    GREY   = "\033[90m"
    BG_RED = "\033[41m"

#  WPM thresholds 
WPM_TOO_SLOW  = 90    # wpm
WPM_SLOW      = 110
WPM_IDEAL_LOW = 110
WPM_IDEAL_HIGH= 160
WPM_FAST      = 180
WPM_TOO_FAST  = 200

FEEDBACK_RULES = [
    (0,            WPM_TOO_SLOW,  "TOO SLOW",   C.BLUE,   "  You're speaking very slowly. Try to pick up the pace."),
    (WPM_TOO_SLOW, WPM_SLOW,     "SLOW",        C.CYAN,   "  A bit slow. You can speak a little faster."),
    (WPM_SLOW,     WPM_IDEAL_HIGH,"IDEAL",       C.GREEN,  "  Great pace! Keep it up."),
    (WPM_IDEAL_HIGH,WPM_FAST,    "FAST",        C.YELLOW, "  You're speaking a bit fast. Slow down slightly."),
    (WPM_FAST,     WPM_TOO_FAST,  "TOO FAST",   C.RED,    "   Too fast! Please slow down so the audience can follow."),
    (WPM_TOO_FAST, 9999,          "VERY FAST",  C.BG_RED, "  Way too fast! Breathe and slow down significantly."),
]

def classify_wpm(wpm: float):
    for lo, hi, label, color, tip in FEEDBACK_RULES:
        if lo <= wpm < hi:
            return label, color, tip
    return "UNKNOWN", C.GREY, "Could not determine pace."

#  Whisper loader (singleton) 
_whisper_model = None
_whisper_lock  = threading.Lock()

def get_whisper(model_size="base"):
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            print(f"{C.GREY}[INFO] Loading Whisper model '{model_size}' …{C.RESET}")
            _whisper_model = whisper.load_model(model_size)
            print(f"{C.GREEN}[INFO] Whisper ready.{C.RESET}")
    return _whisper_model

#  Audio helpers 
SAMPLE_RATE   = 16000
CHANNELS      = 1
SAMPLE_WIDTH  = 2          # int16
CHUNK_FRAMES  = 1600       # 100 ms per PyAudio callback
PROCESS_EVERY = 1.5        # seconds: how often processor fires (low = responsive)
MIN_CHUNK_SEC = 0.8        # ignore chunks shorter than this (silence / noise)

def numpy_to_wav_bytes(audio_np: np.ndarray, sr=SAMPLE_RATE) -> bytes:
    """Convert float32 numpy array → raw WAV bytes (in-memory)."""
    import io
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sr)
        pcm = (audio_np * 32767).astype(np.int16)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()

def is_speech(audio_np: np.ndarray, threshold=0.01) -> bool:
    """Simple energy-based VAD."""
    rms = math.sqrt(np.mean(audio_np ** 2))
    return rms > threshold

#  Transcription & WPM 
def transcribe_chunk(audio_np: np.ndarray, model) -> str:
    """Transcribe a numpy float32 audio array with Whisper."""
    result = model.transcribe(audio_np, language="en", fp16=False,
                               condition_on_previous_text=False)
    return result.get("text", "").strip()

def count_words(text: str) -> int:
    return len(text.split()) if text.strip() else 0

def compute_wpm(text: str, duration_sec: float) -> float:
    words = count_words(text)
    if words == 0 or duration_sec < 0.1:
        return 0.0
    return (words / duration_sec) * 60.0

#  Display helpers 
BAR_WIDTH = 40

def wpm_bar(wpm: float) -> str:
    clamped = min(max(wpm, 0), 300)
    filled  = int(BAR_WIDTH * clamped / 300)
    bar     = "█" * filled + "░" * (BAR_WIDTH - filled)
    return bar

def print_feedback(wpm: float, text: str, elapsed: float, chunk_idx: int):
    label, color, tip = classify_wpm(wpm)
    ts = datetime.now().strftime("%H:%M:%S")
    bar = wpm_bar(wpm)

    print(f"\n{C.GREY}{'─'*60}{C.RESET}")
    print(f"{C.GREY}[{ts}]  chunk #{chunk_idx:03d}  |  duration {elapsed:.1f}s{C.RESET}")
    print(f"{C.BOLD} Text:{C.RESET} {text if text else C.GREY+'(no speech detected)'+C.RESET}")
    print(f"{C.BOLD} WPM :{C.RESET} {color}{C.BOLD}{wpm:.0f}{C.RESET}  {color}[{label}]{C.RESET}")
    print(f"   {color}{bar}{C.RESET}  0──────────150──────────300")
    print(f"{C.BOLD} Tip :{C.RESET} {color}{tip}{C.RESET}")

def print_summary(history: list):
    if not history:
        return
    wpms = [h["wpm"] for h in history if h["wpm"] > 0]
    if not wpms:
        return
    avg  = sum(wpms) / len(wpms)
    mx   = max(wpms)
    mn   = min(wpms)
    lbl, col, tip = classify_wpm(avg)

    print(f"\n{C.BOLD}{'═'*60}")
    print(f"  SESSION SUMMARY")
    print(f"{'═'*60}{C.RESET}")
    print(f"  Chunks analysed : {len(history)}")
    print(f"  Avg WPM         : {col}{C.BOLD}{avg:.0f}{C.RESET}  [{lbl}]")
    print(f"  Min / Max WPM   : {mn:.0f} / {mx:.0f}")
    print(f"  Overall tip     : {col}{tip}{C.RESET}")
    print(f"{C.BOLD}{'═'*60}{C.RESET}\n")


#  MODE 1 – FILE  (offline, straightforward)

def process_file(path: str, model_size: str, window_sec: float, step_sec: float):
    """Slice the audio file into overlapping windows and analyse each."""
    print(f"\n{C.CYAN}{C.BOLD}🎵 File mode: {path}{C.RESET}")

    #  load audio 
    ext = os.path.splitext(path)[1].lower()
    if ext == ".wav":
        with wave.open(path, 'rb') as wf:
            sr       = wf.getframerate()
            n_frames = wf.getnframes()
            raw      = wf.readframes(n_frames)
            pcm      = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif PYDUB_OK:
        seg  = AudioSegment.from_file(path).set_channels(1).set_frame_rate(SAMPLE_RATE)
        pcm  = np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0
        sr   = SAMPLE_RATE
    else:
        print(f"{C.RED}[ERROR] Non-WAV files require pydub: pip install pydub ffmpeg-python{C.RESET}")
        sys.exit(1)

    #  resample to 16 kHz if needed 
    if sr != SAMPLE_RATE:
        from scipy.signal import resample_poly
        pcm = resample_poly(pcm, SAMPLE_RATE, sr)

    model    = get_whisper(model_size)
    history  = []
    total    = len(pcm) / SAMPLE_RATE
    w_frames = int(window_sec * SAMPLE_RATE)
    s_frames = int(step_sec   * SAMPLE_RATE)
    idx      = 0
    chunk_n  = 0

    print(f"{C.GREY}Audio length : {total:.1f}s  |  window {window_sec}s  step {step_sec}s{C.RESET}\n")

    pos = 0
    while pos < len(pcm):
        chunk = pcm[pos: pos + w_frames]
        dur   = len(chunk) / SAMPLE_RATE
        pos  += s_frames
        chunk_n += 1

        if dur < MIN_CHUNK_SEC:
            continue
        if not is_speech(chunk):
            print(f"{C.GREY}[chunk #{chunk_n:03d}] silence – skipped{C.RESET}")
            continue

        text = transcribe_chunk(chunk, model)
        wpm  = compute_wpm(text, dur)
        print_feedback(wpm, text, dur, chunk_n)
        history.append({"chunk": chunk_n, "wpm": wpm, "text": text, "dur": dur})

    print_summary(history)



#  MODE 2 – MICROPHONE  (Deepgram Nova-3 WebSocket — true realtime <300ms)

# Kiến trúc mới so với v1.0:
#   v1.0: Thread A tích lũy 2.5s → Thread B gọi Whisper (1-3s) → in kết quả
#   v2.0: PyAudio stream PCM → Deepgram WebSocket → nhận transcript <300ms
#
#   Deepgram tự làm VAD, tự detect utterance boundary, tự trả text.
#   Tương thích deepgram-sdk >= 3.x (sync WebSocket API).

class DeepgramMicStream:
    """
    Quản lý phiên streaming mic qua Deepgram Nova-3.
    Dùng sync WebSocket của deepgram-sdk v3/v4/v6 — không cần asyncio.
    """

    def __init__(self, api_key: str, language: str = "en",
                 model: str = "nova-3", device_index=None,
                 capture_rate: int = 16000):
        self.api_key          = api_key
        self.language         = language
        self.model            = model
        self.device_index     = device_index
        self.capture_rate     = capture_rate
        self._history         = []
        self._chunk_n         = 0
        self._utterance_buf   = []
        self._utterance_start = None

    def _flush_utterance(self):
        """Khi speech_final=True: ghép buffer, tính WPM, in feedback."""
        if not self._utterance_buf:
            return
        text = " ".join(self._utterance_buf).strip()
        if not text:
            self._utterance_buf = []
            return
        dur = time.time() - (self._utterance_start or time.time())
        dur = max(dur, 0.3)
        wpm = compute_wpm(text, dur)
        self._chunk_n += 1
        print_feedback(wpm, text, dur, self._chunk_n)
        self._history.append({"chunk": self._chunk_n, "wpm": wpm,
                               "text": text, "dur": dur})
        self._utterance_buf   = []
        self._utterance_start = None

    def run(self):
        """Chạy blocking — mở WebSocket, stream mic, xử lý transcript."""
        dg   = DeepgramClient(self.api_key)
        # SDK v3/v4/v6: sync websocket
        conn = dg.listen.websocket.v("1")

        #  Event handlers (sync callbacks)
        def on_message(self_conn, result, **kwargs):
            try:
                alt        = result.channel.alternatives[0]
                transcript = alt.transcript.strip()
            except Exception:
                return
            if not transcript:
                return
            is_final     = getattr(result, "is_final",    False)
            speech_final = getattr(result, "speech_final", False)
            if is_final:
                if self._utterance_start is None:
                    self._utterance_start = time.time()
                self._utterance_buf.append(transcript)
                # In partial để người dùng thấy realtime
                print(f"{C.GREY}  ↳ {transcript}{C.RESET}", end="\r")
            if speech_final:
                print(" " * 80, end="\r")   # xóa dòng partial
                self._flush_utterance()

        def on_utterance_end(self_conn, utterance_end, **kwargs):
            # fallback: nếu speech_final không trigger, flush ở đây
            self._flush_utterance()

        def on_speech_started(self_conn, speech_started, **kwargs):
            if self._utterance_start is None:
                self._utterance_start = time.time()

        def on_error(self_conn, error, **kwargs):
            print(f"\n{C.RED}[Deepgram] Error: {error}{C.RESET}")

        def on_close(self_conn, close, **kwargs):
            print(f"{C.GREY}[Deepgram] Connection closed.{C.RESET}")

        conn.on(LiveTranscriptionEvents.Transcript,   on_message)
        conn.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
        conn.on(LiveTranscriptionEvents.SpeechStarted,on_speech_started)
        conn.on(LiveTranscriptionEvents.Error,        on_error)
        conn.on(LiveTranscriptionEvents.Close,        on_close)

        #  Cấu hình Nova-3 
        options = LiveOptions(
            model            = self.model,      # "nova-3"
            language         = self.language,   # "en" hoặc thử "vi"
            smart_format     = True,            # tự thêm dấu câu, viết hoa
            interim_results  = True,            # partial transcript realtime
            utterance_end_ms = "1000",          # 1s im lặng = end utterance
            vad_events       = True,            # nhận SpeechStarted event
            encoding         = "linear16",
            sample_rate      = self.capture_rate,
            channels         = 1,
        )

        if not conn.start(options):
            print(f"{C.RED}[Deepgram] Không thể kết nối WebSocket.{C.RESET}")
            print(f"{C.RED}           Kiểm tra API key và kết nối mạng.{C.RESET}")
            return

        print(f"{C.GREEN}[Deepgram] Connected  model={self.model} | lang={self.language}{C.RESET}")
        print(f"{C.GREY}      Speak now… Press Ctrl+C to stop.{C.RESET}\n")

        # Mở mic và stream thẳng lên Deepgram 
        pa      = pyaudio.PyAudio()
        pa_kwargs = dict(
            format            = pyaudio.paInt16,
            channels          = 1,
            rate              = self.capture_rate,
            input             = True,
            frames_per_buffer = 3200,           # 200ms buffer
        )
        if self.device_index is not None:
            pa_kwargs["input_device_index"] = self.device_index

        stream = pa.open(**pa_kwargs)
        try:
            while True:
                raw = stream.read(3200, exception_on_overflow=False)
                conn.send(raw)                  # gửi PCM bytes thẳng lên cloud
        except KeyboardInterrupt:
            pass
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            self._flush_utterance()             # flush utterance còn dở
            conn.finish()                       # đóng WebSocket

    def get_history(self):
        return self._history


def run_mic(model_size: str, process_every: float,
            device_index=None, capture_rate: int = 16000,
            language: str = "en"):
    """Mic mode — Deepgram Nova-3 WebSocket streaming."""
    if not DEEPGRAM_OK:
        print(f"{C.RED}[ERROR] deepgram-sdk chưa cài.  pip install deepgram-sdk{C.RESET}")
        sys.exit(1)
    if not PYAUDIO_OK:
        print(f"{C.RED}[ERROR] PyAudio chưa cài.  pip install pyaudio{C.RESET}")
        sys.exit(1)

    api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not api_key:
        print(f"{C.RED}[ERROR] Chưa set DEEPGRAM_API_KEY.{C.RESET}")
        print(f"        Đăng ký miễn phí: https://console.deepgram.com")
        print(f"        Windows : set DEEPGRAM_API_KEY=your_key")
        print(f"        Linux/Mac: export DEEPGRAM_API_KEY=your_key")
        sys.exit(1)

    print(f"\n{C.CYAN}{C.BOLD}🎙️  Microphone — Deepgram Nova-3 WebSocket{C.RESET}")
    print(f"{C.GREY}    language={language} | device={device_index} | rate={capture_rate}Hz{C.RESET}")
    print(f"{C.GREY}    Ctrl+C để dừng và xem tổng kết.{C.RESET}\n")

    session = DeepgramMicStream(api_key=api_key, language=language,
                                device_index=device_index,
                                capture_rate=capture_rate)
    try:
        session.run()           # Ctrl+C được xử lý bên trong run()
    except Exception as e:
        print(f"\n{C.RED}[ERROR] {e}{C.RESET}")
    finally:
        print(f"\n{C.YELLOW}[INFO] Stopped.{C.RESET}")
        print_summary(session.get_history())



#  CLI

def main():
    parser = argparse.ArgumentParser(
        description="Adaptive Feedback System v2.0 – Deepgram Nova-3 (mic) + Whisper (file)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--mode", choices=["mic", "file"], default="mic",
        help="Input mode:\n  mic  – Deepgram Nova-3 realtime (default)\n  file – Whisper batch")
    parser.add_argument("--file", type=str, default=None,
        help="Path to audio file (required for --mode file)")
    parser.add_argument("--model", type=str, default="base",
        choices=["tiny", "base", "small", "medium"],
        help="Whisper model size cho FILE mode (default: base)")
    parser.add_argument("--chunk", type=float, default=2.5,
        help="Giữ lại để tương thích — không dùng trong mic mode nữa")
    parser.add_argument("--window", type=float, default=5.0,
        help="File: analysis window (giây, default: 5.0)")
    parser.add_argument("--step", type=float, default=4.0,
        help="File: step giữa các window (giây, default: 4.0)")
    parser.add_argument("--lang", type=str, default="en",
        help="Ngôn ngữ nhận dạng: en (default) hoặc vi\n"
             "  Mic mode  : Deepgram xử lý\n"
             "  File mode : Whisper xử lý")
    parser.add_argument("--device", type=int, default=None,
        help="Mic: PyAudio device index (default: system default)\n"
             "Chạy check_mic.py để xem danh sách device")
    parser.add_argument("--rate", type=int, default=16000,
        help="Mic: capture sample rate Hz (default: 16000)\n"
             "Dùng 48000 cho mic Realtek")
    args = parser.parse_args()

    print(f"""{C.BOLD}{C.CYAN}

   Adaptive Feedback System  v2.0             
   Mic: Deepgram Nova-3  |  File: Whisper     

{C.RESET}
WPM thresholds:
  {C.BLUE}< {WPM_TOO_SLOW}   → Too Slow{C.RESET}
  {C.CYAN}{WPM_TOO_SLOW}–{WPM_SLOW}  → Slow{C.RESET}
  {C.GREEN}{WPM_SLOW}–{WPM_IDEAL_HIGH}  → Ideal{C.RESET}
  {C.YELLOW}{WPM_IDEAL_HIGH}–{WPM_FAST}  → Fast{C.RESET}
  {C.RED}> {WPM_FAST}   → Too Fast{C.RESET}
""")

    if args.mode == "file":
        if not args.file:
            print(f"{C.RED}[ERROR] --file PATH is required for file mode.{C.RESET}")
            sys.exit(1)
        if not os.path.exists(args.file):
            print(f"{C.RED}[ERROR] File not found: {args.file}{C.RESET}")
            sys.exit(1)
        process_file(args.file, args.model, args.window, args.step)
    else:
        run_mic(args.model, args.chunk,
                device_index=args.device,
                capture_rate=args.rate,
                language=args.lang)


if __name__ == "__main__":
    main()