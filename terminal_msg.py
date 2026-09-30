# -*- coding: utf-8 -*-
"""LEGION terminal Components V2 / embed fallback for Discord messages."""
from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

import discord

log = logging.getLogger('legion.terminal_msg')

CRT_RED = 0xE83232
CRT_DIM = 0xB01414
V2_FLAG = 32768
EPHEMERAL_FLAG = 64
ASSETS = Path(__file__).resolve().parent / 'discord_assets'
SITE_ASSETS = Path(__file__).resolve().parent.parent / 'api' / 'discord_assets'


def _asset_dirs() -> list[Path]:
    return [ASSETS, SITE_ASSETS]


def banner_bytes(kind: str) -> bytes | None:
    kind = {
        'award': 'award',
        'deduct': 'deduct',
        'review_ok': 'review_ok',
        'review_no': 'review_no',
        'generic': 'generic',
        'error': 'review_no',
    }.get(str(kind or 'generic'), 'generic')
    names = [f'dm_{kind}.png', f'banner_{kind}.png', 'dm_generic.png', 'banner_generic.png']
    for folder in _asset_dirs():
        for name in names:
            path = folder / name
            if not path.is_file():
                continue
            try:
                return path.read_bytes()
            except OSError:
                continue
    return None


def score_markdown(
    *,
    title: str,
    name: str = '',
    delta: str = '',
    scores: str = '',
    reason: str = '',
    actor: str = '',
    mention: str = '',
    extra: str = '',
) -> str:
    lines = ['## LEGION', f'**{title}**']
    if mention:
        lines.append(f'<@{mention}>')
    if name:
        lines.append(f'**Оперативник:** {name}')
    if delta:
        lines.append(f'**Изменение:** `{delta}`')
    if scores:
        lines.append(f'**На сайте:** {scores}')
    if reason:
        lines += ['', '### ПРИЧИНА', f'> {reason.replace(chr(10), " ")}']
    if extra:
        lines += ['', extra]
    foot = f'оператор · {actor} · Рота LEGION' if actor else 'Рота LEGION · не для посторонних'
    lines += ['', f'-# {foot}']
    return '\n'.join(lines)[:3900]


def _v2_payload(
    markdown: str,
    filename: str | None,
    accent: int,
    mention_ids: list[str] | None,
    ephemeral: bool = False,
) -> dict[str, Any]:
    inner: list[dict[str, Any]] = []
    if filename:
        inner.append({
            'type': 12,
            'items': [{'media': {'url': f'attachment://{filename}'}, 'description': 'LEGION TERMINAL'}],
        })
        inner.append({'type': 14, 'divider': True, 'spacing': 1})
    inner.append({'type': 10, 'content': markdown})
    flags = V2_FLAG
    if ephemeral:
        flags |= EPHEMERAL_FLAG
    payload: dict[str, Any] = {
        'flags': flags,
        'components': [{
            'type': 17,
            'accent_color': accent,
            'spoiler': False,
            'components': inner,
        }],
        'allowed_mentions': {'parse': [], 'users': mention_ids or [], 'replied_user': False},
    }
    return payload


async def send_terminal(
    dest: Any,
    *,
    markdown: str,
    png: bytes | None = None,
    filename: str = 'legion.png',
    accent: int = CRT_RED,
    mention_ids: list[str] | None = None,
    ephemeral: bool = False,
) -> bool:
    """Send Components V2; fall back to embed+image. dest = channel or Interaction."""
    import aiohttp

    interaction = dest if isinstance(dest, discord.Interaction) else None
    channel = dest if interaction is None else interaction.channel
    eph = bool(ephemeral and interaction is not None)
    payload = _v2_payload(markdown, filename if png else None, accent, mention_ids, ephemeral=eph)
    token = ''
    session = None
    if interaction is not None:
        token = str(getattr(interaction.client.http, 'token', '') or '')
        session = getattr(interaction.client.http, '_HTTPClient__session', None)
        url = (
            f'https://discord.com/api/v10/webhooks/{interaction.application_id}/'
            f'{interaction.token}?wait=true&with_components=true'
        )
        headers = {'Authorization': f'Bot {token}'} if token else {}
    else:
        http = getattr(getattr(channel, '_state', None), 'http', None)
        token = str(getattr(http, 'token', '') or '') if http else ''
        session = getattr(http, '_HTTPClient__session', None) if http else None
        url = f'https://discord.com/api/v10/channels/{channel.id}/messages'
        headers = {'Authorization': f'Bot {token}'} if token else {}

    try:
        form = aiohttp.FormData()
        form.add_field(
            'payload_json',
            json.dumps(payload, ensure_ascii=False),
            content_type='application/json',
        )
        if png:
            form.add_field('files[0]', png, filename=filename, content_type='image/png')
        close = False
        if session is None:
            session = aiohttp.ClientSession()
            close = True
        try:
            async with session.post(url, data=form, headers=headers) as resp:
                if 200 <= resp.status < 300:
                    return True
                log.warning('v2 send %s %s', resp.status, (await resp.text())[:280])
        finally:
            if close:
                await session.close()
    except Exception:
        log.exception('components v2 send failed')

    try:
        embed = discord.Embed(description=markdown[:4096], color=accent)
        kwargs: dict[str, Any] = {'embed': embed}
        if png:
            embed.set_image(url=f'attachment://{filename}')
            kwargs['file'] = discord.File(BytesIO(png), filename=filename)
        if interaction is not None:
            kwargs['ephemeral'] = eph
            if interaction.response.is_done():
                await interaction.followup.send(**kwargs)
            else:
                await interaction.response.send_message(**kwargs)
        elif channel is not None:
            await channel.send(**kwargs)
        return True
    except Exception:
        log.exception('embed fallback failed')
        return False


async def reply_terminal(
    dest: Any,
    *,
    title: str,
    extra: str = '',
    kind: str = 'generic',
    name: str = '',
    delta: str = '',
    scores: str = '',
    reason: str = '',
    actor: str = '',
    mention: str = '',
    ephemeral: bool = True,
    png: bytes | None = None,
    filename: str | None = None,
    mention_ids: list[str] | None = None,
) -> bool:
    md = score_markdown(
        title=title,
        name=name,
        delta=delta,
        scores=scores,
        reason=reason,
        actor=actor,
        mention=mention,
        extra=extra,
    )
    blob = png if png is not None else banner_bytes(kind)
    fname = filename or f'legion_{kind}.png'
    ids = mention_ids
    if ids is None and mention:
        ids = [mention]
    return await send_terminal(
        dest,
        markdown=md,
        png=blob,
        filename=fname,
        ephemeral=ephemeral,
        mention_ids=ids,
    )
