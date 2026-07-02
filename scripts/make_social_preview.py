"""Generate a GitHub social preview image for the repo.

Output: docs/social-preview.png (1280x640, GitHub's recommended size).
GitHub renders this on the repo header when sharing the link.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "docs" / "social-preview.png"
SIZE = (1280, 640)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill)


def _box(draw, x, y, w, h, fill):
    draw.rectangle([x, y, x + w, y + h], fill=fill)


def render() -> Path:
    img = Image.new("RGB", SIZE, color=(14, 18, 28))
    draw = ImageDraw.Draw(img)

    f_title = _font(64, bold=True)
    f_sub = _font(28)
    f_node = _font(20, bold=True)
    f_label = _font(16)
    f_chip = _font(14, bold=True)

    _text(draw, (60, 60), "webcam-guardian", f_title, fill=(245, 245, 245))
    _text(draw, (60, 140),
          "Local RT-DETR guard  +  bring-your-own detective",
          f_sub, fill=(170, 200, 255))
    _text(draw, (60, 178),
          "MIT licensed  ·  v0.2.0  ·  macOS / Linux / Windows",
          f_label, fill=(140, 150, 170))

    node_y = 320
    nodes = [
        ("Camera", (60, 80, 130), "AVFOUNDATION"),
        ("RT-DETR", (60, 200, 110), "local · free"),
        ("Escalator", (60, 200, 110), "debounce + cooldown"),
        ("MiniMax M3", (60, 140, 220), "image judge"),
        ("Telegram", (60, 200, 110), "sendPhoto"),
        ("Resend", (60, 220, 130), "JSON email"),
    ]
    box_w, box_h = 168, 110
    x = 60
    for label, rgb, sub in nodes:
        _box(draw, x, node_y, box_w, box_h, fill=rgb)
        _text(draw, (x + 14, node_y + 22), label, f_node, fill=(255, 255, 255))
        _text(draw, (x + 14, node_y + 60), sub, f_label, fill=(240, 240, 240))
        x += box_w + 32

    for cx in (148, 348, 548, 748, 948):
        draw.line([(cx + 168 + 16, node_y + 55), (cx + box_w + 32, node_y + 55)],
                  fill=(160, 180, 220), width=3)
        draw.polygon(
            [(cx + box_w + 30, node_y + 50),
             (cx + box_w + 40, node_y + 55),
             (cx + box_w + 30, node_y + 60)],
            fill=(160, 180, 220))

    _box(draw, 60, 510, 1160, 90, fill=(30, 36, 50))
    _text(draw, (78, 528),
          "guard: free, local, MIT-clean   ·   detective: any OpenAI-compatible vision model   ·   "
          "alerts: fan-out to all configured channels",
          f_chip, fill=(220, 230, 245))
    _text(draw, (78, 558),
          "pip install -e .   &&   python -m guardian",
          f_chip, fill=(120, 200, 255))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, format="PNG", optimize=True)
    return OUT


if __name__ == "__main__":
    out = render()
    print(f"wrote {out}  ({OUT.stat().st_size // 1024} KB)")