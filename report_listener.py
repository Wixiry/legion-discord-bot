"""Optional discord.py gateway: report import + balls slash commands."""
from __future__ import annotations

import asyncio
import logging
import os
from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dossier_card import render_dossier_png, render_platoon_png
from gear_card import render_gear_board_png, render_gear_person_png
from gear_view import make_gear_roster_view
from legion_api import LegionApi
from review_buttons import handle_review_click, post_review_bars
from terminal_msg import banner_bytes, reply_terminal, score_markdown, send_terminal

log = logging.getLogger('legion.report_listener')

CRT_RED = 0xC81010
CRT_DIM = 0x6E0A0A

PLATOON_CHOICES = [
    app_commands.Choice(name='Штурмовой', value='ШТУРМОВОЙ'),
    app_commands.Choice(name='Офицерский', value='ОФИЦЕРСКИЙ'),
    app_commands.Choice(name='Мостовой', value='МОСТОВОЙ'),
    app_commands.Choice(name='Командный', value='КОМАНДНЫЙ'),
    app_commands.Choice(name='Ядро', value='ЯДРО'),
    app_commands.Choice(name='ХМР', value='ХМР'),
]

WHOLEGION_CHOICES = [
    app_commands.Choice(name='Штурмовой', value='ШТУРМОВОЙ'),
    app_commands.Choice(name='Офицерский', value='ОФИЦЕРСКИЙ'),
    app_commands.Choice(name='Мостовой', value='МОСТОВОЙ'),
    app_commands.Choice(name='Командный', value='КОМАНДНЫЙ'),
    app_commands.Choice(name='Ядро', value='ЯДРО'),
]

WARN_ROLE_IDS = {
    '1486365790750900394': 'EL1',
    '1473396475491782927': 'EL2',
    '1473396551844892722': 'EL3',
    '1473396670027792507': 'EL4',
}
RANK_GROUP_CHOICES = [
    app_commands.Choice(name='Младший состав', value='Младший состав'),
    app_commands.Choice(name='Старший состав', value='Старший состав'),
    app_commands.Choice(name='Офицерский состав', value='Офицерский состав'),
    app_commands.Choice(name='Командный взвод', value='Командный взвод'),
    app_commands.Choice(name='Прочее', value='Прочее'),
]
RANK_FALLBACK = [
    ('N.D — Штрафник', 'N.D'),
    ('XI — Рядовой', 'XI'),
    ('X — Капрал', 'X'),
    ('IX — Сержант', 'IX'),
    ('VIII — Старшина', 'VIII'),
    ('VII — Прапорщик', 'VII'),
    ('VI — Ст. Прапорщик', 'VI'),
    ('V — Мл. лейтенант', 'V'),
    ('IV — Лейтенант', 'IV'),
    ('III — Капитан', 'III'),
    ('II — Зам. Майор', 'II'),
    ('I — Майор', 'I'),
    ('III.X — Подполковник', 'III.X'),
    ('II.X — Полковник', 'II.X'),
    ('I.X — Полковник', 'I.X'),
]


def load_channel_map() -> dict[str, str]:
    raw = os.environ.get('DISCORD_REPORT_CHANNELS', '')
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(','):
        part = part.strip()
        if ':' not in part:
            continue
        cid, typ = part.split(':', 1)
        cid = ''.join(ch for ch in cid if ch.isdigit())
        if cid:
            out[cid] = typ.strip().lower() or 'storm'
    return out


async def _term_fail(interaction: discord.Interaction, text: str) -> None:
    ok = await reply_terminal(
        interaction,
        title='ОШИБКА ТЕРМИНАЛА',
        extra=str(text or 'сбой'),
        kind='review_no',
        ephemeral=True,
    )
    if not ok:
        await interaction.followup.send(str(text or 'сбой'), ephemeral=True)


async def _term_ok(interaction: discord.Interaction, *, title: str, extra: str = '', kind: str = 'generic', **kwargs) -> None:
    ok = await reply_terminal(
        interaction,
        title=title,
        extra=extra,
        kind=kind,
        ephemeral=True,
        **kwargs,
    )
    if not ok:
        await interaction.followup.send(extra or title, ephemeral=True)


def week_markdown(data: dict) -> str:
    period = data.get('period') or {}
    pfrom = _fmt_day(period.get('from') or '')
    pto = _fmt_day(period.get('to') or '')
    norm = int(data.get('normAt') or 2)
    platoons = data.get('platoons') or []
    total_ok = sum(int(p.get('done') or 0) for p in platoons)
    total_n = sum(int(p.get('total') or 0) for p in platoons)
    lines = [
        '## LEGION',
        '**СВОДКА НЕДЕЛИ**',
        f'Период **{pfrom} – {pto}** · норма **{norm}** · сдали **{total_ok}** / {total_n}',
    ]
    for plat in platoons[:8]:
        people = plat.get('people') or []
        lines.append('')
        lines.append(
            f"### {plat.get('name') or '—'}  ·  {plat.get('done') or 0}/{plat.get('total') or 0}"
        )
        low = [p for p in people if not p.get('ok')]
        okp = [p for p in people if p.get('ok')]
        if okp:
            lines.append('**Сдали:** ' + ', '.join(
                f"{x.get('name') or x.get('login')} ({x.get('reports') or 0})"
                for x in okp[:20]
            ))
        if low:
            lines.append('**Не сдали:** ' + ', '.join(
                f"{x.get('name') or x.get('login')} ({x.get('reports') or 0})"
                for x in low[:20]
            ))
        if not people:
            lines.append('—')
    lines += ['', '-# LEGION · сводка только вам']
    return '\n'.join(lines)[:3900]


def _need_login(out: dict) -> bool:
    return bool(out.get('needLogin') or out.get('httpCode') == 404)


def _fmt_day(s: str) -> str:
    s = str(s or '')
    if len(s) >= 10 and s[4] == '-':
        return s[8:10] + '.' + s[5:7]
    return s


def build_me_embed(card: dict) -> discord.Embed:
    user = card.get('user') or {}
    name = user.get('name') or user.get('login') or '—'
    rank = user.get('rank') or '—'
    platoon = user.get('platoon') or '—'
    balls = int(card.get('balls') or 0)
    rep = int(card.get('reputation') or (card.get('user') or {}).get('reputation') or 0)
    total = int(card.get('total') or (balls + rep))
    reports = int(card.get('reports') or 0)
    norm = int(card.get('normAt') or 2)
    promo = int(card.get('promoteFrom') or 6)
    pay_from = int(card.get('payFrom') or 4)
    min_hours = int(card.get('minReportHours') or 1)
    st = card.get('status') or {}
    label = st.get('label') or '—'
    need_n = int(card.get('needForNorm') or 0)
    need_u = int(card.get('needForPromote') or 0)
    period = card.get('period') or {}
    pfrom = _fmt_day(period.get('from') or '')
    pto = _fmt_day(period.get('to') or '')
    weeks = period.get('weeks') or 2

    bar_n = min(promo, max(0, reports))
    bar = ''.join('●' if i < bar_n else '○' for i in range(promo))
    sub = (str(rank) + ' · ' + str(platoon))[:28]
    lines = [
        '┌─ LEGION // DOSSIER ────────────┐',
        '│  ' + str(name)[:28].ljust(28) + ' │',
        '│  ' + sub.ljust(28) + ' │',
        '│                                │',
        '│  БАЛЛЫ / РЕП    ' + (str(balls) + ' / ' + str(rep)).ljust(14) + '│',
        '│  ИТОГО          ' + str(total).ljust(14) + '│',
        '│  ОТЧЁТЫ         ' + (str(reports) + '/' + str(norm)).ljust(14) + '│',
        '│  ШКАЛА          ' + bar[:14].ljust(14) + '│',
        '│  СТАТУС         ' + str(label)[:14].ljust(14) + '│',
        '│  ДО НОРМЫ       ' + str(need_n).ljust(14) + '│',
        '│  ДО ПОВЫШЕНИЯ   ' + str(need_u).ljust(14) + '│',
        '│  ПЕРИОД         ' + (pfrom + '–' + pto).ljust(14) + '│',
        '└────────────────────────────────┘',
    ]

    embed = discord.Embed(
        title=f'◈ {name}',
        description='```\n' + '\n'.join(lines) + '\n```',
        color=CRT_RED,
    )
    embed.add_field(name='Звание', value=str(rank), inline=True)
    embed.add_field(name='Взвод', value=str(platoon), inline=True)
    embed.add_field(name='Баллы', value=f'**{balls}**', inline=True)
    embed.add_field(name='Репутация', value=f'**{rep}**', inline=True)
    embed.add_field(name='Итого', value=f'**{total}**', inline=True)
    embed.add_field(name=f'Отчёты / {weeks} нед', value=f'**{reports}**  из нормы {norm}', inline=True)
    embed.add_field(name='Статус', value=f'**{label}**', inline=True)
    if need_u:
        embed.add_field(name='До повышения', value=f'ещё **{need_u}**', inline=True)
    else:
        embed.add_field(name='До повышения', value='норма набрана', inline=True)
    embed.set_footer(
        text=f'ОТЧЁТЫ: мин {min_hours}ч · норма {norm} (+1) · деньги с {pay_from} · VII+ с {promo} (+1) · КОНТРАКТЫ = репутация'
    )
    return embed


def build_week_embeds(data: dict) -> list[discord.Embed]:
    period = data.get('period') or {}
    pfrom = _fmt_day(period.get('from') or '')
    pto = _fmt_day(period.get('to') or '')
    norm = int(data.get('normAt') or 2)
    embeds: list[discord.Embed] = []
    platoons = data.get('platoons') or []
    if not platoons:
        emb = discord.Embed(title='◈ СВОДКА НЕДЕЛИ', description='Нет состава.', color=CRT_DIM)
        return [emb]
    head = discord.Embed(
        title='◈ СВОДКА НЕДЕЛИ',
        description=f'Период **{pfrom} – {pto}** · норма **{norm}** отчёта',
        color=CRT_RED,
    )
    total_ok = sum(int(p.get('done') or 0) for p in platoons)
    total_n = sum(int(p.get('total') or 0) for p in platoons)
    head.add_field(name='Сдало норму', value=f'**{total_ok}** / {total_n}', inline=True)
    embeds.append(head)
    for plat in platoons:
        people = plat.get('people') or []
        ok_lines = []
        low_lines = []
        for person in people:
            mark = '✓' if person.get('ok') else '✗'
            bit = f"{mark} {person.get('name') or person.get('login')} · {person.get('reports') or 0}"
            if person.get('ok'):
                ok_lines.append(bit)
            else:
                low_lines.append(bit)
        body = ''
        if ok_lines:
            body += '**Сдали**\n' + '\n'.join(ok_lines[:25])
        if low_lines:
            if body:
                body += '\n\n'
            body += '**Не сдали**\n' + '\n'.join(low_lines[:25])
        if not body:
            body = '—'
        if len(body) > 1000:
            body = body[:997] + '…'
        emb = discord.Embed(
            title=f"{plat.get('name') or '—'}  ·  {plat.get('done') or 0}/{plat.get('total') or 0}",
            description=body,
            color=CRT_RED if (plat.get('done') or 0) else CRT_DIM,
        )
        embeds.append(emb)
        if len(embeds) >= 8:
            break
    return embeds


class LegionBot(commands.Bot):
    def __init__(self, api: LegionApi, channel_ids: set[str], guild_id: int | None = None):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix='!', intents=intents)
        self.api = api
        self.channel_ids = channel_ids
        self.guild_id = guild_id

    @tasks.loop(minutes=2)
    async def expire_warns_loop(self):
        try:
            await _api_call(self, self.api.balls_warn_expire)
        except Exception:
            log.exception('warn expire failed')

    async def setup_hook(self) -> None:
        if self.guild_id:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        log.info('Slash commands synced: %s', len(synced))
        if not self.expire_warns_loop.is_running():
            self.expire_warns_loop.start()

    async def on_ready(self):
        log.info('Gateway ready as %s, watching %d channels', self.user, len(self.channel_ids))

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            before_ids = {str(r.id) for r in before.roles}
            after_ids = {str(r.id) for r in after.roles}
            for rid in WARN_ROLE_IDS:
                added = rid in after_ids and rid not in before_ids
                removed = rid in before_ids and rid not in after_ids
                if not added and not removed:
                    continue
                await _api_call(
                    self,
                    self.api.balls_warn_sync_role,
                    actor_discord_id=str(after.id),
                    target_discord_id=str(after.id),
                    role_id=rid,
                    added=added,
                )
        except Exception:
            log.exception('warn role sync failed')

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        try:
            if message.is_system():
                return
        except Exception:
            pass
        cid = str(message.channel.id)
        parent = getattr(message.channel, 'parent_id', None)
        watch = cid in self.channel_ids or (parent is not None and str(parent) in self.channel_ids)
        if not watch:
            return
        log.info('New message %s in channel %s — triggering import', message.id, cid)
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(
            None,
            lambda: self.api.import_reports(message_id=str(message.id), channel_id=cid, max_messages=3),
        )
        try:
            await post_review_bars(message, (out or {}).get('imported') or [])
        except Exception:
            log.exception('review bar failed')


def _api_call(bot: LegionBot, fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


async def _avatar_bytes(user: discord.abc.User) -> bytes | None:
    try:
        asset = user.display_avatar
        try:
            return await asset.replace(size=512, format='png').read()
        except Exception:
            return await asset.with_size(512).read()
    except Exception:
        log.exception('avatar fetch failed')
        return None


async def _send_dossier(interaction: discord.Interaction, out: dict, user: discord.abc.User, caption: str) -> None:
    avatar = await _avatar_bytes(user)
    loop = asyncio.get_running_loop()
    try:
        png = await loop.run_in_executor(
            None,
            lambda: render_dossier_png(
                out,
                avatar_bytes=avatar,
                discord_name=getattr(user, 'display_name', '') or '',
            ),
        )
    except Exception:
        log.exception('dossier render failed')
        await interaction.followup.send(embed=build_me_embed(out), ephemeral=True)
        return
    name = ((out.get('user') or {}).get('name') or getattr(user, 'display_name', 'оперативник'))
    balls = int(out.get('balls') or 0)
    rep = int(out.get('reputation') or (out.get('user') or {}).get('reputation') or 0)
    md = score_markdown(
        title='ДОСЬЕ ТЕРМИНАЛА',
        name=str(name),
        scores=f'{balls} б. · {rep} реп.',
        extra=caption or 'Карточка терминала LEGION.',
        mention=str(getattr(user, 'id', '') or ''),
    )
    public = bool(interaction.guild and interaction.channel)
    dest = interaction.channel if public else interaction
    ok = await send_terminal(
        dest,
        markdown=md,
        png=png,
        filename='legion_dossier.png',
        ephemeral=not public,
        mention_ids=[str(user.id)] if getattr(user, 'id', None) else None,
    )
    if not ok:
        await interaction.followup.send(
            content=caption or f'◈ **{name}** · досье',
            file=discord.File(BytesIO(png), filename='legion_dossier.png'),
            ephemeral=True,
        )
        return
    if public:
        try:
            await interaction.followup.send('◈ карточка в канале', ephemeral=True)
        except Exception:
            pass


def register_slash(bot: LegionBot) -> None:
    @bot.tree.command(name='login', description='Привязать Discord кодом с сайта (Профиль → код, не пароль)')
    @app_commands.describe(code='6-значный код из профиля на сайте (2 минуты)')
    async def login_cmd(interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        digits = ''.join(ch for ch in str(code) if ch.isdigit())
        if len(digits) != 6:
            await _term_fail(interaction, 'Нужен код из 6 цифр с сайта, пароль не подходит.')
            return
        out = await _api_call(
            bot,
            bot.api.balls_login,
            code=digits,
            discord_id=str(interaction.user.id),
        )
        if not out.get('ok'):
            await _term_fail(interaction, 'Не удалось привязать: ' + str(out.get('error') or 'ошибка'))
            return
        user = out.get('user') or {}
        name = user.get('name') or user.get('login') or 'профиль'
        balls = out.get('balls', user.get('balls', 0))
        moved = out.get('reportsMoved') or 0
        extra = f'Отчёты подтянуты: {moved}' if moved else 'Привязка Discord к терминалу завершена.'
        await _term_ok(
            interaction,
            title='ПРИВЯЗКА ОК',
            name=str(name),
            scores=f'{balls} б.',
            extra=extra,
            kind='review_ok',
        )

    @bot.tree.command(name='balls', description='Коротко: сколько баллов (нужен /login)')
    async def balls_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        out = await _api_call(bot, bot.api.balls_me, discord_id=str(interaction.user.id))
        if _need_login(out):
            await _term_fail(interaction, 'Сначала код в Профиле на сайте, затем /login')
            return
        if not out.get('ok'):
            await _term_fail(interaction, 'Ошибка: ' + str(out.get('error') or 'неизвестно'))
            return
        user = out.get('user') or {}
        name = user.get('name') or user.get('login') or interaction.user.display_name
        balls = int(out.get('balls') or 0)
        rep = int(out.get('reputation') or 0)
        await _term_ok(
            interaction,
            title='БАЛЛЫ НА САЙТЕ',
            name=str(name),
            scores=f'{balls} б. · {rep} реп. · итого {int(out.get("total") or (balls + rep))}',
            extra='Карточка только вам.',
            kind='generic',
        )

    @bot.tree.command(name='me', description='Досье: карточка терминала LEGION')
    async def me_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        out = await _api_call(bot, bot.api.balls_card, discord_id=str(interaction.user.id))
        if _need_login(out):
            await _term_fail(interaction, 'Сначала код в Профиле на сайте, затем /login')
            return
        if not out.get('ok'):
            await _term_fail(interaction, 'Ошибка: ' + str(out.get('error') or 'неизвестно'))
            return
        name = ((out.get('user') or {}).get('name') or interaction.user.display_name)
        await _send_dossier(interaction, out, interaction.user, f'◈ **{name}** · досье')

    @bot.tree.command(name='who', description='Досье игрока: карточка терминала LEGION')
    @app_commands.describe(player='Кого показать')
    async def who_cmd(interaction: discord.Interaction, player: discord.Member):
        await interaction.response.defer(ephemeral=True)
        out = await _api_call(bot, bot.api.balls_card, discord_id=str(player.id))
        if _need_login(out):
            await _term_fail(interaction, f'{player.mention} не привязан к терминалу. Нужен `/login` с кодом из Профиля.')
            return
        if not out.get('ok'):
            await _term_fail(interaction, 'Ошибка: ' + str(out.get('error') or 'неизвестно'))
            return
        name = ((out.get('user') or {}).get('name') or player.display_name)
        await _send_dossier(interaction, out, player, f'◈ **{name}** · досье')

    @bot.tree.command(name='gear', description='Готовность снаряжения: карточка loadout + список оперативников')
    @app_commands.describe(player='Опционально: карточка конкретного бойца')
    async def gear_cmd(interaction: discord.Interaction, player: discord.Member | None = None):
        await interaction.response.defer(ephemeral=False)
        if player is not None:
            card = await _api_call(bot, bot.api.balls_card, discord_id=str(player.id))
            callsign = ''
            login = ''
            if card.get('ok'):
                u = card.get('user') or {}
                callsign = str(u.get('name') or u.get('callsign') or '')
                login = str(u.get('login') or '')
            out = await _api_call(bot, bot.api.gear_one, login=login, callsign=callsign)
            if not out.get('ok'):
                await _term_fail(interaction, str(out.get('error') or 'Снаряжение не найдено'))
                return
            user = out.get('user') or {}
            try:
                png = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: render_gear_person_png(user)
                )
            except Exception:
                log.exception('gear person render failed')
                await _term_fail(interaction, 'Не удалось собрать карточку снаряжения')
                return
            name = user.get('callsign') or player.display_name
            summary = user.get('summary') or '—'
            status = 'READY' if user.get('ready') else 'NOT READY'
            await interaction.followup.send(
                content=f'◈ **{name}** · {status}\n`{summary}`',
                file=discord.File(BytesIO(png), filename='legion_gear.png'),
            )
            return

        out = await _api_call(bot, bot.api.gear_roster)
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не удалось загрузить готовность'))
            return
        try:
            png = await asyncio.get_event_loop().run_in_executor(
                None, lambda: render_gear_board_png(out)
            )
        except Exception:
            log.exception('gear board render failed')
            await _term_fail(interaction, 'Не удалось собрать доску готовности')
            return
        ready_n = int(out.get('readyCount') or len(out.get('ready') or []))
        total = int(out.get('total') or 0)
        view = make_gear_roster_view(bot, bot.api, out)
        await interaction.followup.send(
            content=(
                f'◈ **LOADOUT READY** · {ready_n}/{total} готовы\n'
                f'Нажмите **◈ СПИСОК ОПЕРАТИВНИКОВ** — готовые сверху, выберите кого проверить.'
            ),
            file=discord.File(BytesIO(png), filename='legion_gear_board.png'),
            view=view,
        )

    @bot.tree.command(name='wholegion', description='Баннер взвода: командир, состав, норма')
    @app_commands.describe(platoon='Взвод')
    @app_commands.choices(platoon=WHOLEGION_CHOICES)
    async def wholegion_cmd(interaction: discord.Interaction, platoon: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        if str(platoon.value).upper() in ('ХМР', 'HMR', 'ХИМЕРА'):
            await _term_fail(interaction, 'Взвод недоступен.')
            return
        out = await _api_call(bot, bot.api.balls_platoon, platoon=platoon.value)
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не удалось собрать взвод'))
            return
        avatars: dict[str, bytes] = {}
        for person in (out.get('command') or [])[:4]:
            did = str(person.get('discordId') or '')
            if not did.isdigit() or did in avatars:
                continue
            user_obj = bot.get_user(int(did))
            if user_obj is None:
                try:
                    user_obj = await bot.fetch_user(int(did))
                except Exception:
                    user_obj = None
            if user_obj is None:
                continue
            blob = await _avatar_bytes(user_obj)
            if blob:
                avatars[did] = blob
        loop = asyncio.get_running_loop()
        plat = out.get('platoon') or platoon.value
        cmd = next((p for p in (out.get('command') or []) if p.get('kind') == 'cmd'), None)
        extra = (
            f"{out.get('count') or 0} чел. · норма {out.get('done') or 0}/{out.get('count') or 0}"
            + (f" · КМД: {cmd.get('name')}" if cmd else '')
        )
        try:
            png = await loop.run_in_executor(
                None,
                lambda: render_platoon_png(out, avatars=avatars),
            )
        except Exception:
            log.exception('platoon banner render failed')
            people = out.get('people') or []
            bits = [extra]
            for p in people[:20]:
                bits.append(f"· {p.get('name')} · {p.get('rank')} · {p.get('reports')}/{out.get('normAt')}")
            await _term_ok(interaction, title=str(plat), extra='\n'.join(bits), kind='generic')
            return
        public = bool(interaction.guild and interaction.channel)
        dest = interaction.channel if public else interaction
        md = score_markdown(title='ВЗВОД ТЕРМИНАЛА', name=str(plat), extra=extra)
        ok = await send_terminal(
            dest,
            markdown=md,
            png=png,
            filename='legion_platoon.png',
            ephemeral=not public,
        )
        if not ok:
            await interaction.followup.send(
                content=f'◈ **{plat}** · {out.get("count") or 0} чел.',
                file=discord.File(BytesIO(png), filename='legion_platoon.png'),
                ephemeral=True,
            )
            return
        if public:
            try:
                await interaction.followup.send('◈ баннер в канале', ephemeral=True)
            except Exception:
                pass

    @bot.tree.command(name='week', description='Сводка отчётов по взводам (ЯДРО / КМД / TERM.S)')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(platoon='Фильтр взвода, пусто = все')
    @app_commands.choices(platoon=[
        app_commands.Choice(name='Штурмовой', value='ШТУРМОВОЙ'),
        app_commands.Choice(name='Офицерский', value='ОФИЦЕРСКИЙ'),
        app_commands.Choice(name='Мостовой', value='МОСТОВОЙ'),
        app_commands.Choice(name='Командный', value='КОМАНДНЫЙ'),
        app_commands.Choice(name='Ядро', value='ЯДРО'),
        app_commands.Choice(name='ХМР', value='ХМР'),
    ])
    async def week_cmd(interaction: discord.Interaction, platoon: app_commands.Choice[str] | None = None):
        await interaction.response.defer(ephemeral=True)
        plat = platoon.value if platoon else ''
        out = await _api_call(
            bot,
            bot.api.balls_week,
            actor_discord_id=str(interaction.user.id),
            platoon=plat,
        )
        if _need_login(out) or out.get('httpCode') == 403:
            await _term_fail(interaction, str(out.get('error') or 'Нужны /login и права КМД / ЯДРО / TERM.S'))
            return
        if not out.get('ok'):
            await _term_fail(interaction, 'Ошибка: ' + str(out.get('error') or 'неизвестно'))
            return
        ok = await send_terminal(
            interaction,
            markdown=week_markdown(out),
            png=banner_bytes('generic'),
            filename='legion_week.png',
            ephemeral=True,
        )
        if not ok:
            embeds = build_week_embeds(out)
            await interaction.followup.send(embeds=embeds[:10], ephemeral=True)

    @bot.tree.command(name='giveballs', description='Выдать баллы (дробные ок, напр. 0.34; ЯДРО / TERM.S / КОМАНДНЫЙ)')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(
        player='Игрок (пинг)',
        amount='Сколько баллов (можно дробное: 0.34, -1.5)',
        reason='Причина выдачи или снятия',
    )
    async def giveballs_cmd(
        interaction: discord.Interaction,
        player: discord.Member,
        amount: float,
        reason: str,
    ):
        await interaction.response.defer(ephemeral=True)
        reason = str(reason or '').strip()
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            await _term_fail(interaction, 'Укажите число баллов (можно дробное, напр. 0.34).')
            return
        amount = round(amount, 4)
        if abs(amount) < 0.00005:
            await _term_fail(interaction, 'Укажите ненулевое число.')
            return
        if not reason:
            await _term_fail(interaction, 'Укажите причину.')
            return
        out = await _api_call(
            bot,
            bot.api.balls_give,
            actor_discord_id=str(interaction.user.id),
            target_discord_id=str(player.id),
            amount=amount,
            note=reason,
        )
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не выдано. Нужны /login и права КМД/ЯДРО.'))
            return
        balls = float(out.get('balls') or 0)
        rep = int(out.get('reputation') or 0)

        def _fmt(n: float) -> str:
            s = f'{float(n):.4f}'.rstrip('0').rstrip('.')
            return s or '0'

        kind = 'deduct' if amount < 0 else 'award'
        md = score_markdown(
            title='СПИСАНИЕ · БАЛЛЫ' if amount < 0 else 'НАЧИСЛЕНИЕ · БАЛЛЫ',
            name=player.display_name,
            delta=f'{_fmt(amount)} б.' if amount < 0 else f'+{_fmt(amount)} б.',
            scores=f'{_fmt(balls)} б. · {rep} реп.',
            reason=reason,
            actor=interaction.user.display_name,
            mention=str(player.id),
        )
        if interaction.channel is not None:
            await send_terminal(
                interaction.channel,
                markdown=md,
                png=None,
                filename='',
                accent=CRT_RED,
                mention_ids=[str(player.id)],
            )
        try:
            await interaction.followup.send('◈ записано. Карточка в канале.', ephemeral=True)
        except Exception:
            pass

    async def _rank_choices(bot: LegionBot, current: str = '', *, custom_only: bool = False) -> list[app_commands.Choice[str]]:
        cur = (current or '').strip().lower()
        rows: list[tuple[str, str]] = []
        try:
            out = await _api_call(bot, bot.api.balls_ranks)
            for r in (out.get('ranks') or []):
                code = str(r.get('code') or '').strip()
                title = str(r.get('title') or code).strip()
                if not code:
                    continue
                if custom_only and not r.get('custom'):
                    continue
                rows.append((f'{code} — {title}', code))
        except Exception:
            rows = []
        if not rows:
            rows = list(RANK_FALLBACK)
        if cur:
            rows = [p for p in rows if cur in p[0].lower() or cur in p[1].lower()]
        return [app_commands.Choice(name=name[:100], value=code) for name, code in rows[:25]]

    @bot.tree.command(name='setrank', description='Сменить звание игроку (звания с сайта; ЯДРО / TERM.S / КОМАНДНЫЙ)')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(
        player='Игрок с привязанным Discord (/login)',
        rank='Звание с сайта (начните вводить для поиска)',
    )
    async def setrank_cmd(
        interaction: discord.Interaction,
        player: discord.Member,
        rank: str,
    ):
        await interaction.response.defer(ephemeral=True)
        rank = str(rank or '').strip()
        if not rank:
            await _term_fail(interaction, 'Укажите звание.')
            return
        # Подтверждаем, что цель привязана — иначе API тоже откажет, но текст понятнее заранее
        card = await _api_call(bot, bot.api.balls_card, discord_id=str(player.id))
        if _need_login(card) or not card.get('ok'):
            await _term_fail(
                interaction,
                f'{player.mention} не привязал Discord. Нужен `/login` с кодом из Профиля на сайте.',
            )
            return
        out = await _api_call(
            bot,
            bot.api.balls_setrank,
            actor_discord_id=str(interaction.user.id),
            target_discord_id=str(player.id),
            rank=rank,
        )
        if not out.get('ok'):
            err = str(out.get('error') or 'Не изменено')
            if out.get('needLogin') or 'не привяз' in err.lower():
                await _term_fail(interaction, err)
                return
            await _term_fail(interaction, err)
            return
        user = out.get('user') or out.get('target') or {}
        name = user.get('name') or user.get('login') or player.display_name
        new_label = out.get('rankLabel') or user.get('rank') or rank
        old = out.get('oldRank') or '—'
        md = score_markdown(
            title='СМЕНА ЗВАНИЯ',
            name=str(name),
            delta=f'{old} → {new_label}',
            scores=str(new_label),
            reason=f'код {out.get("rank") or rank}',
            actor=interaction.user.display_name,
            mention=str(player.id),
        )
        if interaction.channel is not None:
            await send_terminal(
                interaction.channel,
                markdown=md,
                png=banner_bytes('award'),
                filename='legion_setrank.png',
                accent=CRT_RED,
                mention_ids=[str(player.id)],
            )
        try:
            await interaction.followup.send(
                f'◈ звание обновлено: **{old} → {new_label}**. Карточка в канале.',
                ephemeral=True,
            )
        except Exception:
            pass

    @setrank_cmd.autocomplete('rank')
    async def setrank_rank_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await _rank_choices(bot, current)

    @bot.tree.command(name='ranknew', description='Создать или править звание (состав, порядок, порог). ЯДРО / КМД / TERM.S')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(
        code='Код звания, например III.T или XII',
        title='Название (Рядовой, Капитан Такучи…)',
        need='Необходимая сумма баллов + репутации',
        group='Состав: младший / старший / офицерский / командный',
        order='Порядок в составе: 1 = младший',
        manual='Вручную, без авто-повышения (для спецзваний — да)',
    )
    @app_commands.choices(group=RANK_GROUP_CHOICES)
    async def ranknew_cmd(
        interaction: discord.Interaction,
        code: str,
        title: str,
        group: str,
        order: int,
        need: int = 0,
        manual: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)
        code = str(code or '').strip()
        if not code:
            await _term_fail(interaction, 'Укажите код звания.')
            return
        out = await _api_call(
            bot,
            bot.api.balls_rank_upsert,
            actor_discord_id=str(interaction.user.id),
            rank=code,
            title=str(title or '').strip(),
            need=int(need or 0),
            group=str(group or '').strip(),
            order=int(order or 0),
            manual=bool(manual),
        )
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не сохранено'))
            return
        verb = 'создано' if out.get('created') else 'обновлено'
        await _term_ok(
            interaction,
            title='ЗВАНИЕ',
            extra=(
                f'**{code}** — {title or code}\n'
                f'{group or "состав"} · порядок **{int(order or 0)}** · порог **{int(need or 0)}** · {verb}'
            ),
            kind='review_ok',
        )

    @bot.tree.command(name='rankneed', description='Изменить порог баллов у звания')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(rank='Звание с сайта', need='Необходимая сумма баллов + репутации')
    async def rankneed_cmd(interaction: discord.Interaction, rank: str, need: int):
        await interaction.response.defer(ephemeral=True)
        out = await _api_call(
            bot,
            bot.api.balls_rank_upsert,
            actor_discord_id=str(interaction.user.id),
            rank=str(rank or '').strip(),
            need=int(need),
        )
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не сохранено'))
            return
        await _term_ok(
            interaction,
            title='ПОРОГ ЗВАНИЯ',
            extra=f'**{rank}** → от **{int(need)}** баллов',
            kind='review_ok',
        )

    @rankneed_cmd.autocomplete('rank')
    async def rankneed_rank_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await _rank_choices(bot, current)

    async def _do_rankdel(interaction: discord.Interaction, rank: str) -> None:
        await interaction.response.defer(ephemeral=True)
        out = await _api_call(
            bot,
            bot.api.balls_rank_delete,
            actor_discord_id=str(interaction.user.id),
            rank=str(rank or '').strip(),
        )
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не удалено'))
            return
        await _term_ok(interaction, title='ЗВАНИЕ СНЯТО', extra=f'Удалено **{rank}**.', kind='review_no')

    @bot.tree.command(name='rankdel', description='Удалить добавленное звание (не штатную лестницу)')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(rank='Звание с сайта (начните вводить для поиска)')
    async def rankdel_cmd(interaction: discord.Interaction, rank: str):
        await _do_rankdel(interaction, rank)

    @rankdel_cmd.autocomplete('rank')
    async def rankdel_rank_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        choices = await _rank_choices(bot, current, custom_only=True)
        if choices:
            return choices
        return await _rank_choices(bot, current)

    @bot.tree.command(name='delrank', description='Удалить добавленное звание (список как у /setrank)')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(rank='Звание с сайта (начните вводить для поиска)')
    async def delrank_cmd(interaction: discord.Interaction, rank: str):
        await _do_rankdel(interaction, rank)

    @delrank_cmd.autocomplete('rank')
    async def delrank_rank_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        choices = await _rank_choices(bot, current, custom_only=True)
        if choices:
            return choices
        return await _rank_choices(bot, current)

    @bot.tree.command(name='warn', description='Выдать варн ролью Discord и записать на сайт')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(
        player='Боец с /login',
        level='Тип взыскания (роль на сервере)',
        reason='Причина (попадёт на сайт)',
        days='Срок в днях (для заключения по умолчанию 7)',
    )
    @app_commands.choices(level=[
        app_commands.Choice(name='Замечание', value='EL1'),
        app_commands.Choice(name='Выговор', value='EL2'),
        app_commands.Choice(name='Строгий выговор', value='EL3'),
        app_commands.Choice(name='Заключение', value='EL4'),
    ])
    async def warn_cmd(
        interaction: discord.Interaction,
        player: discord.Member,
        level: app_commands.Choice[str],
        reason: str,
        days: int = 0,
    ):
        await interaction.response.defer(ephemeral=True)
        lv = level.value if level else 'EL1'
        out = await _api_call(
            bot,
            bot.api.balls_warn_issue,
            actor_discord_id=str(interaction.user.id),
            target_discord_id=str(player.id),
            level=lv,
            text=str(reason or '').strip(),
            days=int(days or 0),
        )
        if not out.get('ok'):
            err = str(out.get('error') or 'Не выдано')
            await _term_fail(interaction, err)
            return
        extra = f'{player.mention} · **{level.name}**\n{reason}'
        if lv == 'EL4':
            extra += '\nTRAITOR / HAVOC сняты на срок заключения, роли вернутся по истечении.'
            d = int(days or 7)
            extra += f'\nсрок **{d}** сут.'
        await _term_ok(interaction, title='ВАРН', extra=extra, kind='review_no')
        if interaction.channel is not None:
            md = score_markdown(
                title='ВЗЫСКАНИЕ',
                name=player.display_name,
                delta=level.name,
                scores=lv,
                reason=str(reason or ''),
                actor=interaction.user.display_name,
                mention=str(player.id),
            )
            await send_terminal(
                interaction.channel,
                markdown=md,
                png=None,
                filename='',
                accent=CRT_RED,
                mention_ids=[str(player.id)],
            )

    @bot.tree.command(name='setnot', description='Каналы уведомлений сайта: отчёты, кодекс, операции, пейджер…')
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(
        kind='Тип изменений или «показать текущие»',
        channel='Куда слать (не нужен для списка)',
        clear='Снять канал с этого типа',
    )
    @app_commands.choices(kind=[
        app_commands.Choice(name='Показать текущие', value='list'),
        app_commands.Choice(name='Отчёты', value='reports'),
        app_commands.Choice(name='Кодекс', value='codex'),
        app_commands.Choice(name='Операции', value='ops'),
        app_commands.Choice(name='Пейджер', value='pager'),
        app_commands.Choice(name='Пользователи', value='users'),
        app_commands.Choice(name='Совет', value='council'),
        app_commands.Choice(name='Казна / склад', value='treasury'),
        app_commands.Choice(name='Общий (если нет отдельного)', value='all'),
    ])
    async def setnot_cmd(
        interaction: discord.Interaction,
        kind: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
        clear: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)
        kid = kind.value if kind else 'list'
        actor_id = str(interaction.user.id)
        if kid == 'list':
            out = await _api_call(bot, bot.api.notify_channels_list, actor_discord_id=actor_id)
            if not out.get('ok'):
                await _term_fail(interaction, str(out.get('error') or 'Нет прав. Нужны /login и ЯДРО / КМД.'))
                return
            chans = out.get('channels') or {}
            labels = out.get('labels') or {}
            lines = []
            for key in ('reports', 'codex', 'ops', 'pager', 'users', 'council', 'treasury', 'all'):
                lab = labels.get(key) or key
                cid = str(chans.get(key) or '').strip()
                lines.append(f'**{lab}:** ' + (f'<#{cid}>' if cid.isdigit() else '— не задан'))
            await _term_ok(
                interaction,
                title='КАНАЛЫ УВЕДОМЛЕНИЙ',
                extra='\n'.join(lines),
                kind='generic',
            )
            return
        if clear:
            out = await _api_call(
                bot,
                bot.api.notify_channels_set,
                actor_discord_id=actor_id,
                kind=kid,
                clear=True,
            )
            if not out.get('ok'):
                await _term_fail(interaction, str(out.get('error') or 'Не снято. Нужны /login и ЯДРО / КМД.'))
                return
            await _term_ok(interaction, title='КАНАЛ СНЯТ', extra=f'**{kind.name}** больше не шлётся отдельно.', kind='review_no')
            return
        if channel is None:
            await _term_fail(interaction, 'Укажите канал или поставьте clear. Для списка: kind = Показать текущие.')
            return
        out = await _api_call(
            bot,
            bot.api.notify_channels_set,
            actor_discord_id=actor_id,
            kind=kid,
            channel_id=str(channel.id),
        )
        if not out.get('ok'):
            await _term_fail(interaction, str(out.get('error') or 'Не записано. Нужны /login и ЯДРО / КМД.'))
            return
        md = score_markdown(
            title='ЖУРНАЛ САЙТА',
            extra=f'Сюда будут приходить изменения: **{kind.name}**.',
            actor=interaction.user.display_name,
        )
        try:
            await send_terminal(
                channel,
                markdown=md,
                png=banner_bytes('generic'),
                filename='legion_generic.png',
            )
        except Exception:
            log.exception('setnot test post failed')
        await _term_ok(
            interaction,
            title='КАНАЛ НАЗНАЧЕН',
            extra=f'**{kind.name}** → {channel.mention}',
            kind='review_ok',
        )

    @bot.listen('on_interaction')
    async def on_review_interaction(interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = ''
        if interaction.data:
            cid = str(interaction.data.get('custom_id') or '')
        if not cid.startswith('lgrev:'):
            return
        try:
            await handle_review_click(bot.api, interaction, cid)
        except Exception:
            log.exception('review click failed')
            if not interaction.response.is_done():
                try:
                    await interaction.response.send_message('Сбой разбора.', ephemeral=True)
                except Exception:
                    pass


def run_gateway(api: LegionApi) -> None:
    token = os.environ.get('DISCORD_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('DISCORD_BOT_TOKEN required for gateway mode')
    channel_map = load_channel_map()
    if not channel_map:
        log.warning('DISCORD_REPORT_CHANNELS empty — import on message disabled, slash commands still run')
    guild_raw = os.environ.get('DISCORD_GUILD_ID', '').strip()
    guild_id = int(guild_raw) if guild_raw.isdigit() else None
    bot = LegionBot(api, set(channel_map.keys()), guild_id=guild_id)
    register_slash(bot)
    bot.run(token, log_handler=None)
