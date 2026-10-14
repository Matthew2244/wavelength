"""Draw the app icon: python tools/make_icon.py  ->  assets/icon.png, icon.icns, icon.ico

Wavelength: one bold sound wave, white on a deep indigo-to-teal square. (The arrow of the
Media Download icon went with the old name: the app plays, searches and describes now, not
only downloads.) High contrast and a thick line on purpose, so it reads at 16 pixels and to
low vision; the wave's ends are rounded, so it doesn't fray when scaled down.
"""
import math
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
top, bottom = (36, 28, 120), (8, 146, 158)
px = grad.load()
for y in range(S):
    for x in range(S):
        t = (0.75 * y + 0.25 * x) / (S - 1)
        px[x, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((100, 100, S - 100, S - 100), radius=185, fill=255)
img.paste(grad, (0, 0), mask)

# The wave, drawn four times larger and shrunk, for smooth edges.
B = 4
big = Image.new("RGBA", (S * B, S * B), (0, 0, 0, 0))
d = ImageDraw.Draw(big)
W = (255, 255, 255, 255)
x0, x1, mid, amp, width = 230, 794, 512, 150, 78
# A thick line drawn as one stroke comes out striped where the wave is steep, so the wave is
# stamped as round dots close enough to overlap into one solid, round-ended stroke.
r = width * B / 2
for i in range(0, 20001):
    t = i / 20000
    x = x0 + (x1 - x0) * t
    env = 0.35 + 0.65 * math.sin(math.pi * t)  # taller in the middle, like a sound
    y = mid - amp * env * math.sin(t * 2 * math.pi * 2)
    d.ellipse((x * B - r, y * B - r, x * B + r, y * B + r), fill=W)
img.alpha_composite(big.resize((S, S), Image.LANCZOS))
out = os.path.join(ROOT, "assets")
os.makedirs(out, exist_ok=True)
img.save(os.path.join(out, "icon.png"))
img.save(os.path.join(out, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
with tempfile.TemporaryDirectory() as tmp:
    iconset = os.path.join(tmp, "icon.iconset")
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        img.resize((size, size), Image.LANCZOS).save(os.path.join(iconset, "icon_%dx%d.png" % (size, size)))
        img.resize((size * 2, size * 2), Image.LANCZOS).save(os.path.join(iconset, "icon_%dx%d@2x.png" % (size, size)))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(out, "icon.icns")], check=True)
print("wrote", out)
