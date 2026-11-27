"""Render the README's demo GIF: dictation into a browser field, a terminal and an editor.

This is an illustration of the workflow, not a screen recording: the windows, keys,
notifications and texts are drawn with Pillow.

    uv run --with pillow python scripts/make_demo_gif.py

Writes docs/images/voice-input-demo.gif. Needs the DejaVu fonts (fonts-dejavu-core) and Pillow
built with libraqm for right-to-left Hebrew.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "images" / "voice-input-demo.gif"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
W, H = 860, 480
FRAME_MS = 90

# Example dictations shown in the illustration.
TEXTS = {
    "en": "Great video! The explanation of the setup was really clear, thank you.",
    "ru": "Исправил ошибку в обработке конфигурации и добавил тесты.",
    "he": "לקנות חלב, לחם וביצים בדרך הביתה.",
}

BG = (36, 31, 49)
PANEL = (250, 250, 250)
TEXT = (30, 30, 30)
MUTED = (120, 120, 130)
ACCENT = (53, 132, 228)
RED = (224, 27, 36)
TERM_BG = (23, 20, 33)
TERM_FG = (220, 220, 220)
GREEN = (87, 227, 137)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size, layout_engine=ImageFont.Layout.RAQM)


SANS = font("DejaVuSans.ttf", 17)
SANS_SMALL = font("DejaVuSans.ttf", 14)
SANS_BOLD = font("DejaVuSans-Bold.ttf", 15)
MONO = font("DejaVuSansMono.ttf", 16)
KEY = font("DejaVuSans-Bold.ttf", 18)


@dataclass(frozen=True)
class Scene:
    kind: str  # "browser", "terminal" or "editor"
    keys: str
    language: str  # notification name
    text: str
    rtl: bool = False


def wrap(
    draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=fnt) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def window(draw: ImageDraw.ImageDraw, title: str, dark: bool) -> tuple[int, int, int, int]:
    box = (40, 100, W - 40, H - 75)
    draw.rounded_rectangle(box, 12, fill=TERM_BG if dark else PANEL)
    draw.rounded_rectangle(
        (box[0], box[1], box[2], box[1] + 38), 12, fill=(48, 48, 56) if dark else (235, 235, 238)
    )
    draw.rectangle(
        (box[0], box[1] + 26, box[2], box[1] + 38), fill=(48, 48, 56) if dark else (235, 235, 238)
    )
    draw.text(
        ((box[0] + box[2]) / 2, box[1] + 19),
        title,
        font=SANS_BOLD,
        fill=(230, 230, 230) if dark else TEXT,
        anchor="mm",
    )
    for i, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        draw.ellipse(
            (box[2] - 70 + i * 20, box[1] + 13, box[2] - 58 + i * 20, box[1] + 25), fill=colour
        )
    return box


def draw_content(draw: ImageDraw.ImageDraw, scene: Scene, shown: str, cursor: bool) -> None:
    if scene.kind == "browser":
        box = window(draw, "Video comments — Browser", dark=False)
        draw.text((box[0] + 30, box[1] + 60), "Add a comment…", font=SANS_SMALL, fill=MUTED)
        field = (box[0] + 30, box[1] + 85, box[2] - 30, box[3] - 30)
        draw.rounded_rectangle(field, 8, outline=ACCENT, width=2, fill=(255, 255, 255))
        y = field[1] + 14
        lines = wrap(draw, shown, SANS, field[2] - field[0] - 30) or [""]
        for line in lines:
            draw.text((field[0] + 15, y), line, font=SANS, fill=TEXT)
            y += 26
        if cursor:
            x = field[0] + 15 + draw.textlength(lines[-1], font=SANS)
            draw.line((x + 2, y - 24, x + 2, y - 4), fill=TEXT, width=2)
    elif scene.kind == "terminal":
        box = window(draw, "Terminal", dark=True)
        x0, y = box[0] + 20, box[1] + 55
        draw.text((x0, y), "~/project$ git add -A", font=MONO, fill=TERM_FG)
        y += 26
        prompt = '~/project$ git commit -m "'
        draw.text((x0, y), prompt, font=MONO, fill=TERM_FG)
        x = x0 + draw.textlength(prompt, font=MONO)
        lines = wrap(draw, shown, MONO, box[2] - x - 30) or [""]
        for i, line in enumerate(lines):
            draw.text((x if i == 0 else x0, y), line, font=MONO, fill=GREEN)
            y += 26
        if cursor:
            last_x = (x if len(lines) == 1 else x0) + draw.textlength(lines[-1], font=MONO)
            draw.rectangle((last_x + 2, y - 25, last_x + 11, y - 5), fill=TERM_FG)
    else:
        box = window(draw, "notes.txt — Text Editor", dark=False)
        right = box[2] - 30
        y = box[1] + 60
        draw.text((right, y), "רשימות", font=SANS_BOLD, fill=MUTED, anchor="ra", direction="rtl")
        y += 34
        lines = wrap(draw, shown, SANS, box[2] - box[0] - 60) or [""]
        for line in lines:
            draw.text((right, y), line, font=SANS, fill=TEXT, anchor="ra", direction="rtl")
            y += 28
        if cursor:
            width = draw.textlength(lines[-1], font=SANS, direction="rtl")
            draw.line((right - width - 4, y - 26, right - width - 4, y - 6), fill=TEXT, width=2)


def draw_keys(draw: ImageDraw.ImageDraw, keys: str) -> None:
    parts = keys.split("+")
    widths = [draw.textlength(p, font=KEY) + 26 for p in parts]
    total = sum(widths) + 22 * (len(parts) - 1)
    x = (W - total) / 2
    y = H - 58
    for i, (part, width) in enumerate(zip(parts, widths, strict=True)):
        draw.rounded_rectangle(
            (x, y, x + width, y + 36), 7, fill=(245, 245, 245), outline=(180, 180, 190), width=2
        )
        draw.text((x + width / 2, y + 18), part, font=KEY, fill=TEXT, anchor="mm")
        x += width
        if i < len(parts) - 1:
            draw.text((x + 11, y + 18), "+", font=KEY, fill=(230, 230, 230), anchor="mm")
            x += 22


def draw_bubble(draw: ImageDraw.ImageDraw, title: str, body: str, recording: float | None) -> None:
    box = (W // 2 - 200, 14, W // 2 + 200, 82)  # GNOME shows banners at the top centre
    draw.rounded_rectangle(box, 12, fill=(54, 54, 62), outline=(80, 80, 90))
    x = box[0] + 18
    if recording is not None:
        radius = 7 + 2 * math.sin(recording)
        draw.ellipse((x + 8 - radius, 40 - radius, x + 8 + radius, 40 + radius), fill=RED)
        x += 26
    draw.text((x, 29), title, font=SANS_BOLD, fill=(240, 240, 240))
    draw.text((box[0] + 18, 55), body, font=SANS_SMALL, fill=(200, 200, 205))


def frames_for(scene: Scene) -> list[Image.Image]:
    frames: list[Image.Image] = []

    def frame(
        shown: str, keys: str | None, bubble: tuple[str, str, float | None] | None, cursor: bool
    ) -> None:
        image = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(image)
        draw_content(draw, scene, shown, cursor)
        if keys:
            draw_keys(draw, keys)
        if bubble:
            draw_bubble(draw, *bubble)
        frames.append(image)

    for i in range(8):
        frame("", None, None, i % 6 < 3)
    for _ in range(7):
        frame("", scene.keys, None, True)
    for i in range(22):
        frame(
            "",
            scene.keys if i < 4 else None,
            (f"Recording · {scene.language}", "Speak now…", i * 0.6),
            True,
        )
    for _ in range(5):
        frame("", scene.keys, (f"Recording · {scene.language}", "Speak now…", 0.0), True)
    for _ in range(12):
        frame("", None, (f"Recognising · {scene.language}…", "", None), True)
    preview = scene.text if len(scene.text) < 46 else scene.text[:44] + "…"
    for i in range(26):
        frame(
            scene.text,
            None,
            (f"Typed · {scene.language}", preview, None) if i < 16 else None,
            i % 6 < 3,
        )
    return frames


def main() -> None:
    texts = TEXTS
    scenes = [
        Scene("browser", "Super+T", "auto-detect", texts["en"]),
        Scene("terminal", "Shift+Super+R", "Русский", texts["ru"]),
        Scene("editor", "Shift+Super+H", "עברית", texts["he"], rtl=True),
    ]
    frames = [f for scene in scenes for f in frames_for(scene)]
    # One palette for all scenes, built from a frame of each (the terminal's green included).
    per_scene = len(frames) // len(scenes)
    sample = Image.new("RGB", (W, H * len(scenes)))
    for i in range(len(scenes)):
        sample.paste(frames[i * per_scene + per_scene - 5], (0, H * i))
    palette = sample.quantize(colors=160, method=Image.Quantize.MEDIANCUT)
    quantized = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        OUTPUT, save_all=True, append_images=quantized[1:], duration=FRAME_MS, loop=0, optimize=True
    )
    print(f"{OUTPUT}: {len(frames)} frames, {OUTPUT.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
