"""Make the opening and closing sounds for every sound set, from each set's own notes.

    python3 tools/make_open_close_sounds.py [KENNEY_INTERFACE_AUDIO_DIR]

Rhodes, kalimba and pizzicato: the set's one-note `item_done` sound, moved to new pitches
(no more than seven semitones, the rule the other figures follow) and arranged into two short
tunes: one that climbs for opening, a different one that falls and settles for closing (the
vo-cue direction convention: up is hello and all clear, down is goodbye). Soft: Kenney's own Interface Sounds
`open` and `close` pair (CC0), from the folder given. Everything gets the treatment every
other sound has: 10 ms of silence, a 3 ms fade-in, a 150 ms fade-out, a 40 ms silent tail,
true peak at -1.5 dBFS; written as MP3 (the Mac) and 16-bit 44.1 kHz WAV (Windows). Needs ffmpeg.

Headroom all the way through: the overlapping notes are mixed at half level in 32-bit float and
only brought up at the end. The first version mixed them straight into 16-bit, so wherever two
notes summed past full scale the tops were cut off, then the whole thing was turned down and
the meters read clean (Matthew heard it, 2026-10-13). The level is set on the true peak, which
counts the overshoot between samples that the MP3 and the playback filters bring out.
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sounds")
SR = 44100
# (seconds, semitones from the set's note, level): two little tunes with some swagger
# (Matthew, 2026-10-14: "even catchier... be creative"). Notes on the same time are a chord.
# In the Rhodes key, G. Opening: a quick run up the chord, D G B D, a "doo-dit" C D answer,
# and a ringing G chord to land on. Closing: a bluesy goodbye lick down from the top, D C A,
# a blue note B flat bent back into A, G, and a low G and D to finish. Every note stays
# within seven semitones of the source note.
OPEN = [(0.00, -5, 0.8), (0.09, 0, 0.85), (0.18, 4, 0.9), (0.27, 7, 1.0),
        (0.50, 5, 0.75), (0.61, 7, 0.95),
        (0.84, 0, 0.7), (0.84, 4, 0.7), (0.84, 7, 0.9)]
CLOSE = [(0.00, 7, 1.0), (0.11, 5, 0.85), (0.22, 2, 0.9),
         (0.40, 3, 0.8), (0.47, 2, 0.85), (0.60, 0, 0.9),
         (0.86, -5, 0.75), (0.86, 0, 0.85)]
SOFT = {"opening": "open_002.ogg", "closing": "close_002.ogg"}
SOFT_PEAK_DB = -5.5


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def figure(src, notes, out):
    """Each note is the source moved by `semis`, placed at its time; mixed without level change."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    for _ in notes:
        cmd += ["-i", src]
    chains = []
    for i, (at, semis, level) in enumerate(notes):
        r = 2 ** (semis / 12)
        chains.append("[%d:a]aformat=sample_fmts=flt:channel_layouts=mono,volume=%.3f,asetrate=%d,"
                      "aresample=%d,adelay=%d[n%d]" % (i, 0.4 * level, round(SR * r), SR, round(at * 1000), i))
    mix = "".join("[n%d]" % i for i in range(len(notes)))
    chains.append("%samix=inputs=%d:normalize=0:duration=longest[m]" % (mix, len(notes)))
    run(cmd + ["-filter_complex", ";".join(chains), "-map", "[m]", "-ar", str(SR), "-c:a", "pcm_f32le", out])


def true_peak(path):
    out = run(["ffmpeg", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"]).stderr
    return float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", out)[-1])


def finish(raw, dest_base, peak_db=-1.5):
    """The treatment every sound in the app has, then MP3 and WAV."""
    dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                     raw]).stdout)
    with tempfile.TemporaryDirectory() as tmp:
        shaped = os.path.join(tmp, "shaped.wav")
        run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-af",
             "aformat=sample_fmts=flt:channel_layouts=mono,afade=t=in:d=0.003,afade=t=out:st=%.3f:d=0.15,"
             "adelay=10,apad=pad_dur=0.04" % max(0.0, dur - 0.15), "-ar", str(SR), "-c:a", "pcm_f32le", shaped])
        gain = "volume=%.2fdB" % (peak_db - true_peak(shaped))
        run(["ffmpeg", "-v", "error", "-y", "-i", shaped, "-af", gain, "-c:a", "pcm_s16le",
             dest_base + ".wav"])
        run(["ffmpeg", "-v", "error", "-y", "-i", shaped, "-af", gain, "-c:a", "libmp3lame", "-b:a",
             "192k", dest_base + ".mp3"])


def main():
    kenney = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
        "~/Downloads/iem-control-sounds/kenney/kenney_interface-sounds/Audio")
    with tempfile.TemporaryDirectory() as tmp:
        for theme in ("rhodes", "kalimba", "pizzicato"):
            src = os.path.join(ROOT, theme, "item_done.wav")
            for kind, notes in (("opening", OPEN), ("closing", CLOSE)):
                raw = os.path.join(tmp, "%s-%s.wav" % (theme, kind))
                figure(src, notes, raw)
                finish(raw, os.path.join(ROOT, theme, kind))
                print("made", theme, kind)
        for kind, name in SOFT.items():
            # Kenney's open and close are brighter than the rest of the set: a little softer
            # (Matthew, 2026-10-14).
            finish(os.path.join(kenney, name), os.path.join(ROOT, "soft", kind), SOFT_PEAK_DB)
            print("made soft", kind, "from", name)


if __name__ == "__main__":
    main()
