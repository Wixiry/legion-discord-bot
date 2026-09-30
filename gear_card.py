# -*- coding: utf-8 -*-
"""LEGION CRT gear cards — modular loadout renderer for Discord /gear."""
from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

try:
    from dossier_card import (  # type: ignore
        CASE, DIM, MUTED, OUT_H, OUT_W, PANEL, PEACH, PHOS, RED, S,
        _draw_chassis, _glow_text, _mono, _scanlines_and_grain, _tektur, _text_w, _u,
    )
except Exception:  # pragma: no cover
    from bot.dossier_card import (  # type: ignore
        CASE, DIM, MUTED, OUT_H, OUT_W, PANEL, PEACH, PHOS, RED, S,
        _draw_chassis, _glow_text, _mono, _scanlines_and_grain, _tektur, _text_w, _u,
    )

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / 'discord_assets' / 'gear'

ICON_MAP = {
    'TRAITOR': 'traitor.png',
    'HAVOC': 'havoc.png',
    'CHAOS': 'chaos.png',
    'POISON': 'poison.png',
    'AR2': 'ar2.png',
    'REAPER': 'reaper.png',
    'FREEDOM': 'freedom.png',
    'SPAS-12': 'spas-12.png',
    'TERRIBLE': 'terrible.png',
    'P2020': 'p2020.png',
    'USP-MATCH': 'usp-match.png',
    'OSP': 'osp.png',
    'JUDGE': 'judge.png',
    'LMINE': 'lmine.png',
    'LSCANNER': 'lscanner.png',
    'CHASER': 'chaser.png',
    'SCOUT': 'scout.png',
    'BEE': 'bee.png',
}

STAT_BASE = {
    'TRAITOR': (200, 140, 100),
    'HAVOC': (220, 180, 120),
    'CHAOS': (240, 160, 130),
    'POISON': (190, 120, 95),
}
STAT_BONUS = {
    'LMINE': (0, 0, 12), 'LSCANNER': (0, 8, 6), 'CHASER': (8, 2, 4),
    'SCOUT': (4, 0, 8), 'BEE': (6, 0, 6),
    'AR2': (0, 4, 8), 'REAPER': (0, 6, 10), 'FREEDOM': (0, 5, 9),
    'SPAS-12': (0, 2, 12), 'TERRIBLE': (0, 8, 14),
    'P2020': (0, 0, 4), 'USP-MATCH': (0, 0, 5), 'OSP': (0, 0, 5), 'JUDGE': (0, 2, 7),
}

SLOT_ORDER = (
    ('primary1', 'PRIMARY 1'),
    ('primary2', 'PRIMARY 2'),
    ('primary3', 'PRIMARY 3'),
    ('pistol', 'PISTOL'),
    ('device', 'DEVICE'),
)


# ─── components ───────────────────────────────────────────────────────────────

class GearAssets:
    """Load / cache gear icons from discord_assets/gear."""

    def __init__(self, root: Path | None = None):
        self.root = root or ASSET_DIR
        self._cache: dict[str, Image.Image | None] = {}

    def icon(self, name: str) -> Image.Image | None:
        key = str(name or '').upper().strip()
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        fname = ICON_MAP.get(key)
        if not fname:
            self._cache[key] = None
            return None
        path = self.root / fname
        if not path.is_file():
            self._cache[key] = None
            return None
        try:
            im = Image.open(path).convert('RGBA')
            self._cache[key] = im
            return im
        except Exception:
            self._cache[key] = None
            return None

    def fit(self, name: str, max_w: int, max_h: int) -> Image.Image | None:
        src = self.icon(name)
        if src is None:
            return None
        im = src.copy()
        im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS)
        return im


def calc_stats(slots: dict) -> dict:
    unit = str((slots or {}).get('unit') or '').upper()
    hp = armor = tough = 0
    live = False
    if unit in STAT_BASE:
        hp, armor, tough = STAT_BASE[unit]
        live = True
    elif unit:
        hp, armor, tough = 180, 120, 90
        live = True
    for k, _ in SLOT_ORDER:
        n = str((slots or {}).get(k) or '').upper()
        if not n:
            continue
        live = True
        b = STAT_BONUS.get(n)
        if b:
            hp += b[0]
            armor += b[1]
            tough += b[2]
        else:
            tough += 4
    return {'hp': hp, 'armor': armor, 'tough': tough, 'live': live}


def _panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill=PANEL, outline=None) -> None:
    x, y, w, h = box
    draw.rectangle((x, y, x + w, y + h), fill=fill, outline=outline or (255, 90, 66, 120), width=max(1, _u(1)))


def draw_header(im: Image.Image, *, title: str, subtitle: str) -> None:
    d = ImageDraw.Draw(im)
    title_f = _tektur(_u(26), 800) or _mono(_u(24), 'bold')
    sub_f = _mono(_u(12), 'semibold')
    _glow_text(im, (_u(56), _u(36)), title, title_f, PEACH, radius=_u(5))
    d.text((_u(56), _u(70)), subtitle[:70], font=sub_f, fill=DIM)
    d.line([(_u(56), _u(94)), (_u(1224), _u(94))], fill=PHOS, width=2)
    # live pip
    d.ellipse((_u(1210), _u(42), _u(1224), _u(56)), fill=RED)


def draw_stat_pills(im: Image.Image, stats: dict, origin: tuple[int, int]) -> None:
    d = ImageDraw.Draw(im)
    x0, y0 = origin
    lab_f = _mono(_u(10), 'semibold')
    val_f = _tektur(_u(18), 700) or _mono(_u(16), 'bold')
    items = (
        ('♥', 'HP', stats.get('hp') if stats.get('live') else '—'),
        ('▣', 'ARMOR', stats.get('armor') if stats.get('live') else '—'),
        ('◈', 'TOUGH', stats.get('tough') if stats.get('live') else '—'),
    )
    gap = _u(8)
    w = _u(88)
    h = _u(54)
    for i, (ico, lab, val) in enumerate(items):
        x = x0 + i * (w + gap)
        _panel(d, (x, y0, w, h), fill=(18, 8, 7, 230), outline=(255, 90, 66, 140))
        d.text((x + _u(8), y0 + _u(6)), ico, font=lab_f, fill=PHOS)
        d.text((x + _u(8), y0 + _u(22)), str(val), font=val_f, fill=PEACH)
        d.text((x + _u(50), y0 + _u(8)), lab, font=lab_f, fill=MUTED)


def draw_unit_stage(
    im: Image.Image,
    assets: GearAssets,
    *,
    box: tuple[int, int, int, int],
    unit: str,
    callsign: str,
    platoon: str,
) -> None:
    d = ImageDraw.Draw(im)
    x, y, w, h = box
    # stage well
    d.rectangle((x, y, x + w, y + h), fill=(6, 0, 0, 255), outline=(255, 60, 50, 160), width=max(2, _u(2)))
    # grid
    for gx in range(x + _u(10), x + w - _u(10), _u(18)):
        d.line([(gx, y + _u(8)), (gx, y + h - _u(8))], fill=(255, 40, 30, 18), width=1)
    for gy in range(y + _u(10), y + h - _u(10), _u(18)):
        d.line([(x + _u(8), gy), (x + w - _u(8), gy)], fill=(255, 40, 30, 18), width=1)
    # bloom
    bloom = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(bloom).ellipse(
        (x + w // 4, y + h // 5, x + 3 * w // 4, y + 4 * h // 5),
        fill=(255, 42, 24, 55),
    )
    im.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(radius=_u(28))))

    tag_f = _mono(_u(12), 'bold')
    unit_up = str(unit or '').upper() or 'STANDBY'
    d.text((x + _u(14), y + _u(12)), f'{unit_up} // UNIT', font=tag_f, fill=PHOS)
    d.text((x + w - _u(110), y + _u(12)), 'LOADOUT', font=tag_f, fill=MUTED)

    fig = assets.fit(unit_up, _u(320), _u(420)) if unit_up != 'STANDBY' else None
    if fig is not None:
        fx = x + (w - fig.width) // 2
        fy = y + (h - fig.height) // 2 + _u(10)
        # soft ground shadow
        shadow = Image.new('RGBA', im.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse(
            (fx + _u(20), fy + fig.height - _u(18), fx + fig.width - _u(20), fy + fig.height + _u(10)),
            fill=(0, 0, 0, 120),
        )
        im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=_u(10))))
        im.paste(fig, (fx, fy), fig)
    else:
        empty_f = _mono(_u(14), 'semibold')
        msg = 'НЕТ КОМПЛЕКТА UNIT'
        tw = _text_w(empty_f, msg)
        d.text((x + (w - int(tw)) // 2, y + h // 2), msg, font=empty_f, fill=MUTED)

    lore_f = _mono(_u(11), 'semibold')
    name_f = _tektur(_u(16), 700) or _mono(_u(14), 'bold')
    d.text((x + _u(14), y + h - _u(52)), str(callsign or '—')[:22], font=name_f, fill=PEACH)
    d.text((x + _u(14), y + h - _u(28)), str(platoon or '—')[:28], font=lore_f, fill=DIM)


def draw_slot_stack(
    im: Image.Image,
    assets: GearAssets,
    *,
    box: tuple[int, int, int, int],
    slots: dict,
) -> None:
    d = ImageDraw.Draw(im)
    x, y, w, h = box
    title_f = _mono(_u(11), 'bold')
    d.text((x, y), 'LOADOUT SLOTS', font=title_f, fill=PHOS)
    y += _u(22)
    n = len(SLOT_ORDER)
    gap = _u(8)
    avail = h - _u(22) - gap * (n - 1)
    slot_h = max(_u(54), avail // n)
    lab_f = _mono(_u(9), 'semibold')
    name_f = _tektur(_u(13), 700) or _mono(_u(12), 'bold')
    ph_f = _mono(_u(10))

    for i, (key, label) in enumerate(SLOT_ORDER):
        sy = y + i * (slot_h + gap)
        compact = key == 'device'
        sh = slot_h - (_u(10) if compact else 0)
        if compact:
            sy += _u(4)
        filled = str((slots or {}).get(key) or '').upper()
        border = (255, 90, 66, 170) if filled else (255, 60, 50, 90)
        style = 'solid' if filled else 'dashed'
        _panel(d, (x, sy, w, sh), fill=(10, 0, 0, 220), outline=border)
        if style == 'dashed' and not filled:
            # dashed feel via inner corners
            d.rectangle((x + 2, sy + 2, x + w - 2, sy + sh - 2), outline=(255, 60, 50, 40), width=1)
        d.text((x + _u(8), sy + _u(5)), label, font=lab_f, fill=MUTED)
        if filled:
            icon = assets.fit(filled, _u(120), sh - _u(22))
            if icon is not None:
                ix = x + (w - icon.width) // 2
                iy = sy + (sh - icon.height) // 2 + _u(4)
                im.paste(icon, (ix, iy), icon)
            d.text((x + _u(8), sy + sh - _u(18)), filled[:16], font=name_f, fill=PEACH)
        else:
            msg = 'клик / drop'
            tw = _text_w(ph_f, msg)
            d.text((x + (w - int(tw)) // 2, sy + sh // 2 - _u(6)), msg, font=ph_f, fill=MUTED)


def draw_readiness_strip(im: Image.Image, *, ready_n: int, total: int, y: int) -> None:
    d = ImageDraw.Draw(im)
    f = _mono(_u(12), 'bold')
    d.text((_u(56), y), f'ГОТОВНОСТЬ · {ready_n} / {total}', font=f, fill=PHOS)
    bar_x, bar_y = _u(280), y + _u(4)
    bar_w, bar_h = _u(400), _u(12)
    d.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), fill=(12, 8, 7, 255), outline=(255, 90, 66, 80))
    frac = (ready_n / float(total)) if total else 0.0
    fill = int(bar_w * max(0.0, min(1.0, frac)))
    if fill > 2:
        d.rectangle((bar_x + 1, bar_y + 1, bar_x + fill, bar_y + bar_h - 1), fill=PHOS)


def draw_roster_columns(
    im: Image.Image,
    *,
    ready: list,
    pending: list,
    y0: int,
) -> None:
    d = ImageDraw.Draw(im)
    sub_f = _mono(_u(12), 'bold')
    row_f = _mono(_u(12))
    small_f = _mono(_u(10))
    left_x, right_x = _u(56), _u(660)
    d.text((left_x, y0), f'ГОТОВЫ · {len(ready)}', font=sub_f, fill=PHOS)
    d.text((right_x, y0), f'НЕ СДЕЛАЛИ · {len(pending)}', font=sub_f, fill=(255, 136, 102, 255))
    y = y0 + _u(26)
    row_h = _u(26)
    max_rows = 11

    def col(x: int, rows: list, pending_mode: bool) -> None:
        yy = y
        if not rows:
            d.text((x, yy), '— пусто —', font=small_f, fill=MUTED)
            return
        for r in rows[:max_rows]:
            cs = str(r.get('callsign') or '—')[:16]
            plat = str(r.get('platoon') or '—')[:10]
            summary = str(r.get('summary') or '—')[:36]
            d.text((x, yy), cs, font=row_f, fill=PEACH if not pending_mode else (200, 120, 90, 255))
            tw = _text_w(row_f, cs)
            d.text((x + int(tw) + _u(8), yy + _u(1)), plat, font=small_f, fill=MUTED)
            d.text(
                (x, yy + _u(13)),
                summary if not pending_mode else 'нет комплекта UNIT',
                font=small_f,
                fill=DIM if not pending_mode else (255, 136, 102, 200),
            )
            yy += row_h
        if len(rows) > max_rows:
            d.text((x, yy), f'… +{len(rows) - max_rows}', font=small_f, fill=MUTED)

    col(left_x, ready, False)
    col(right_x, pending, True)


def _finalize(im: Image.Image) -> bytes:
    im = _scanlines_and_grain(im)
    out = im.resize(
        (OUT_W, OUT_H),
        Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS,
    )
    buf = BytesIO()
    out.convert('RGB').save(buf, format='PNG', optimize=True)
    return buf.getvalue()


# ─── public renderers ─────────────────────────────────────────────────────────

def render_gear_person_png(user: dict, assets: GearAssets | None = None) -> bytes:
    """Single-operator visual loadout card (site mygear layout)."""
    assets = assets or GearAssets()
    slots = user.get('slots') or {}
    callsign = str(user.get('callsign') or '—')
    platoon = str(user.get('platoon') or '—')
    unit = str(slots.get('unit') or '').upper()
    ready = bool(user.get('ready') or unit)
    stats = calc_stats(slots)

    W, H = OUT_W * S, OUT_H * S
    im = Image.new('RGBA', (W, H), CASE)
    _draw_chassis(im)

    status = 'READY' if ready else 'NOT READY'
    draw_header(
        im,
        title='◈ МОЁ СНАРЯЖЕНИЕ',
        subtitle=f'{callsign} · {platoon} · {status}',
    )
    draw_stat_pills(im, stats, (_u(920), _u(28)))

    draw_unit_stage(
        im,
        assets,
        box=(_u(56), _u(110), _u(720), _u(540)),
        unit=unit,
        callsign=callsign,
        platoon=platoon,
    )
    draw_slot_stack(
        im,
        assets,
        box=(_u(800), _u(110), _u(424), _u(540)),
        slots=slots,
    )

    foot = _mono(_u(11))
    ImageDraw.Draw(im).text(
        (_u(56), _u(670)),
        'LEGION TERMINAL · /gear · LOADOUT CARD',
        font=foot,
        fill=MUTED,
    )
    return _finalize(im)


def render_gear_board_png(data: dict, assets: GearAssets | None = None) -> bytes:
    """Readiness board: summary + ready/pending lists (+ optional featured loadout strip)."""
    assets = assets or GearAssets()
    ready = list(data.get('ready') or [])
    pending = list(data.get('pending') or [])
    total = int(data.get('total') or (len(ready) + len(pending)))
    ready_n = int(data.get('readyCount') or len(ready))

    W, H = OUT_W * S, OUT_H * S
    im = Image.new('RGBA', (W, H), CASE)
    _draw_chassis(im)

    draw_header(
        im,
        title='◈ LOADOUT READY BOARD',
        subtitle=f'ГОТОВЫ {ready_n} / {total} · выберите оперативника ниже',
    )
    draw_readiness_strip(im, ready_n=ready_n, total=total, y=_u(108))

    # featured: first ready operator mini-stage
    featured = ready[0] if ready else None
    if featured:
        slots = featured.get('slots') or {}
        draw_unit_stage(
            im,
            assets,
            box=(_u(56), _u(140), _u(420), _u(300)),
            unit=str(slots.get('unit') or ''),
            callsign=str(featured.get('callsign') or '—'),
            platoon=str(featured.get('platoon') or '—'),
        )
        draw_slot_stack(
            im,
            assets,
            box=(_u(500), _u(140), _u(280), _u(300)),
            slots=slots,
        )
        # mini label
        f = _mono(_u(11), 'bold')
        ImageDraw.Draw(im).text(
            (_u(800), _u(150)),
            'FEATURED READY',
            font=f,
            fill=DIM,
        )
        draw_roster_columns(im, ready=ready, pending=pending, y0=_u(460))
    else:
        draw_roster_columns(im, ready=ready, pending=pending, y0=_u(150))

    foot = _mono(_u(11))
    ImageDraw.Draw(im).text(
        (_u(56), _u(670)),
        'LEGION · список оперативников — в меню под сообщением',
        font=foot,
        fill=MUTED,
    )
    return _finalize(im)


def slot_line(slots: dict) -> str:
    parts = []
    for k in ('unit', 'primary1', 'primary2', 'primary3', 'pistol', 'device'):
        v = (slots or {}).get(k) or ''
        if v:
            parts.append(str(v))
    return ' · '.join(parts) if parts else '—'
