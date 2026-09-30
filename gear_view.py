# -*- coding: utf-8 -*-
"""Discord UI components for /gear — operator select (ready first)."""
from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from typing import Any

import discord

from gear_card import render_gear_person_png, slot_line

log = logging.getLogger('legion.gear_view')

PAGE_SIZE = 25  # Discord select max


def _flatten_roster(data: dict) -> list[dict]:
    """Ready first, then pending."""
    ready = list(data.get('ready') or [])
    pending = list(data.get('pending') or [])
    out: list[dict] = []
    for r in ready:
        row = dict(r)
        row['_ready'] = True
        out.append(row)
    for r in pending:
        row = dict(r)
        row['_ready'] = False
        out.append(row)
    return out


def _option_label(row: dict) -> str:
    mark = '✅' if row.get('_ready') else '⏳'
    cs = str(row.get('callsign') or '—')[:60]
    return f'{mark} {cs}'


def _option_desc(row: dict) -> str:
    plat = str(row.get('platoon') or '—')[:40]
    if row.get('_ready'):
        summary = str(row.get('summary') or slot_line(row.get('slots') or {}))[:50]
        return f'{plat} · {summary}'[:100]
    return f'{plat} · нет комплекта'[:100]


class GearOperatorSelect(discord.ui.Select):
    def __init__(self, view: 'GearRosterView', page: int):
        self.gear_view = view
        rows = view.page_rows(page)
        options: list[discord.SelectOption] = []
        for i, row in enumerate(rows):
            login = str(row.get('login') or '')
            value = login if login else f'cs:{row.get("callsign") or i}'
            options.append(discord.SelectOption(
                label=_option_label(row)[:100],
                value=value[:100],
                description=_option_desc(row),
            ))
        if not options:
            options = [discord.SelectOption(label='— список пуст —', value='__empty__')]
        super().__init__(
            placeholder='◈ Выберите оперативника (готовые сверху)…',
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f'leggear:sel:{page}',
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        await self.gear_view.on_pick(interaction, self.values[0])


class GearPageButton(discord.ui.Button):
    def __init__(self, view: 'GearRosterView', page: int, *, label: str, disabled: bool = False):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            custom_id=f'leggear:page:{page}',
            disabled=disabled,
            row=1,
        )
        self.gear_view = view
        self.page = page

    async def callback(self, interaction: discord.Interaction):
        self.gear_view.page = self.page
        self.gear_view.rebuild()
        await interaction.response.edit_message(view=self.gear_view)


class GearToggleListButton(discord.ui.Button):
    def __init__(self, view: 'GearRosterView'):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label='◈ СПИСОК ОПЕРАТИВНИКОВ',
            custom_id='leggear:toggle',
            row=1,
        )
        self.gear_view = view

    async def callback(self, interaction: discord.Interaction):
        self.gear_view.expanded = not self.gear_view.expanded
        self.gear_view.rebuild()
        await interaction.response.edit_message(view=self.gear_view)


class GearDiscordUserSelect(discord.ui.UserSelect):
    def __init__(self, view: 'GearRosterView'):
        super().__init__(
            placeholder='Или участник Discord-сервера…',
            min_values=1,
            max_values=1,
            custom_id='leggear:user',
            row=2,
        )
        self.gear_view = view

    async def callback(self, interaction: discord.Interaction):
        users = self.values
        if not users:
            await interaction.response.send_message('Никто не выбран.', ephemeral=True)
            return
        member = users[0]
        await self.gear_view.on_discord_user(interaction, member)


class GearRosterView(discord.ui.View):
    """Under /gear board: expand list → select operator (ready first)."""

    def __init__(
        self,
        *,
        bot: Any,
        api: Any,
        roster: dict,
        timeout: float | None = 600,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.api = api
        self.roster = roster or {}
        self.flat = _flatten_roster(self.roster)
        self.page = 0
        self.expanded = False
        self.rebuild()

    def page_count(self) -> int:
        n = len(self.flat)
        return max(1, (n + PAGE_SIZE - 1) // PAGE_SIZE) if n else 1

    def page_rows(self, page: int) -> list[dict]:
        start = page * PAGE_SIZE
        return self.flat[start:start + PAGE_SIZE]

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(GearToggleListButton(self))
        if self.expanded:
            self.add_item(GearOperatorSelect(self, self.page))
            pages = self.page_count()
            if pages > 1:
                prev_p = max(0, self.page - 1)
                next_p = min(pages - 1, self.page + 1)
                self.add_item(GearPageButton(
                    self, prev_p,
                    label=f'◀ {self.page}/{pages}',
                    disabled=self.page <= 0,
                ))
                self.add_item(GearPageButton(
                    self, next_p,
                    label=f'{self.page + 1}/{pages} ▶',
                    disabled=self.page >= pages - 1,
                ))
            self.add_item(GearDiscordUserSelect(self))

    async def _api_call(self, fn, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(**kwargs))

    async def _send_person(self, interaction: discord.Interaction, user: dict, mention: str = '') -> None:
        try:
            png = await asyncio.get_event_loop().run_in_executor(
                None, lambda: render_gear_person_png(user)
            )
        except Exception:
            log.exception('gear person render failed')
            msg = 'Не удалось собрать карточку снаряжения'
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        name = user.get('callsign') or '—'
        summary = user.get('summary') or slot_line(user.get('slots') or {})
        status = 'READY' if user.get('ready') else 'NOT READY'
        content = f'◈ **{name}** · {status}'
        if mention:
            content = f'{mention}\n{content}'
        content += f'\n`{summary}`'
        file = discord.File(BytesIO(png), filename='legion_gear.png')
        if interaction.response.is_done():
            await interaction.followup.send(content=content, file=file)
        else:
            await interaction.response.send_message(content=content, file=file)

    async def on_pick(self, interaction: discord.Interaction, value: str) -> None:
        await interaction.response.defer(ephemeral=False)
        if value == '__empty__':
            await interaction.followup.send('Список пуст.', ephemeral=True)
            return
        login = ''
        callsign = ''
        if value.startswith('cs:'):
            callsign = value[3:]
        else:
            login = value
            # resolve callsign from flat for nicer API
            for r in self.flat:
                if str(r.get('login') or '') == login:
                    callsign = str(r.get('callsign') or '')
                    break
        out = await self._api_call(self.api.gear_one, login=login, callsign=callsign)
        if not out.get('ok'):
            await interaction.followup.send(
                str(out.get('error') or 'Снаряжение не найдено'),
                ephemeral=True,
            )
            return
        await self._send_person(interaction, out.get('user') or {})

    async def on_discord_user(self, interaction: discord.Interaction, member: discord.abc.User) -> None:
        await interaction.response.defer(ephemeral=False)
        card = await self._api_call(self.api.balls_card, discord_id=str(member.id))
        callsign = ''
        login = ''
        if card.get('ok'):
            u = card.get('user') or {}
            callsign = str(u.get('name') or u.get('callsign') or '')
            login = str(u.get('login') or '')
        out = await self._api_call(self.api.gear_one, login=login, callsign=callsign)
        if not out.get('ok'):
            await interaction.followup.send(
                f'{member.mention} не найден в «Моё снаряжение» (нужен `/login` и комплект на сайте).',
                ephemeral=True,
            )
            return
        await self._send_person(interaction, out.get('user') or {}, mention=member.mention)


def make_gear_roster_view(bot: Any, api: Any, roster: dict) -> GearRosterView:
    return GearRosterView(bot=bot, api=api, roster=roster)
