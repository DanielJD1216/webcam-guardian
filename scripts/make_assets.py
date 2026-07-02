"""Generate webcam-guardian hero assets.

Outputs:
  docs/banner.png    1280x320  - hero image for top of README
  docs/mascot.png     512x512  - inline logo / favicon-ish
  docs/social-preview.png  1280x640 - unchanged if already present
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)


# ---------- font helpers ----------

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        ("/System/Library/Fonts/Helvetica.ttc", bold),
        ("/System/Library/Fonts/Helvetica.ttc", False),
        ("/Library/Fonts/Arial Bold.ttf", bold),
        ("/Library/Fonts/Arial.ttf", False),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", bold),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", False),
    ]
    for path, want_bold in candidates:
        if not Path(path).exists():
            continue
        try:
            f = ImageFont.truetype(path, size)
            if want_bold:
                return f
        except Exception:
            continue
    return ImageFont.load_default()


# ---------- color palette ----------

BG_DARK = (14, 18, 28)
BG_DEEP = (10, 14, 22)
ACCENT_CYAN = (94, 200, 255)
ACCENT_CYAN_DIM = (60, 130, 180)
ACCENT_YELLOW = (255, 200, 87)
ACCENT_PURPLE = (160, 130, 240)
TEXT_WHITE = (245, 245, 250)
TEXT_DIM = (170, 200, 255)
TEXT_GREY = (140, 150, 170)


# ---------- mascot (a vigilant camera-shield) ----------

def _radial_gradient(size: int, inner_color, outer_color):
    img = Image.new("RGB", (size, size), outer_color)
    px = img.load()
    cx = cy = size / 2
    max_r = size / 2
    for y in range(size):
        for x in range(size):
            r = math.hypot(x - cx, y - cy) / max_r
            r = min(1.0, r)
            t = r * r
            px[x, y] = tuple(
                int(inner_color[i] * (1 - t) + outer_color[i] * t)
                for i in range(3)
            )
    return img


def render_mascot() -> Image.Image:
    size = 512
    img = _radial_gradient(size, BG_DARK, BG_DEEP)
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    shield_r = 180

    shield = [(cx + shield_r * math.cos(math.radians(a)),
               cy + shield_r * math.sin(math.radians(a)))
              for a in range(-180, 1, 6)]
    shield = [(cx, cy - shield_r - 30)] + shield
    for i in range(len(shield) - 1, -1, -1):
        x, y = shield[i]
        if y < cy:
            shield[i] = (x, cy + (cy - y))
    draw.polygon(shield, fill=(22, 28, 42), outline=ACCENT_CYAN)

    draw.ellipse(
        [cx - 95, cy - 95, cx + 95, cy + 95],
        fill=(8, 12, 20), outline=ACCENT_CYAN, width=4,
    )

    for r, alpha in [(82, 110), (66, 90), (50, 70), (36, 60)]:
        col = tuple(int(c * (alpha / 255)) for c in ACCENT_CYAN_DIM)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=2)

    for a in range(0, 360, 30):
        rad = math.radians(a)
        x1 = cx + 70 * math.cos(rad)
        y1 = cy + 70 * math.sin(rad)
        x2 = cx + 88 * math.cos(rad)
        y2 = cy + 88 * math.sin(rad)
        draw.line([(x1, y1), (x2, y2)], fill=ACCENT_YELLOW, width=3)

    draw.ellipse([cx - 30, cy - 30, cx + 30, cy + 30],
                 fill=ACCENT_YELLOW, outline=(180, 130, 30), width=2)
    draw.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], fill=(20, 24, 36))
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=ACCENT_YELLOW)
    draw.ellipse([cx - 25, cy - 25, cx - 5, cy - 12],
                 fill=(255, 240, 180), outline=None)

    draw.ellipse([cx - 35, cy + 90, cx - 25, cy + 100], fill=ACCENT_PURPLE)
    draw.ellipse([cx + 25, cy + 90, cx + 35, cy + 100], fill=ACCENT_PURPLE)

    return img


# ---------- banner ----------

def render_banner() -> Image.Image:
    w, h = 1280, 320
    img = _radial_gradient(w, BG_DARK, BG_DEEP)
    draw = ImageDraw.Draw(img)

    for i in range(80):
        x = (i * 173) % w
        y = (i * 91) % h
        r = (i % 5) + 1
        a = int(30 + (i % 3) * 20)
        col = tuple(int(c * a / 255) for c in ACCENT_CYAN)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=col)

    f_word = _font(96, bold=True)
    f_tag = _font(30)
    f_sub = _font(18)

    draw.text((60, 88), "webcam-guardian", font=f_word, fill=TEXT_WHITE)
    draw.text((60, 198), "Local guard  ·  Bring-your-own detective  ·  MIT",
              font=f_tag, fill=TEXT_DIM)
    draw.text((60, 245),
              "RT-DETR r18  ·  MiniMax-M3 / Ollama / OpenAI-compatible  ·  Telegram + Resend",
              font=f_sub, fill=TEXT_GREY)

    chip_y = 285
    chips = ["v0.2.0", "MIT", "macOS / Linux / Windows"]
    x = 60
    for label in chips:
        tw = draw.textlength(label, font=f_sub) + 18
        draw.rounded_rectangle([x, chip_y, x + tw, chip_y + 22],
                                radius=11, fill=(28, 36, 52),
                                outline=ACCENT_CYAN_DIM, width=1)
        draw.text((x + 9, chip_y + 3), label, font=f_sub, fill=TEXT_DIM)
        x += tw + 10

    mascot = render_mascot()
    mascot = mascot.resize((220, 220), Image.LANCZOS)
    img.paste(mascot, (w - 280, 50))

    return img


# ---------- social preview (refresh) ----------

def render_social_preview() -> Image.Image:
    w, h = 1280, 640
    img = _radial_gradient(w, BG_DARK, BG_DEEP)
    draw = ImageDraw.Draw(img)

    f_title = _font(72, bold=True)
    f_sub = _font(32)
    f_chip = _font(16, bold=True)

    draw.text((60, 70), "webcam-guardian", font=f_title, fill=TEXT_WHITE)
    draw.text((60, 160),
              "Local RT-DETR guard  +  bring-your-own detective",
              font=f_sub, fill=TEXT_DIM)
    draw.text((60, 200),
              "MIT licensed  ·  v0.2.0  ·  macOS / Linux / Windows",
              font=f_chip, fill=TEXT_GREY)

    node_y = 320
    nodes = [
        ("Camera",      (60, 80, 130),  "AVFOUNDATION"),
        ("RT-DETR",     (60, 200, 110), "local · free"),
        ("Escalator",   (60, 200, 110), "debounce + cooldown"),
        ("MiniMax M3",  (60, 140, 220), "image judge"),
        ("Telegram",    (60, 200, 110), "sendPhoto"),
        ("Resend",      (60, 220, 130), "JSON email"),
    ]
    f_node = _font(20, bold=True)
    f_label = _font(16)
    box_w, box_h = 168, 110
    x = 60
    for label, rgb, sub in nodes:
        draw.rounded_rectangle([x, node_y, x + box_w, node_y + box_h],
                               radius=14, fill=rgb)
        draw.text((x + 14, node_y + 22), label, font=f_node, fill=TEXT_WHITE)
        draw.text((x + 14, node_y + 60), sub, font=f_label, fill=(240, 240, 240))
        x += box_w + 32

    for cx in (148, 348, 548, 748, 948):
        draw.line([(cx + 168 + 16, node_y + 55), (cx + box_w + 32, node_y + 55)],
                  fill=(160, 180, 220), width=3)
        draw.polygon(
            [(cx + box_w + 30, node_y + 50),
             (cx + box_w + 40, node_y + 55),
             (cx + box_w + 30, node_y + 60)],
            fill=(160, 180, 220))

    draw.rounded_rectangle([60, 510, 1220, 600], radius=14, fill=(30, 36, 50))
    draw.text((78, 528),
              "guard: free, local, MIT-clean   ·   detective: any OpenAI-compatible vision model",
              font=f_chip, fill=(220, 230, 245))
    draw.text((78, 558),
              "pip install -e .   &&   python -m guardian",
              font=f_chip, fill=(120, 200, 255))

    return img


# ---------- entry point ----------

def _save(img: Image.Image, name: str) -> Path:
    path = DOCS / name
    img.save(path, format="PNG", optimize=True)
    print(f"  wrote {path}  ({path.stat().st_size // 1024} KB)")
    return path


def main() -> int:
    print("rendering webcam-guardian hero assets...")
    _save(render_mascot(), "mascot.png")
    _save(render_banner(), "banner.png")
    _save(render_social_preview(), "social-preview.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())