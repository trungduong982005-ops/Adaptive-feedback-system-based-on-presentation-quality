# test_samplerate.py
import pyaudio
import numpy as np
import math

pa = pyaudio.PyAudio()
RATES = [44100, 48000, 16000, 22050, 8000]
DEVICES = [0, 1, 5]

for idx in DEVICES:
    d = pa.get_device_info_by_index(idx)
    print(f"\n[{idx}] {d['name'][:50]}")
    for rate in RATES:
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=1,
                             rate=rate, input=True,
                             input_device_index=idx,
                             frames_per_buffer=rate//10)
            raw = stream.read(rate//10, exception_on_overflow=False)
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32)/32768.0
            rms = math.sqrt(np.mean(pcm**2))
            stream.stop_stream(); stream.close()
            print(f"  {rate} Hz -> OK  RMS={rms:.4f}")
        except Exception as e:
            print(f"  {rate} Hz -> FAIL")

pa.terminate()