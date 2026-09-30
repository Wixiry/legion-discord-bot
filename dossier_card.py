# -*- coding: utf-8 -*-
"""LEGION CRT dossier card — PNG for public /me."""
from __future__ import annotations

import math
import random
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    _LANCZOS = Image.LANCZOS

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / 'fonts'

# Site CRT palette (legion_crt.css)
CASE = (8, 0, 0, 255)
LIP = (48, 4, 4, 255)
WELL = (6, 0, 0, 255)
PHOS = (255, 38, 28, 255)
RED = (255, 38, 28, 255)
PEACH = (255, 72, 58, 255)
DIM = (160, 18, 14, 255)
MUTED = (96, 10, 10, 255)
PANEL = (12, 0, 0, 230)
INK = (255, 72, 58, 255)

OUT_W, OUT_H = 1280, 720
S = 2  # supersample


def _u(v: float) -> int:
    return int(round(v * S))


def _font_ok(p: Path | None) -> bool:
    try:
        return bool(p and p.is_file() and p.stat().st_size > 1024)
    except OSError:
        return False


def _open_font(*names: str, size: int) -> ImageFont.FreeTypeFont | None:
    candidates: list[Path] = []
    for name in names:
        candidates.append(FONT_DIR / name)
    candidates.extend((
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
    ))
    for p in candidates:
        if not _font_ok(p):
            continue
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    return None


def _font_path(*names: str) -> Path | None:
    for name in names:
        p = FONT_DIR / name
        if _font_ok(p):
            return p
    linux = [
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
        Path('/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
    ]
    for p in linux:
        if _font_ok(p):
            return p
    return None


def _tektur(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    font = _open_font('Tektur-Variable.ttf', size=size)
    if font:
        try:
            font.set_variation_by_axes([100.0, float(max(400, min(900, weight)))])
        except Exception:
            pass
        return font
    return _sans(size, bold=weight >= 600)


def _sans(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = 'IBMPlexSans-Bold.ttf' if bold else 'IBMPlexSans-SemiBold.ttf'
    font = _open_font(name, 'IBMPlexSans-Bold.ttf', 'IBMPlexSans-SemiBold.ttf', size=size)
    return font or ImageFont.load_default()


def _mono(size: int, weight: str = 'regular') -> ImageFont.FreeTypeFont:
    names = {
        'regular': ('IBMPlexMono-Regular.ttf', 'IBMPlexMono-SemiBold.ttf', 'IBMPlexMono-Bold.ttf'),
        'semibold': ('IBMPlexMono-SemiBold.ttf', 'IBMPlexMono-Bold.ttf', 'IBMPlexMono-Regular.ttf'),
        'bold': ('IBMPlexMono-Bold.ttf', 'IBMPlexMono-SemiBold.ttf', 'IBMPlexMono-Regular.ttf'),
    }[weight]
    font = _open_font(*names, size=size)
    return font or ImageFont.load_default()


def _text_w(font: ImageFont.ImageFont, text: str) -> float:
    try:
        return float(font.getlength(text))
    except Exception:
        try:
            box = font.getbbox(text)
            return float(box[2] - box[0])
        except Exception:
            return float(len(text) * 8)


def _fit(text: str, max_w: int, maker, sizes: list[int]) -> ImageFont.FreeTypeFont:
    text = text or '—'
    for sz in sizes:
        font = maker(sz)
        if _text_w(font, text) <= max_w:
            return font
    return maker(sizes[-1])


def _fmt_day(s: str) -> str:
    s = str(s or '')
    if len(s) >= 10 and s[4] == '-':
        return s[8:10] + '.' + s[5:7]
    return s


def _cut(x: int, y: int, w: int, h: int, cut: int) -> list[tuple[int, int]]:
    c = min(cut, max(0, w // 4), max(0, h // 4))
    return [
        (x + c, y), (x + w - c, y), (x + w, y + c), (x + w, y + h - c),
        (x + w - c, y + h), (x + c, y + h), (x, y + h - c), (x, y + c),
    ]


def _hexagon(cx: int, cy: int, r: int) -> list[tuple[int, int]]:
    pts = []
    for i in range(6):
        a = math.radians(30 + i * 60)
        pts.append((int(cx + r * math.cos(a)), int(cy + r * math.sin(a))))
    return pts


def _glow_text(
    layers: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    glow: tuple[int, int, int, int] | None = None,
    radius: int = 10,
) -> None:
    if glow is None:
        glow = (fill[0], fill[1], fill[2], 90)
    overlay = Image.new('RGBA', layers.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.text(xy, text, font=font, fill=glow)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=radius))
    layers.alpha_composite(overlay)
    ImageDraw.Draw(layers).text(xy, text, font=font, fill=fill)


def _panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, cut: int = 16) -> None:
    pts = _cut(x, y, w, h, cut)
    draw.polygon(pts, fill=PANEL, outline=PHOS)
    # inner hairline
    inset = 4
    inner = _cut(x + inset, y + inset, w - inset * 2, h - inset * 2, max(8, cut - 4))
    draw.polygon(inner, outline=(255, 90, 66, 70))
    # HUD corners
    tick = 18
    col = (255, 72, 58, 180)
    draw.line([(x + cut, y), (x + cut + tick, y)], fill=col, width=2)
    draw.line([(x, y + cut), (x, y + cut + tick)], fill=col, width=2)
    draw.line([(x + w - cut, y), (x + w - cut - tick, y)], fill=col, width=2)
    draw.line([(x + w, y + cut), (x + w, y + cut + tick)], fill=col, width=2)
    draw.line([(x + cut, y + h), (x + cut + tick, y + h)], fill=col, width=2)
    draw.line([(x, y + h - cut), (x, y + h - cut - tick)], fill=col, width=2)
    draw.line([(x + w - cut, y + h), (x + w - cut - tick, y + h)], fill=col, width=2)
    draw.line([(x + w, y + h - cut), (x + w, y + h - cut - tick)], fill=col, width=2)


def _hazard_strip(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    step = max(10, h * 2)
    i = -h
    while i < w + h:
        draw.polygon(
            [(x + i, y), (x + i + h, y), (x + i, y + h), (x + i - h, y + h)],
            fill=(255, 42, 24, 55),
        )
        i += step


def _draw_ring(im: Image.Image, cx: int, cy: int, r: int, frac: float, width: int = 14) -> None:
    overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    box = (cx - r, cy - r, cx + r, cy + r)
    d.arc(box, start=130, end=410, fill=(138, 64, 56, 180), width=width)
    span = max(0.0, min(1.0, frac))
    if span > 0.005:
        d.arc(box, start=130, end=130 + int(280 * span), fill=PHOS, width=width)
    glow = overlay.filter(ImageFilter.GaussianBlur(radius=6))
    im.alpha_composite(glow)
    im.alpha_composite(overlay)


def _reticle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    draw.polygon(_hexagon(cx, cy, r), outline=PHOS, width=3)
    draw.polygon(_hexagon(cx, cy, r + _u(12)), outline=(255, 90, 66, 90), width=2)
    tick = _u(14)
    for ang in (0, 60, 120, 180, 240, 300):
        a = math.radians(ang)
        x0 = int(cx + (r + _u(4)) * math.cos(a))
        y0 = int(cy + (r + _u(4)) * math.sin(a))
        x1 = int(cx + (r + tick) * math.cos(a))
        y1 = int(cy + (r + tick) * math.sin(a))
        draw.line([(x0, y0), (x1, y1)], fill=PEACH, width=2)


def _pips(draw: ImageDraw.ImageDraw, x: int, y: int, filled: int, total: int, r: int = 5) -> None:
    total = max(1, min(6, total))
    filled = max(0, min(total, filled))
    for i in range(total):
        cx = x + i * (r * 2 + 6)
        box = (cx - r, y - r, cx + r, y + r)
        if i < filled:
            draw.ellipse(box, fill=PHOS, outline=PEACH)
        else:
            draw.ellipse(box, outline=MUTED, width=2)


def _unit_code(plat: str) -> str:
    return {
        'ШТУРМОВОЙ': 'STORM',
        'ОФИЦЕРСКИЙ': 'OFFICER',
        'МОСТОВОЙ': 'BRIDGE',
        'КОМАНДНЫЙ': 'COMMAND',
        'ЯДРО': 'CORE',
        'ХМР': 'HMR',
        'ХИМЕРА': 'HMR',
    }.get(str(plat or '').upper(), 'UNIT')


def _mini_bar(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    frac: float,
    ok: bool,
) -> None:
    draw.rectangle((x, y, x + w, y + h), fill=(12, 8, 7, 220), outline=(255, 90, 66, 70))
    span = max(0.0, min(1.0, frac))
    fill_w = int((w - 2) * span)
    if fill_w > 0:
        col = PHOS if ok else DIM
        draw.rectangle((x + 1, y + 1, x + 1 + fill_w, y + h - 1), fill=col)


def _readiness_bar(
    im: Image.Image,
    box: tuple[int, int, int, int],
    done: int,
    count: int,
) -> None:
    x, y, w, h = box
    draw = ImageDraw.Draw(im)
    pts = _cut(x, y, w, h, _u(10))
    draw.polygon(pts, fill=(18, 10, 9, 230), outline=(255, 90, 66, 140))
    lab = _mono(_u(12), 'bold')
    ImageDraw.Draw(im).text((x + _u(16), y + _u(10)), 'READINESS', font=lab, fill=DIM)
    frac = (done / float(count)) if count else 0.0
    track_x = x + _u(130)
    track_y = y + (h // 2) - _u(7)
    track_w = w - _u(230)
    track_h = _u(14)
    draw.rectangle((track_x, track_y, track_x + track_w, track_y + track_h), fill=(12, 8, 7, 255))
    fill_w = max(0, int(track_w * max(0.0, min(1.0, frac))))
    if fill_w > 2:
        glow = Image.new('RGBA', im.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rectangle(
            (track_x, track_y - 4, track_x + fill_w, track_y + track_h + 4),
            fill=(255, 42, 24, 90),
        )
        im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=6)))
        ImageDraw.Draw(im).rectangle(
            (track_x + 1, track_y + 1, track_x + fill_w, track_y + track_h - 1),
            fill=PHOS,
        )
    for i in range(1, 4):
        tx = track_x + int(track_w * i / 4)
        draw.line([(tx, track_y - 2), (tx, track_y + track_h + 2)], fill=(255, 72, 58, 50), width=1)
    num = f'{done}/{count}' if count else '0/0'
    nf = _tektur(_u(18), 800)
    nw = _text_w(nf, num)
    _glow_text(im, (x + w - _u(18) - int(nw), y + _u(6)), num, nf, PEACH, radius=_u(4))


def _ghost_word(im: Image.Image, text: str, xy: tuple[int, int], size: int) -> None:
    font = _tektur(size, 900)
    overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).text(xy, text, font=font, fill=(255, 42, 24, 22))
    im.alpha_composite(overlay)


def _default_avatar(size: int) -> Image.Image:
    im = Image.new('RGBA', (size, size), (22, 10, 9, 255))
    d = ImageDraw.Draw(im)
    cx = cy = size // 2
    r = int(size * 0.42)
    d.polygon(_hexagon(cx, cy, r), outline=PHOS, width=max(2, size // 48))
    d.polygon(_hexagon(cx, cy, int(r * 0.72)), outline=DIM, width=max(1, size // 64))
    visor = [cx - r // 3, cy - r // 8, cx + r // 3, cy + r // 4]
    d.rounded_rectangle(visor, radius=size // 18, fill=(40, 12, 10, 255), outline=RED)
    chev = [
        (cx, cy + r // 3),
        (cx - r // 4, cy + r // 2),
        (cx + r // 4, cy + r // 2),
    ]
    d.polygon(chev, fill=PHOS)
    return im


def _load_avatar(avatar_bytes: bytes | None, size: int) -> Image.Image:
    if avatar_bytes:
        try:
            im = Image.open(BytesIO(avatar_bytes))
            if getattr(im, 'is_animated', False):
                im.seek(0)
            im = im.convert('RGBA')
            w, h = im.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            im = im.crop((left, top, left + side, top + side))
            return im.resize((size, size), _LANCZOS)
        except Exception:
            pass
    return _default_avatar(size)


def _circle_mask(size: int) -> Image.Image:
    m = Image.new('L', (size * 4, size * 4), 0)
    ImageDraw.Draw(m).ellipse((1, 1, size * 4 - 2, size * 4 - 2), fill=255)
    return m.resize((size, size), _LANCZOS)


def _avatar_scanlines(im: Image.Image) -> Image.Image:
    overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, im.size[1], 4):
        d.line([(0, y), (im.size[0], y)], fill=(0, 0, 0, 36))
    tint = Image.new('RGBA', im.size, (255, 42, 24, 16))
    out = Image.alpha_composite(im, tint)
    return Image.alpha_composite(out, overlay)


def _status_color(status_id: str) -> tuple[int, int, int, int]:
    return {
        'up': RED,
        'pay': PHOS,
        'ok': PEACH,
        'warn': DIM,
        'empty': MUTED,
    }.get(status_id, DIM)


def _draw_icon(draw: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, r: int, col) -> None:
    if kind == 'balls':
        draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=col, width=3)
        draw.ellipse((cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3), outline=col, width=2)
    elif kind == 'reports':
        draw.rectangle((cx - r, cy - r, cx + r, cy + r), outline=col, width=3)
        for i in range(3):
            yy = cy - r + 10 + i * (r // 2)
            draw.line([(cx - r + 8, yy), (cx + r - 8, yy)], fill=col, width=2)
    elif kind == 'status':
        draw.polygon([(cx - r, cy + r // 2), (cx, cy - r), (cx + r, cy + r // 2)], outline=col, width=3)
        draw.line([(cx, cy - r // 4), (cx, cy + r // 3)], fill=col, width=3)
    else:
        draw.rectangle((cx - r, cy - r // 2, cx + r, cy + r // 2), outline=col, width=3)
        draw.line([(cx - r // 3, cy - r // 2), (cx - r // 3, cy + r // 2)], fill=col, width=2)


def _draw_chassis(im: Image.Image) -> None:
    w, h = im.size
    draw = ImageDraw.Draw(im)
    # case plate
    draw.rectangle((0, 0, w, h), fill=CASE)
    # side bezels
    bezel = _u(44)
    for x0, x1, inward in ((0, bezel, 1), (w - bezel, w, -1)):
        for x in range(x0, x1):
            t = (x - x0) / max(1, x1 - x0)
            if inward < 0:
                t = 1 - t
            shade = int(8 + t * 22)
            draw.line([(x, 0), (x, h)], fill=(shade, shade - 1, max(0, shade - 3), 255))
        # vents
        vx = x0 + (bezel // 2 if inward > 0 else bezel // 2)
        for i in range(18):
            yy = _u(90) + i * _u(28)
            draw.rectangle((vx - _u(6), yy, vx + _u(6), yy + _u(10)), fill=(0, 0, 0, 180))
            draw.line([(vx - _u(6), yy), (vx + _u(6), yy)], fill=(255, 255, 255, 18), width=1)
    # CRT well
    well = (bezel, _u(22), w - bezel, h - _u(28))
    draw.rounded_rectangle(well, radius=_u(28), fill=WELL)
    # phosphor bloom in the well
    bloom = Image.new('RGBA', im.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bloom)
    bd.ellipse(
        (_u(40), _u(-40), _u(520), _u(520)),
        fill=(255, 42, 24, 38),
    )
    bd.ellipse(
        (_u(700), _u(80), _u(1280), _u(700)),
        fill=(255, 90, 66, 22),
    )
    bloom = bloom.filter(ImageFilter.GaussianBlur(radius=_u(48)))
    im.alpha_composite(bloom)


def _scanlines_and_grain(im: Image.Image) -> Image.Image:
    w, h = im.size
    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, h, 2):
        d.line([(0, y), (w, y)], fill=(0, 0, 0, 42))
    rnd = random.Random(11)
    px = overlay.load()
    for _ in range(9000):
        x = rnd.randrange(w)
        y = rnd.randrange(h)
        a = rnd.randint(10, 32)
        px[x, y] = (255, 70, 50, a)
    # vignette
    vig = Image.new('L', (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse((-w // 8, -h // 10, w + w // 8, h + h // 8), fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(radius=90))
    dark = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    shade = Image.new('RGBA', (w, h), (0, 0, 0, 130))
    inv = Image.eval(vig, lambda p: 255 - p)
    shade.putalpha(inv)
    out = Image.alpha_composite(im, overlay)
    return Image.alpha_composite(out, shade)


def _tile(
    im: Image.Image,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
    sub: str,
    icon: str,
    accent: tuple[int, int, int, int],
) -> None:
    x, y, w, h = box
    draw = ImageDraw.Draw(im)
    _panel(draw, x, y, w, h, cut=_u(14))
    cx, cy, r = x + _u(46), y + h // 2, _u(16)
    _draw_icon(draw, icon, cx, cy, r, accent)
    lab_font = _mono(_u(13), 'semibold')
    val_font = _fit(value, w - _u(120), lambda sz: _tektur(sz, 800), [_u(46), _u(40), _u(34), _u(28)])
    sub_font = _mono(_u(14), 'regular')
    tx = x + _u(86)
    _glow_text(im, (tx, y + _u(22)), label, lab_font, DIM, (accent[0], accent[1], accent[2], 70), radius=_u(4))
    _glow_text(im, (tx, y + _u(48)), value, val_font, accent, (accent[0], accent[1], accent[2], 110), radius=_u(8))
    if sub:
        ImageDraw.Draw(im).text((tx, y + h - _u(38)), sub, font=sub_font, fill=MUTED)


def _progress(
    im: Image.Image,
    box: tuple[int, int, int, int],
    reports: int,
    promote: int,
    norm: int,
    need_up: int,
) -> None:
    x, y, w, h = box
    draw = ImageDraw.Draw(im)
    _panel(draw, x, y, w, h, cut=_u(14))
    title = 'ДО ПОВЫШЕНИЯ'
    lab = _mono(_u(13), 'semibold')
    num = _tektur(_u(28), 700)
    _glow_text(im, (x + _u(24), y + _u(18)), title, lab, DIM, radius=_u(4))
    right = f'{reports} / {promote}'
    rw = num.getlength(right)
    _glow_text(im, (x + w - _u(24) - int(rw), y + _u(12)), right, num, PEACH, radius=_u(6))

    track_x = x + _u(24)
    track_y = y + _u(64)
    track_w = w - _u(48)
    track_h = _u(18)
    draw.rectangle((track_x, track_y, track_x + track_w, track_y + track_h), outline=PHOS, width=2)
    frac = 0.0 if promote <= 0 else max(0.0, min(1.0, reports / float(promote)))
    fill_w = int(track_w * frac)
    if fill_w > 4:
        glow = Image.new('RGBA', im.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rectangle((track_x + 2, track_y + 2, track_x + fill_w, track_y + track_h - 2), fill=(255, 42, 24, 200))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
        im.alpha_composite(glow)
        ImageDraw.Draw(im).rectangle(
            (track_x + 2, track_y + 2, track_x + fill_w, track_y + track_h - 2),
            fill=PHOS,
        )
    # ticks: norm marker
    if promote > 0:
        nx = track_x + int(track_w * (norm / float(promote)))
        draw.line([(nx, track_y - _u(4)), (nx, track_y + track_h + _u(4))], fill=PEACH, width=2)
        nf = _mono(_u(12), 'regular')
        ImageDraw.Draw(im).text((nx - _u(10), track_y + track_h + _u(8)), 'НОРМА', font=nf, fill=DIM)

    hint = 'норма набрана' if need_up <= 0 else f'ещё {need_up} до повышения'
    ImageDraw.Draw(im).text((x + _u(24), y + h - _u(36)), hint, font=_mono(_u(14), 'regular'), fill=PEACH)


def render_dossier_png(
    card: dict,
    avatar_bytes: bytes | None = None,
    discord_name: str = '',
) -> bytes:
    """Return PNG bytes of a CRT dossier card."""
    user = card.get('user') or {}
    name = str(user.get('name') or user.get('login') or discord_name or 'ОПЕРАТИВНИК')
    rank = str(user.get('rank') or '—')
    platoon = str(user.get('platoon') or '—')
    callsign = str(user.get('callsign') or '')
    login = str(user.get('login') or '')
    balls = int(card.get('balls') or 0)
    reports = int(card.get('reports') or 0)
    norm = int(card.get('normAt') or 2)
    promo = int(card.get('promoteFrom') or 6)
    need_n = int(card.get('needForNorm') or 0)
    need_u = int(card.get('needForPromote') or 0)
    st = card.get('status') or {}
    label = str(st.get('label') or '—')
    sid = str(st.get('id') or 'empty')
    period = card.get('period') or {}
    pfrom = _fmt_day(period.get('from') or '')
    pto = _fmt_day(period.get('to') or '')
    weeks = int(period.get('weeks') or 2)
    accent = _status_color(sid)

    W, H = OUT_W * S, OUT_H * S
    im = Image.new('RGBA', (W, H), CASE)
    _draw_chassis(im)
    draw = ImageDraw.Draw(im)

    # header
    hx0, hy0 = _u(64), _u(32)
    head = _tektur(_u(22), 700)
    meta = _mono(_u(13), 'semibold')
    _glow_text(im, (hx0, hy0), 'LEGION // DOSSIER', head, PHOS, radius=_u(6))
    right_meta = f'TERM.S  ·  SECURE  ·  {login}'
    mw = meta.getlength(right_meta)
    ImageDraw.Draw(im).text((_u(1280 - 64) - int(mw), hy0 + _u(8)), right_meta, font=meta, fill=DIM)
    draw.line([(_u(64), _u(68)), (_u(1216), _u(68))], fill=PHOS, width=2)
    # live pip
    draw.ellipse((_u(1216), _u(36), _u(1230), _u(50)), fill=RED)
    bloom = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(bloom).ellipse((_u(1208), _u(28), _u(1238), _u(58)), fill=(255, 42, 24, 90))
    im.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(radius=_u(8))))

    # left identity
    lx, ly, lw, lh = _u(56), _u(84), _u(360), _u(572)
    _panel(draw, lx, ly, lw, lh, cut=_u(18))

    av_size = _u(236)
    av = _load_avatar(avatar_bytes, av_size)
    av = _avatar_scanlines(av)
    mask = _circle_mask(av_size)
    av.putalpha(mask)
    cx = lx + lw // 2
    cy = ly + _u(176)
    # glow ring
    ring = Image.new('RGBA', im.size, (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rr = av_size // 2 + _u(22)
    rd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(255, 42, 24, 80))
    im.alpha_composite(ring.filter(ImageFilter.GaussianBlur(radius=_u(18))))
    # hex HUD
    draw.polygon(_hexagon(cx, cy, av_size // 2 + _u(20)), outline=PHOS, width=3)
    draw.polygon(_hexagon(cx, cy, av_size // 2 + _u(30)), outline=(255, 90, 66, 80), width=2)
    im.paste(av, (cx - av_size // 2, cy - av_size // 2), av)
    # inner circle ring
    draw.ellipse(
        (cx - av_size // 2 - 4, cy - av_size // 2 - 4, cx + av_size // 2 + 4, cy + av_size // 2 + 4),
        outline=PEACH,
        width=4,
    )
    draw.ellipse(
        (cx - av_size // 2 - _u(8), cy - av_size // 2 - _u(8), cx + av_size // 2 + _u(8), cy + av_size // 2 + _u(8)),
        outline=(255, 90, 66, 110),
        width=2,
    )

    name_font = _fit(name, lw - _u(36), lambda sz: _tektur(sz, 800), [_u(40), _u(34), _u(28), _u(22)])
    nw = name_font.getlength(name)
    _glow_text(im, (cx - int(nw) // 2, ly + _u(312)), name, name_font, PEACH, radius=_u(8))

    sub = callsign if callsign else (discord_name if discord_name and discord_name != name else '')
    if sub:
        sf = _mono(_u(14), 'regular')
        sw = sf.getlength(sub)
        ImageDraw.Draw(im).text((cx - int(sw) // 2, ly + _u(360)), sub, font=sf, fill=DIM)

    # rank / platoon rows
    row_x = lx + _u(18)
    row_w = lw - _u(36)
    row_h = _u(44)
    row_y = ly + _u(392)
    lf = _mono(_u(12), 'semibold')
    for lab, val in (('ЗВАНИЕ', rank), ('ВЗВОД', platoon)):
        pts = _cut(row_x, row_y, row_w, row_h, _u(8))
        draw.polygon(pts, fill=(28, 14, 12, 230), outline=(255, 90, 66, 140))
        ImageDraw.Draw(im).text((row_x + _u(12), row_y + _u(12)), lab, font=lf, fill=DIM)
        vf = _fit(val, row_w - _u(120), lambda sz: _tektur(sz, 700), [_u(18), _u(16), _u(14)])
        vw = vf.getlength(val)
        ImageDraw.Draw(im).text((row_x + row_w - _u(12) - int(vw), row_y + _u(8)), val, font=vf, fill=PEACH)
        row_y += row_h + _u(8)

    # status chip
    sty = row_y + _u(4)
    pts = _cut(row_x, sty, row_w, _u(52), _u(10))
    draw.polygon(pts, fill=(accent[0], accent[1], accent[2], 40), outline=accent)
    stf = _fit(label, row_w - _u(24), lambda sz: _tektur(sz, 700), [_u(22), _u(18), _u(14)])
    slw = stf.getlength(label)
    _glow_text(im, (lx + lw // 2 - int(slw) // 2, sty + _u(12)), label, stf, accent, radius=_u(6))

    # right grid
    rx, ry = _u(436), _u(84)
    tw, th = _u(382), _u(168)
    gapx, gapy = _u(16), _u(16)
    period_txt = f'{pfrom}–{pto}' if pfrom or pto else '—'
    reports_sub = f'норма {norm} · {weeks} нед'
    if need_n:
        reports_sub = f'до нормы {need_n} · {weeks} нед'
    tiles = [
        ((rx, ry, tw, th), 'БАЛЛЫ', str(balls), 'на счету', 'balls', PHOS),
        ((rx + tw + gapx, ry, tw, th), 'ОТЧЁТЫ', f'{reports} / {norm}', reports_sub, 'reports', PEACH),
        ((rx, ry + th + gapy, tw, th), 'СТАТУС', label, f'шкала {reports}/{promo}', 'status', accent),
        ((rx + tw + gapx, ry + th + gapy, tw, th), 'ПЕРИОД', period_txt, f'{weeks} недели', 'period', DIM),
    ]
    for box, lab, val, sub_s, icon, col in tiles:
        _tile(im, box, lab, val, sub_s, icon, col)

    _progress(
        im,
        (rx, ry + (th + gapy) * 2, tw * 2 + gapx, _u(204)),
        reports,
        promo,
        norm,
        need_u,
    )

    # footer
    foot = _mono(_u(12), 'regular')
    footer = 'LEGION  ·  не для посторонних  ·  код привязки — в Профиле на сайте'
    ImageDraw.Draw(im).text((_u(64), _u(672)), footer, font=foot, fill=MUTED)

    im = im.resize((OUT_W, OUT_H), _LANCZOS)
    im = _scanlines_and_grain(im.convert('RGBA'))
    buf = BytesIO()
    im.convert('RGB').save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_platoon_png(data: dict, avatars: dict[str, bytes] | None = None) -> bytes:
    """CRT unit dossier banner — commander well, roster, readiness strip."""
    avatars = avatars or {}
    plat = str(data.get('platoon') or 'ВЗВОД')
    people = list(data.get('people') or [])
    command = list(data.get('command') or [])
    count = int(data.get('count') or len(people))
    done = int(data.get('done') or 0)
    norm = int(data.get('normAt') or 2)
    period = data.get('period') or {}
    pfrom = _fmt_day(period.get('from') or '')
    pto = _fmt_day(period.get('to') or '')
    code = _unit_code(plat)

    cmd = next((p for p in command if p.get('kind') == 'cmd'), None)
    if cmd is None and command:
        cmd = command[0]
    deputies = [p for p in command if p is not cmd][:2]

    W, H = OUT_W * S, OUT_H * S
    im = Image.new('RGBA', (W, H), CASE)
    _draw_chassis(im)
    draw = ImageDraw.Draw(im)

    _hazard_strip(draw, _u(64), _u(24), _u(1152), _u(12))
    head = _tektur(_u(18), 700)
    meta = _mono(_u(12), 'semibold')
    stamp = _mono(_u(13), 'semibold')
    _glow_text(im, (_u(64), _u(40)), 'LEGION // UNIT DOSSIER', head, PHOS, radius=_u(6))
    live = _mono(_u(12), 'bold')
    ImageDraw.Draw(im).text((_u(1120), _u(46)), 'LIVE', font=live, fill=RED)
    pip = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(pip).ellipse((_u(1090), _u(40), _u(1116), _u(66)), fill=(255, 42, 24, 110))
    im.alpha_composite(pip.filter(ImageFilter.GaussianBlur(radius=_u(6))))
    draw.ellipse((_u(1098), _u(48), _u(1114), _u(64)), fill=RED)
    draw.line([(_u(64), _u(72)), (_u(1216), _u(72))], fill=PHOS, width=2)

    plat_f = _fit(plat, _u(780), lambda sz: _tektur(sz, 900), [_u(48), _u(38), _u(30)])
    _glow_text(im, (_u(64), _u(78)), plat, plat_f, PEACH, radius=_u(12))
    sub = f'CLASSIFICATION · INTERNAL  ·  UNIT/{code}'
    ImageDraw.Draw(im).text((_u(64), _u(128)), sub, font=stamp, fill=MUTED)
    period_txt = f'{pfrom}–{pto}' if pfrom or pto else '—'
    pr = _text_w(meta, period_txt)
    ImageDraw.Draw(im).text((_u(1216) - int(pr), _u(128)), period_txt, font=meta, fill=DIM)

    lx, ly, lw, lh = _u(56), _u(152), _u(348), _u(448)
    _panel(draw, lx, ly, lw, lh, cut=_u(18))
    draw.rectangle((lx + _u(8), ly + _u(14), lx + _u(14), ly + lh - _u(14)), fill=PHOS)
    ImageDraw.Draw(im).text((lx + _u(24), ly + _u(14)), 'CMD WELL', font=meta, fill=MUTED)

    av_size = _u(196)
    cmd_did = str((cmd or {}).get('discordId') or '')
    av = _avatar_scanlines(_load_avatar(avatars.get(cmd_did), av_size))
    mask = _circle_mask(av_size)
    av.putalpha(mask)
    cx = lx + lw // 2 + _u(8)
    cy = ly + _u(148)
    bloom = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(bloom).ellipse(
        (cx - av_size, cy - av_size, cx + av_size, cy + av_size),
        fill=(255, 42, 24, 60),
    )
    im.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(radius=_u(24))))
    _reticle(draw, cx, cy, av_size // 2 + _u(12))
    im.paste(av, (cx - av_size // 2, cy - av_size // 2), av)
    draw.ellipse(
        (cx - av_size // 2 - 3, cy - av_size // 2 - 3, cx + av_size // 2 + 3, cy + av_size // 2 + 3),
        outline=PEACH,
        width=3,
    )

    cmd_name = str((cmd or {}).get('name') or 'не назначен')
    cmd_rank = str((cmd or {}).get('rank') or (cmd or {}).get('role') or 'командир')
    nf = _fit(cmd_name, lw - _u(40), lambda sz: _tektur(sz, 800), [_u(28), _u(22), _u(18)])
    nw = _text_w(nf, cmd_name)
    _glow_text(im, (cx - int(nw) // 2, ly + _u(268)), cmd_name, nf, PEACH, radius=_u(6))

    chip_w, chip_h = _u(72), _u(26)
    chip_x = cx - chip_w // 2
    chip_y = ly + _u(308)
    chip = _cut(chip_x, chip_y, chip_w, chip_h, _u(6))
    draw.polygon(chip, fill=(255, 42, 24, 50), outline=PHOS)
    cw = _text_w(stamp, 'КМД')
    ImageDraw.Draw(im).text((chip_x + (chip_w - int(cw)) // 2, chip_y + _u(4)), 'КМД', font=stamp, fill=PHOS)
    rf = _fit(cmd_rank, lw - _u(36), lambda sz: _mono(sz, 'regular'), [_u(13), _u(12)])
    rw = _text_w(rf, cmd_rank)
    ImageDraw.Draw(im).text((cx - int(rw) // 2, ly + _u(340)), cmd_rank, font=rf, fill=DIM)

    row_x, row_w = lx + _u(22), lw - _u(40)
    row_y = ly + _u(372)
    if deputies:
        for dep in deputies[:2]:
            pts = _cut(row_x, row_y, row_w, _u(32), _u(8))
            draw.polygon(pts, fill=(40, 14, 12, 230), outline=(255, 90, 66, 150))
            dname = str(dep.get('name') or '—')
            vf = _fit('ЗАМ  ' + dname, row_w - _u(16), lambda sz: _tektur(sz, 700), [_u(14), _u(12)])
            ImageDraw.Draw(im).text((row_x + _u(10), row_y + _u(6)), 'ЗАМ  ' + dname, font=vf, fill=PEACH)
            row_y += _u(38)
    else:
        ImageDraw.Draw(im).text((row_x + _u(4), row_y + _u(8)), 'зам не указан', font=meta, fill=MUTED)

    rx, ry, rww, rhh = _u(420), _u(152), _u(796), _u(448)
    _panel(draw, rx, ry, rww, rhh, cut=_u(16))
    _glow_text(im, (rx + _u(22), ry + _u(12)), 'СОСТАВ', _tektur(_u(18), 700), DIM, radius=_u(4))
    head_r = f'{count} чел.'
    hw = _text_w(meta, head_r)
    ImageDraw.Draw(im).text((rx + rww - _u(22) - int(hw), ry + _u(18)), head_r, font=meta, fill=MUTED)
    draw.line([(rx + _u(18), ry + _u(46)), (rx + rww - _u(18), ry + _u(46))], fill=(255, 90, 66, 90), width=2)
    _ghost_word(im, code, (rx + _u(24), ry + _u(120)), _u(132))

    npeople = len(people)
    if npeople > 16:
        cols, max_rows = 3, 8
    elif npeople > 8:
        cols, max_rows = 2, 11
    else:
        cols, max_rows = 1, 8
    shown = people[: max_rows * cols]
    col_w = (rww - _u(28)) // cols
    row_h = max(_u(32), (rhh - _u(58)) // max_rows)
    idx_f = _mono(_u(11), 'bold')
    rank_font = _mono(_u(11), 'regular')
    name_max = col_w - (_u(108) if cols >= 3 else _u(150))
    show_rank = row_h >= _u(44)
    for i, person in enumerate(shown):
        col = i % cols
        row = i // cols
        x0 = rx + _u(12) + col * (col_w + _u(6))
        y0 = ry + _u(52) + row * row_h
        kind = str(person.get('kind') or 'troop')
        nm = str(person.get('name') or '—')
        rk = str(person.get('rank') or '')
        reps = int(person.get('reports') or 0)
        ok = bool(person.get('ok'))
        fill = (52, 16, 14, 210) if kind in ('cmd', 'deputy') else (
            (30, 14, 12, 190) if row % 2 == 0 else (22, 11, 10, 180)
        )
        rh = max(_u(24), row_h - _u(6))
        pts = _cut(x0, y0, col_w - _u(6), rh, _u(6))
        draw.polygon(pts, fill=fill, outline=(255, 90, 66, 80))
        accent = PHOS if ok else MUTED
        ay0, ay1 = y0 + _u(5), y0 + rh - _u(5)
        if ay1 > ay0:
            draw.rectangle((x0, ay0, x0 + _u(5), ay1), fill=accent)
        idx = f'{i + 1:02d}'
        ImageDraw.Draw(im).text((x0 + _u(10), y0 + _u(6)), idx, font=idx_f, fill=MUTED)
        gx, gy = x0 + _u(34), y0 + (rh // 2)
        if kind == 'cmd':
            draw.polygon([(gx, gy - 5), (gx + 5, gy), (gx, gy + 5), (gx - 5, gy)], fill=PHOS)
        elif kind == 'deputy':
            draw.polygon([(gx, gy - 5), (gx + 5, gy), (gx, gy + 5), (gx - 5, gy)], outline=PHOS, width=2)
        elif kind == 'officer':
            draw.ellipse((gx - 4, gy - 4, gx + 4, gy + 4), outline=PHOS, width=2)
        else:
            draw.ellipse((gx - 3, gy - 3, gx + 3, gy + 3), outline=MUTED if not ok else DIM, width=2)
        lf = _fit(nm, name_max, lambda sz: _tektur(sz, 700), [_u(15), _u(13), _u(11)])
        ImageDraw.Draw(im).text((x0 + _u(44), y0 + _u(5)), nm, font=lf, fill=PEACH if ok else DIM)
        if show_rank and rk:
            rk_f = _fit(rk, name_max, lambda sz: _mono(sz, 'regular'), [_u(11), _u(10)])
            ImageDraw.Draw(im).text((x0 + _u(44), y0 + _u(24)), rk, font=rk_f, fill=MUTED)
        bar_w = _u(56) if cols >= 3 else _u(72)
        bar_x = x0 + col_w - _u(16) - bar_w
        bar_y = y0 + rh - _u(14)
        if bar_y > y0 + _u(4):
            _mini_bar(draw, bar_x, bar_y, bar_w, _u(7), reps / float(max(norm, 1)), ok)
        score = f'{reps}/{norm}'
        sw = _text_w(rank_font, score)
        ImageDraw.Draw(im).text(
            (bar_x + bar_w - int(sw), y0 + _u(5)),
            score,
            font=rank_font,
            fill=PEACH if ok else MUTED,
        )

    extra = count - len(shown)
    if extra > 0:
        ImageDraw.Draw(im).text((rx + _u(22), ry + rhh - _u(22)), f'+ ещё {extra}', font=meta, fill=DIM)

    _readiness_bar(im, (_u(56), _u(612), _u(1160), _u(44)), done, count)

    foot = _mono(_u(12), 'regular')
    ImageDraw.Draw(im).text(
        (_u(64), _u(668)),
        'LEGION  ·  не для посторонних  ·  unit dossier',
        font=foot,
        fill=MUTED,
    )

    im = im.resize((OUT_W, OUT_H), _LANCZOS)
    im = _scanlines_and_grain(im.convert('RGBA'))
    buf = BytesIO()
    im.convert('RGB').save(buf, format='PNG', optimize=True)
    return buf.getvalue()


if __name__ == '__main__':
    sample = {
        'user': {
            'name': 'Виксири',
            'login': 'viksiri',
            'rank': 'Мл.Лейтенант',
            'platoon': 'ХМР',
            'callsign': '',
        },
        'balls': 0,
        'reports': 0,
        'normAt': 2,
        'promoteFrom': 6,
        'needForNorm': 2,
        'needForPromote': 6,
        'status': {'id': 'empty', 'label': 'НЕТ СДАЧИ'},
        'period': {'from': '2026-08-31', 'to': '2026-09-13', 'weeks': 2},
    }
    out = Path(__file__).resolve().parents[1] / '_logs' / 'preview_dossier.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_dossier_png(sample, discord_name='Виксири'))
    print('wrote', out, out.stat().st_size)
