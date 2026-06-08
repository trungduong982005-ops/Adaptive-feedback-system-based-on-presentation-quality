# test_device.py
import pyaudio
import numpy as np
import math

DEVICES_TO_TEST = [0, 1, 5, 9, 13, 17, 18, 19, 21]

pa = pyaudio.PyAudio()
for idx in DEVICES_TO_TEST:
    try:
        d = pa.get_device_info_by_index(idx)
        if d['maxInputChannels'] < 1:
            continue
        stream = pa.open(format=pyaudio.paInt16, channels=1,
                         rate=16000, input=True,
                         input_device_index=idx,
                         frames_per_buffer=1600)
        raw = stream.read(1600, exception_on_overflow=False)
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        rms = math.sqrt(np.mean(pcm ** 2))
        stream.stop_stream()
        stream.close()
        print(f"[{idx:2d}] {d['name'][:45]:45s} RMS={rms:.4f}")
    except Exception as e:
        print(f"[{idx:2d}] ERROR: {e}")

pa.terminate()
print("\nNoi vao mic roi chay lai de so sanh RMS khi co tieng va khong co tieng")