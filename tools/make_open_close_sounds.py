"""Make the opening and closing sounds for every sound set, from each set's own notes.

    python3 tools/make_open_close_sounds.py [KENNEY_INTERFACE_AUDIO_DIR]

Rhodes, kalimba and pizzicato: the set's one-note `item_done` sound, moved to new pitches
(no more than seven semitones) and arranged into two short tunes, the same in every set, each
in its own key. Opening climbs and closing falls, the vo-cue direction convention. Notes at the
same time are a chord.

Soft clicks: Kenney's Interface Sounds `open` and `close` pair (CC0), from the folder given,
4 dB under the rest of that set at Matthew's word.

Everything gets the treatment every other sound has: 10 ms of silence, a 3 ms fade-in, a
150 ms fade-out, a 40 ms silent tail; written as MP3 (the Mac) and 16-bit 44.1 kHz WAV
(Windows). Needs ffmpeg.

Headroom all the way through: notes are mixed quietly in 32-bit float and only brought up at
the end, with the level set on the true peak. The first version mixed straight into 16-bit,
so wherever notes summed past full scale the tops were cut off; then the whole sound was
turned down and every meter read clean. Matthew heard it at once (2026-10-13).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(HERE), "assets", "sounds")
SR = 44100

# (seconds, semitones from the set's item_done note, level). Every note is that one recorded
# note moved, so all three instruments play the same two tunes in their own key (the Rhodes
# key is G). Opening (Matthew's pick, 2026-10-14): a quick run up the chord, D G B D, a
# "doo-dit" C D, and a ringing G chord. Closing answers it: the doo-dit turned round and
# walked down in steps, D B, C A, B G, then a soft G chord to settle on.
OPEN = [(0.00, -5, 0.8), (0.09, 0, 0.85), (0.18, 4, 0.9), (0.27, 7, 1.0),
        (0.50, 5, 0.75), (0.61, 7, 0.95),
        (0.84, 0, 0.7), (0.84, 4, 0.7), (0.84, 7, 0.9)]
CLOSE = [(0.00, 7, 1.0), (0.10, 4, 0.85),
         (0.30, 5, 0.9), (0.40, 2, 0.8),
         (0.60, 4, 0.85), (0.70, 0, 0.8),
         (0.94, -5, 0.55), (0.94, 0, 0.6), (0.94, 4, 0.65)]
# The opening files in the repo are the exact ones Matthew approved, made by the 2026-10-14
# "catchier" version of this script (0.4 x level per note, no per-note fade); remaking them
# here would change them by a hair. Take KEEP out to rebuild them anyway.
KEEP = {"opening"}
TUNES = {theme: {"opening": OPEN, "closing": CLOSE} for theme in ("rhodes", "kalimba", "pizzicato")}
SOFT = {"opening": "open_002.ogg", "closing": "close_002.ogg"}
SOFT_PEAK_DB = -5.5


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def tune(theme, notes, out):
    """Each note is the set's item_done note moved to pitch, placed at its time, mixed in float."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    chains = []
    for i, (at, semis, level) in enumerate(notes):
        path = os.path.join(ROOT, theme, "item_done.wav")
        gain = 1.0
        cmd += ["-i", path]
        chains.append("[%d:a]aformat=sample_fmts=flt:channel_layouts=mono,afade=t=in:d=0.003,volume=%.3f,"
                      "asetrate=%d,aresample=%d,adelay=%d[n%d]"
                      % (i, 0.3 * level * gain, round(SR * 2 ** (semis / 12)), SR, round(at * 1000), i))
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
        for theme, tunes in TUNES.items():
            for kind, notes in tunes.items():
                if kind in KEEP:
                    continue
                raw = os.path.join(tmp, "%s-%s.wav" % (theme, kind))
                tune(theme, notes, raw)
                finish(raw, os.path.join(ROOT, theme, kind))
                print("made", theme, kind)
        if os.path.isdir(kenney):
            for kind, name in SOFT.items():
                finish(os.path.join(kenney, name), os.path.join(ROOT, "soft", kind), SOFT_PEAK_DB)
                print("made soft", kind, "from", name)
        else:
            print("soft set left as it is: Kenney's Interface Sounds not found at", kenney)


if __name__ == "__main__":
    main()
