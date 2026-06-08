# 🎙️ Adaptive Feedback System
### Real-time Speaking Pace Detector for English Presentations

---

## ✨ Features
- **Mic (real-time)**: Dual-thread pipeline so audio capture and Whisper processing run in parallel — no blocking lag
- **File mode**: Sliding-window analysis of any `.wav` / `.mp3` / `.ogg` / `.m4a` file
- **WPM classification** with colour-coded terminal output and actionable tips
- **Session summary** at the end with avg / min / max WPM

---

## 📦 Installation

```bash
# 1. System dependencies
# Ubuntu / Debian:
sudo apt-get install portaudio19-dev ffmpeg

# macOS:
brew install portaudio ffmpeg

# 2. Python packages
pip install -r requirements.txt
```

---

## 🚀 Usage

### Microphone (real-time)
```bash
# Default – 2.5-second chunks, base Whisper model
python adaptive_feedback.py --mode mic

# More responsive (1.5s chunks) – accuracy slightly lower
python adaptive_feedback.py --mode mic --chunk 1.5

# Higher accuracy – slower feedback (~3s latency)
python adaptive_feedback.py --mode mic --chunk 3 --model small
```

### Audio File
```bash
# Analyse a WAV file
python adaptive_feedback.py --mode file --file speech.wav

# Analyse an MP3 with 8s windows, 6s step
python adaptive_feedback.py --mode file --file talk.mp3 --window 8 --step 6

# Use a more accurate model
python adaptive_feedback.py --mode file --file presentation.wav --model small
```

---

## ⚙️ Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `mic` | `mic` or `file` |
| `--file` | – | Path to audio file (file mode) |
| `--model` | `base` | Whisper model: `tiny` / `base` / `small` / `medium` |
| `--chunk` | `2.5` | Mic: seconds per processing chunk |
| `--window` | `5.0` | File: analysis window in seconds |
| `--step` | `4.0` | File: step between windows |

---

## 📊 WPM Thresholds

| WPM Range | Label | Feedback |
|-----------|-------|---------|
| < 90 | ⏩ Too Slow | Pick up the pace |
| 90–110 | 🐢 Slow | Speak a little faster |
| 110–160 | ✅ Ideal | Great pace! |
| 160–180 | 🐇 Fast | Slow down slightly |
| 180–200 | ⚠️ Too Fast | Please slow down |
| > 200 | 🚨 Very Fast | Breathe and slow down |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│  MICROPHONE MODE  (multi-threaded)                        │
│                                                           │
│  Thread A (AudioCaptureThread)                            │
│  ┌──────────────────────────────────────────────────┐     │
│  │  PyAudio callback (100ms chunks)                 │     │
│  │  accumulate → CHUNK seconds → push to audio_q   │     │
│  └──────────────────────────────────────────────────┘     │
│                       │ audio_q (Queue)                   │
│  Thread B (ProcessorThread)                               │
│  ┌──────────────────────────────────────────────────┐     │
│  │  pop chunk → VAD check → Whisper transcribe      │     │
│  │  → compute WPM → push to result_q               │     │
│  └──────────────────────────────────────────────────┘     │
│                       │ result_q (Queue)                  │
│  Main Thread (UI)                                         │
│  ┌──────────────────────────────────────────────────┐     │
│  │  pop result → print_feedback → update history   │     │
│  └──────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

**Why this solves lag:**
- Capture never waits for Whisper → no audio drop
- `CHUNK` duration is the only real latency knob
- VAD skips silence → faster throughput

---

## 💡 Tips to reduce latency further
1. Use `--model tiny` (fastest, ~1s on CPU)
2. Set `--chunk 1.5` (shorter windows)
3. Run on a machine with GPU → Whisper uses CUDA automatically
4. For GPU: `pip install torch --index-url https://download.pytorch.org/whl/cu118`