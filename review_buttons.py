# -*- coding: utf-8 -*-
"""Buttons under imported Discord reports: approve / reject / balls."""
from __future__ import annotations

import logging

import discord

from legion_api import LegionApi
from terminal_msg import reply_terminal

log = logging.getLogger('legion.review_buttons')

TYPE_RU = {
    'storm': 'штурм',
    'captive': 'плен',
    'leave': 'отпуск',
    'access': 'доступ',
}


def make_review_view(message_id: str) -> discord.ui.View:
    mid = ''.join(ch for ch in str(message_id) if ch.isdigit())
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.success,
        label='Принять',
        custom_id=f'lgrev:ok:{mid}',
    ))
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.danger,
        label='Отклонить',
        custom_id=f'lgrev:no:{mid}',
    ))
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.secondary,
        label='Баллы',
        custom_id=f'lgrev:pts:{mid}',
    ))
    return view


def parse_review_custom_id(custom_id: str) -> tuple[str, str] | None:
    raw = str(custom_id or '')
    if not raw.startswith('lgrev:'):
        return None
    parts = raw.split(':')
    if len(parts) < 3:
        return None
    op = parts[1]
    mid = ''.join(ch for ch in parts[2] if ch.isdigit())
    if op not in ('ok', 'no', 'pts') or not mid:
        return None
    return op, mid


class BallsAmountModal(discord.ui.Modal, title='Начислить баллы'):
    amount = discord.ui.TextInput(
        label='Сколько',
        placeholder='0.34 или 1',
        default='1',
        max_length=12,
        required=True,
    )
    reason = discord.ui.TextInput(
        label='Причина',
        placeholder='за штурм / снятие за ...',
        max_length=200,
        required=True,
        style=discord.TextStyle.short,
    )

    def __init__(self, api: LegionApi, message_id: str):
        super().__init__()
        self.api = api
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.amount.value or '1').strip().replace('+', '')
        try:
            amt = float(str(raw).replace(',', '.'))
            amt = round(amt, 4)
        except ValueError:
            await interaction.response.send_message('Нужно число, например 1 или 0.34.', ephemeral=True)
            return
        if abs(amt) < 0.00005:
            await interaction.response.send_message('Укажите ненулевое число.', ephemeral=True)
            return
        note = str(self.reason.value or '').strip()
        if not note:
            await interaction.response.send_message('Укажите причину.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        out = await _call_review(self.api, interaction, self.message_id, 'balls', amt, note)
        await _reply_review(interaction, out, edit_bar=False)


def _api_call(fn, *args, **kwargs):
    import asyncio
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def _call_review(
    api: LegionApi,
    interaction: discord.Interaction,
    message_id: str,
    op: str,
    amount: float | None = None,
    note: str = '',
) -> dict:
    return await _api_call(
        api.review_report,
        actor_discord_id=str(interaction.user.id),
        message_id=message_id,
        op=op,
        amount=amount,
        silent=True,
        note=note,
    )


def _bar_text(out: dict) -> str:
    author = out.get('author') or 'оперативник'
    who = out.get('reviewedBy') or '—'
    typ = TYPE_RU.get(str(out.get('type') or ''), str(out.get('type') or 'отчёт'))
    if out.get('op') == 'balls' and out.get('ok'):
        delta = out.get('delta') or 0
        balls = (out.get('balls') or {}).get('balls')
        extra = f' · итого {balls}' if balls is not None else ''
        note = out.get('note') or ''
        line = f'◈ БАЛЛЫ · {author} · {delta:+d}{extra}\nначислил: {who}'
        if note:
            line += f'\nпричина: {note}'
        return line
    status = out.get('status')
    note = out.get('extraNote') or ''
    if status == 'approved':
        line = f'◈ ПРИНЯТ · {typ}\nотчёт: {author}\nпринял: {who}'
    else:
        line = f'◈ ОТКЛОНЁН · {typ}\nотчёт: {author}\nотклонил: {who}'
    if note:
        line += f'\n{note}'
    return line


async def _strip_bar(interaction: discord.Interaction, text: str) -> None:
    msg = interaction.message
    if msg is None:
        return
    try:
        await msg.edit(content=text, view=None)
        return
    except Exception:
        log.exception('failed to clear review buttons')
    try:
        empty = discord.ui.View()
        await msg.edit(content=text, view=empty)
    except Exception:
        log.exception('failed to edit review bar fallback')


async def _reply_review(interaction: discord.Interaction, out: dict, *, edit_bar: bool) -> None:
    already = bool(out.get('already') or out.get('httpCode') == 409)
    if not out.get('ok') and not already:
        err = str(out.get('error') or 'ошибка')
        if out.get('httpCode') == 403:
            err = 'Нет прав на разбор (нужны /login и ЯДРО / КМД / ОФЦ / ХМР).'
        await reply_terminal(interaction, title='ОШИБКА РАЗБОРА', extra=err, kind='review_no', ephemeral=True)
        return
    text = _bar_text(out) if (out.get('ok') or already) else str(out.get('error') or 'ошибка')
    if edit_bar or already:
        await _strip_bar(interaction, text)
    if already:
        await reply_terminal(
            interaction,
            title='УЖЕ РАЗОБРАН',
            extra=str(out.get('error') or 'Уже разобран.'),
            kind='generic',
            ephemeral=True,
        )
        return
    if not out.get('ok'):
        await reply_terminal(interaction, title='ОШИБКА РАЗБОРА', extra=str(out.get('error') or 'ошибка'), kind='review_no', ephemeral=True)
        return
    await reply_terminal(interaction, title='ЗАПИСАНО', extra=text, kind='review_ok', ephemeral=True)


async def handle_review_click(api: LegionApi, interaction: discord.Interaction, custom_id: str) -> bool:
    parsed = parse_review_custom_id(custom_id)
    if not parsed:
        return False
    op, mid = parsed
    if op == 'pts':
        await interaction.response.send_modal(BallsAmountModal(api, mid))
        return True
    await interaction.response.defer(ephemeral=True)
    out = await _call_review(api, interaction, mid, op)
    await _reply_review(interaction, out, edit_bar=True)
    return True


async def post_review_bars(message: discord.Message, imported: list) -> None:
    if not imported or not isinstance(imported, list):
        return
    mid = str(message.id)
    chan = str(message.channel.id)
    parent = getattr(message.channel, 'parent_id', None)
    seen = set()
    for item in imported:
        if not isinstance(item, dict):
            continue
        item_mid = str(item.get('discordMessageId') or '')
        item_tid = str(item.get('discordThreadId') or '')
        item_ch = str(item.get('channelId') or '')
        hit = item_mid == mid or item_tid == mid or item_tid == chan or item_ch == chan
        if parent is not None and str(parent) == item_ch and (item_tid == chan or item_mid == mid):
            hit = True
        if not hit:
            continue
        bar_id = item_mid or mid
        if bar_id in seen:
            continue
        seen.add(bar_id)
        typ = TYPE_RU.get(str(item.get('type') or ''), 'отчёт')
        try:
            await message.reply(
                content=f'◈ РАЗБОР · {typ} · терминал LEGION',
                view=make_review_view(bar_id),
                mention_author=False,
            )
        except Exception:
            log.exception('failed to post review bar for %s', bar_id)
