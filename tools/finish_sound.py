"""Give any sound file the treatment every sound in the app has, as MP3 and WAV.

    python3 tools/finish_sound.py IN.mp3 OUT_BASE [PEAK_DB]

Silence before the sound starts is trimmed; then 10 ms of silence, a 3 ms fade-in, a 150 ms
fade-out, a 40 ms silent tail, and the true peak set to PEAK_DB (default -1.5 dBFS), all in
32-bit float so nothing clips on the way. Writes OUT_BASE.mp3 (the Mac) and OUT_BASE.wav
(16-bit 44.1 kHz, Windows). Used for the ElevenLabs sounds (tour_done, milestone,
signed_in, settings_saved); make_open_close_sounds.py has its own copy of the same steps.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_open_close_sounds import SR, finish, run  # noqa: E402


def main():
    src, out = sys.argv[1], sys.argv[2]
    peak = float(sys.argv[3]) if len(sys.argv) > 3 else -1.5
    with tempfile.TemporaryDirectory() as tmp:
        trimmed = os.path.join(tmp, "trimmed.wav")
        run(["ffmpeg", "-v", "error", "-y", "-i", src, "-af",
             "aformat=sample_fmts=flt:channel_layouts=mono,silenceremove=start_periods=1:start_threshold=-50dB",
             "-ar", str(SR), "-c:a", "pcm_f32le", trimmed])
        finish(trimmed, out, peak)


if __name__ == "__main__":
    main()
