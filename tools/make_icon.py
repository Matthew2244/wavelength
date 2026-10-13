"""Draw the app icon: python tools/make_icon.py  ->  assets/icon.png, icon.icns, icon.ico

A downward arrow landing on a sound wave, white on a deep blue-to-teal square.
High contrast on purpose, so it reads at 16 pixels and to low vision.
"""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
top, bottom = (24, 52, 140), (10, 150, 160)
px = grad.load()
for y in range(S):
    t = y / (S - 1)
    c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
    for x in range(S):
        px[x, y] = c
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((100, 100, S - 100, S - 100), radius=185, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)
W = (255, 255, 255, 255)
# the arrow
d.rectangle((452, 210, 572, 520), fill=W)
d.polygon([(332, 480), (692, 480), (512, 680)], fill=W)
# the sound wave it lands on
import math
pts = []
for i in range(0, 601):
    x = 212 + i
    env = math.sin(math.pi * i / 600)
    y = 790 - 70 * env * math.sin(i / 600 * 2 * math.pi * 4.5)
    pts.append((x, y))
d.line(pts, fill=W, width=34, joint="curve")
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
