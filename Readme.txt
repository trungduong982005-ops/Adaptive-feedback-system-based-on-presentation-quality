# 🎙️ Adaptive Feedback System v2.0

Hệ thống phản hồi thích ứng phân tích **tốc độ nói** (Words Per Minute) trong thời gian thực, giúp bạn luyện tập và cải thiện kỹ năng thuyết trình.

---

## ✨ Tính năng

- **Chế độ Mic (realtime)** — Sử dụng Deepgram Nova-3 qua WebSocket, độ trễ dưới 300ms
- **Chế độ File (batch)** — Phân tích file âm thanh có sẵn bằng OpenAI Whisper
- Hiển thị WPM trực quan kèm thanh tiến trình ngay trên terminal
- Phân loại tốc độ nói thành 6 mức và đưa ra gợi ý cụ thể
- Tổng kết phiên sau khi kết thúc (trung bình, min, max WPM)
- Hỗ trợ tiếng Anh và tiếng Việt

---

## 📊 Ngưỡng WPM

| Mức | Khoảng WPM | Nhận xét |
|-----|-----------|----------|
| 🔵 Quá chậm | < 90 | Nói rất chậm, cần tăng tốc |
| 🩵 Chậm | 90 – 110 | Hơi chậm, có thể nhanh hơn một chút |
| 🟢 Lý tưởng | 110 – 160 | Tốc độ tốt, tiếp tục duy trì |
| 🟡 Nhanh | 160 – 180 | Hơi nhanh, nên chậm lại một chút |
| 🔴 Quá nhanh | 180 – 200 | Quá nhanh, cần giảm tốc độ |
| 🚨 Rất nhanh | > 200 | Cực kỳ nhanh, hít thở và chậm lại ngay |

---

## 🛠️ Cài đặt

### Yêu cầu hệ thống

- Python 3.8 trở lên
- ffmpeg (cần thiết để đọc file MP3, OGG, FLAC, M4A)

### Bước 1 — Cài các thư viện bắt buộc

```bash
pip install numpy openai-whisper
```

### Bước 2 — Cài thư viện theo chế độ sử dụng

**Chế độ Mic (realtime):**
```bash
pip install deepgram-sdk pyaudio
```

> Trên Windows, nếu cài `pyaudio` bị lỗi, thử:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```

**Chế độ File (hỗ trợ MP3, OGG, FLAC, M4A):**
```bash
pip install pydub
```
> Cần cài thêm [ffmpeg](https://ffmpeg.org/download.html) và thêm vào PATH.

### Bước 3 — Lấy Deepgram API Key (chỉ cần cho chế độ Mic)

1. Đăng ký miễn phí tại [https://console.deepgram.com](https://console.deepgram.com) (có $200 credit, không cần thẻ)
2. Tạo API Key trong dashboard
3. Thiết lập biến môi trường:

```bash
# Linux / macOS
export DEEPGRAM_API_KEY=your_key_here

# Windows (Command Prompt)
set DEEPGRAM_API_KEY=your_key_here

# Windows (PowerShell)
$env:DEEPGRAM_API_KEY="your_key_here"
```

---

## 🚀 Sử dụng

### Chế độ Mic — realtime qua Deepgram Nova-3

```bash
python Adaptivefeedback.py --mode mic
```

Nói vào microphone, nhấn **Ctrl+C** để dừng và xem tổng kết phiên.

### Chế độ File — phân tích file âm thanh

```bash
python Adaptivefeedback.py --mode file --file path/to/audio.wav
```

Hỗ trợ định dạng: `.wav`, `.mp3`, `.ogg`, `.flac`, `.m4a`

---

## ⚙️ Tham số dòng lệnh

| Tham số | Mặc định | Mô tả |
|---------|---------|-------|
| `--mode` | `mic` | Chế độ nhập: `mic` hoặc `file` |
| `--file` | _(bắt buộc với file mode)_ | Đường dẫn đến file âm thanh |
| `--model` | `base` | Kích thước model Whisper: `tiny`, `base`, `small`, `medium` |
| `--window` | `5.0` | File mode: độ dài cửa sổ phân tích (giây) |
| `--step` | `4.0` | File mode: bước dịch giữa các cửa sổ (giây) |
| `--lang` | `en` | Ngôn ngữ nhận dạng: `en` hoặc `vi` |
| `--device` | _(mặc định hệ thống)_ | Mic mode: chỉ số thiết bị PyAudio |
| `--rate` | `16000` | Mic mode: sample rate (Hz), dùng `48000` cho mic Realtek |

### Ví dụ nâng cao

```bash
# Mic mode — tiếng Việt, dùng mic số 2, sample rate 48kHz
python Adaptivefeedback.py --mode mic --lang vi --device 2 --rate 48000

# File mode — file MP3, model Whisper small, cửa sổ 8 giây
python Adaptivefeedback.py --mode file --file talk.mp3 --model small --window 8 --step 6

# File mode — tiếng Việt
python Adaptivefeedback.py --mode file --file baocao.wav --lang vi
```

---

## 🖥️ Ví dụ đầu ra

```
────────────────────────────────────────────────────────────
[14:32:05]  chunk #001  |  duration 3.2s
 Text: Welcome everyone to today's presentation on climate change
 WPM : 142  [IDEAL]
   ████████████████████░░░░░░░░░░░░░░░░░░░░  0──────────150──────────300
 Tip :   Great pace! Keep it up.

════════════════════════════════════════════════════════════
  SESSION SUMMARY
════════════════════════════════════════════════════════════
  Chunks analysed : 12
  Avg WPM         : 138  [IDEAL]
  Min / Max WPM   : 95 / 187
  Overall tip     :   Great pace! Keep it up.
```

---

## 🏗️ Kiến trúc hệ thống

```
Chế độ Mic (v2.0):
  PyAudio (mic) → raw PCM bytes → Deepgram WebSocket → transcript events (<300ms)
                                                       ↓
                                          Tính WPM → Hiển thị feedback

Chế độ File:
  File âm thanh → WAV/pydub load → Sliding window → Whisper batch → WPM → Feedback
```

---

## 🔧 Xử lý sự cố

**Lỗi `DEEPGRAM_API_KEY` chưa được set:**
```
[ERROR] Chưa set DEEPGRAM_API_KEY.
```
→ Thiết lập biến môi trường như hướng dẫn ở Bước 3.

**Lỗi không kết nối được Deepgram WebSocket:**
→ Kiểm tra kết nối mạng và tính hợp lệ của API Key.

**Lỗi khi đọc file MP3/OGG/M4A:**
```
[ERROR] Non-WAV files require pydub: pip install pydub ffmpeg-python
```
→ Cài `pydub` và đảm bảo `ffmpeg` đã có trong PATH.

**Không nhận diện được mic:**
→ Chạy đoạn script sau để liệt kê các thiết bị âm thanh, sau đó dùng `--device <index>`:
```python
import pyaudio
p = pyaudio.PyAudio()
for i in range(p.get_device_count()):
    print(i, p.get_device_info_by_index(i)['name'])
```

**Độ chính xác nhận dạng thấp (File mode):**
→ Thử dùng model lớn hơn: `--model small` hoặc `--model medium`.

---

## 📦 Tóm tắt các thư viện

| Thư viện | Dùng cho | Bắt buộc? |
|----------|---------|-----------|
| `numpy` | Xử lý audio | ✅ Luôn cần |
| `openai-whisper` | Nhận dạng giọng nói (file mode) | ✅ Luôn cần |
| `deepgram-sdk` | Streaming realtime (mic mode) | ⚡ Cần cho mic mode |
| `pyaudio` | Thu âm từ microphone | ⚡ Cần cho mic mode |
| `pydub` | Đọc MP3/OGG/FLAC/M4A | 🔄 Cần nếu dùng non-WAV |



Dự án mang tính học thuật và nghiên cứu cá nhân.

