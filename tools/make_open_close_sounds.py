"""Make the opening and closing sounds for every sound set, from each set's own notes.

    python3 tools/make_open_close_sounds.py [KENNEY_INTERFACE_AUDIO_DIR]

Rhodes, kalimba and pizzicato each get their own two tunes, written for the instrument rather
than one tune moved between keys (Matthew, 2026-10-14: "be more creative... don't hold back").
Every note is one of the set's own recorded notes, moved to its pitch: for each note the
nearest source is used, so nothing is moved more than seven semitones. Notes at the same time
are a chord; a run of chord notes a few hundredths apart is a rolled chord. Opening rises and
closing falls, the vo-cue direction convention.

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
MAX_SHIFT = 7  # semitones; further and a note stops sounding like the instrument

# Each set's single recorded notes: (file, MIDI note it plays, gain to match the others).
SOURCES = {
    "rhodes": [(os.path.join(ROOT, "rhodes", "item_done.wav"), 67, 1.0),       # G4
               (os.path.join(ROOT, "rhodes", "added.wav"), 76, 1.0)],          # E5
    "pizzicato": [(os.path.join(ROOT, "pizzicato", "item_done.wav"), 67, 1.0),  # G4
                  (os.path.join(ROOT, "pizzicato", "added.wav"), 74, 1.0)],     # D5
    # From hark's kalimba recordings, Matthew's own, with their full natural ring.
    # The two raw notes sit about 4 dB under the levelled item_done note.
    "kalimba": [(os.path.join(ROOT, "kalimba", "item_done.wav"), 71, 1.0),      # B4
                (os.path.join(HERE, "sound_sources", "kalimba_D#5.wav"), 75, 1.6),
                (os.path.join(HERE, "sound_sources", "kalimba_F#5.wav"), 78, 1.6)],
}


def roll(at, notes, level, gap=0.03):
    """A rolled chord: the notes one after another, `gap` apart, ringing together."""
    return [(at + i * gap, n, level) for i, n in enumerate(notes)]


# (seconds, MIDI note, level 0..1)
TUNES = {
    # Neo-soul, in G. Opening: a slide into the lick, B D E D B D, and a rolled Gmaj9 to land
    # on. Closing: a falling turn G E D C, then the gospel "Amen", a rolled Cmaj9 resolving to
    # a G chord rolled down from the top.
    "rhodes": {
        "opening": [(0.00, 70, 0.5), (0.05, 71, 0.85), (0.19, 74, 0.9), (0.32, 76, 1.0),
                    (0.45, 74, 0.8), (0.58, 71, 0.8), (0.71, 74, 0.9)]
                   + roll(0.92, [67, 71, 74, 78, 81], 0.65),
        "closing": [(0.00, 79, 0.9), (0.12, 76, 0.85), (0.24, 74, 0.85), (0.36, 72, 0.9)]
                   + roll(0.58, [60, 64, 67, 71, 74], 0.6)
                   + roll(1.02, [79, 74, 71, 67, 62], 0.6),
    },
    # Thumb piano, in B, pentatonic. Opening: a bouncing riff up to the top B, answered, then
    # its own echo twice, fading. Closing: a lullaby falling and slowing, a little lift, and
    # a soft B and F sharp with one last echo.
    "kalimba": {
        "opening": [(0.00, 71, 0.8), (0.08, 75, 0.8), (0.16, 78, 0.85), (0.24, 80, 0.85),
                    (0.36, 78, 0.8), (0.44, 83, 1.0), (0.60, 80, 0.8), (0.68, 83, 0.95),
                    (0.84, 80, 0.45), (0.92, 83, 0.45), (1.08, 80, 0.22), (1.16, 83, 0.22)],
        "closing": [(0.00, 83, 0.9), (0.11, 80, 0.85), (0.22, 78, 0.85), (0.36, 75, 0.85),
                    (0.52, 73, 0.8), (0.70, 75, 0.75), (0.92, 71, 0.85), (0.92, 66, 0.6),
                    (1.20, 71, 0.3)],
    },
    # Plucked strings, in G, cheeky. Opening: a strut, D G, B D, a little E D B, and a hit on
    # a G chord. Closing: tiptoeing away down a chromatic line, a pause, then "dun... dun".
    "pizzicato": {
        "opening": [(0.00, 62, 0.8), (0.10, 67, 0.9), (0.30, 71, 0.85), (0.40, 74, 0.95),
                    (0.60, 76, 0.85), (0.70, 74, 0.8), (0.80, 71, 0.8),
                    (0.98, 67, 0.75), (0.98, 74, 0.75), (0.98, 79, 0.9)],
        "closing": [(0.00, 74, 0.9), (0.12, 73, 0.75), (0.24, 72, 0.75), (0.36, 71, 0.75),
                    (0.48, 70, 0.7), (0.60, 69, 0.7), (0.88, 74, 0.85),
                    (1.14, 67, 0.95), (1.14, 62, 0.8)],
    },
}
SOFT = {"opening": "open_002.ogg", "closing": "close_002.ogg"}
SOFT_PEAK_DB = -5.5


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def nearest(theme, midi):
    path, base, gain = min(SOURCES[theme], key=lambda s: abs(midi - s[1]))
    if abs(midi - base) > MAX_SHIFT:
        raise SystemExit("%s note %d is %d semitones from any recorded note" % (theme, midi, abs(midi - base)))
    return path, midi - base, gain


def tune(theme, notes, out):
    """Each note from its nearest source, moved to pitch, placed at its time, mixed in float."""
    cmd = ["ffmpeg", "-v", "error", "-y"]
    chains = []
    for i, (at, midi, level) in enumerate(notes):
        path, semis, gain = nearest(theme, midi)
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
