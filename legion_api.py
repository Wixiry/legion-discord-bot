"""HTTP client for Legion panel PHP API (import + health)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LegionApi:
    def __init__(
        self,
        base_url: str | None = None,
        write_token: str | None = None,
        timeout: int = 120,
    ):
        self.base_url = (base_url or os.environ.get('LEGION_API_URL', 'http://legionpanel.online/api')).rstrip('/')
        self.write_token = write_token or os.environ.get('LEGION_WRITE_TOKEN', '')
        self.timeout = timeout

    def _request(self, path: str, body: dict | None = None, method: str = 'GET', timeout: int | None = None) -> dict:
        url = f'{self.base_url}/{path.lstrip("/")}'
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('Content-Type', 'application/json; charset=utf-8')
        if self.write_token:
            req.add_header('X-Legion-Token', self.write_token)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout if timeout is None else timeout) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode('utf-8', errors='replace')
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {'ok': False, 'error': raw[:500], 'httpCode': e.code}
            payload['httpCode'] = e.code
            return payload
        except Exception as e:
            return {'ok': False, 'error': str(e)[:400]}

    def site_status(self) -> dict:
        return self._request('site_status.php')

    def import_reports(
        self,
        *,
        full: bool = False,
        max_messages: int = 12,
        refresh_images: bool = False,
        message_id: str | None = None,
        channel_id: str | None = None,
    ) -> dict:
        body: dict = {'action': 'import', 'maxMessages': max_messages}
        if full:
            body['full'] = True
        if refresh_images:
            body['refreshImages'] = True
        if message_id:
            body['messageId'] = message_id
        if channel_id:
            body['channelId'] = channel_id
        return self._request('discord_reports_import.php?action=import', body, method='POST')

    def import_status(self) -> dict:
        return self._request('discord_reports_import.php?action=status')

    def balls_login(self, *, code: str, discord_id: str) -> dict:
        return self._request(
            'balls.php',
            {
                'action': 'claim',
                'code': code,
                'discordId': discord_id,
            },
            method='POST',
        )

    def balls_me(self, *, discord_id: str) -> dict:
        return self._request(
            'balls.php',
            {'action': 'me', 'discordId': discord_id},
            method='POST',
        )

    def balls_card(self, *, discord_id: str) -> dict:
        return self._request(
            'balls.php',
            {'action': 'card', 'discordId': discord_id},
            method='POST',
        )

    def balls_week(self, *, actor_discord_id: str, platoon: str = '') -> dict:
        body = {
            'action': 'week',
            'actorDiscordId': actor_discord_id,
        }
        if platoon:
            body['platoon'] = platoon
        return self._request('balls.php', body, method='POST')

    def balls_platoon(self, *, platoon: str) -> dict:
        return self._request(
            'balls.php',
            {'action': 'platoon', 'platoon': platoon},
            method='POST',
        )

    def review_report(
        self,
        *,
        actor_discord_id: str,
        message_id: str,
        op: str,
        amount: float | None = None,
        silent: bool = True,
        note: str = '',
    ) -> dict:
        body: dict = {
            'action': 'review_report',
            'actorDiscordId': actor_discord_id,
            'messageId': message_id,
            'op': op,
            'silent': silent,
        }
        if amount is not None:
            body['amount'] = amount
        if note:
            body['note'] = note
        return self._request('balls.php', body, method='POST')

    def balls_give(
        self,
        *,
        actor_discord_id: str,
        target_discord_id: str,
        amount: float,
        reason: str = 'give',
        note: str = '',
    ) -> dict:
        body = {
            'action': 'give',
            'actorDiscordId': actor_discord_id,
            'targetDiscordId': target_discord_id,
            'amount': float(amount),
            'reason': reason,
        }
        if note:
            body['note'] = note
        return self._request('balls.php', body, method='POST')

    def balls_ranks(self) -> dict:
        return self._request('balls.php', {'action': 'ranks'}, method='POST', timeout=4)

    def balls_setrank(
        self,
        *,
        actor_discord_id: str,
        target_discord_id: str,
        rank: str,
    ) -> dict:
        return self._request(
            'balls.php',
            {
                'action': 'setrank',
                'actorDiscordId': actor_discord_id,
                'targetDiscordId': target_discord_id,
                'rank': rank,
            },
            method='POST',
        )

    def notify_channels_list(self, *, actor_discord_id: str) -> dict:
        return self._request(
            'discord_notify.php',
            {'action': 'list_channels', 'actorDiscordId': actor_discord_id},
            method='POST',
        )

    def notify_channels_set(
        self,
        *,
        actor_discord_id: str,
        kind: str,
        channel_id: str = '',
        clear: bool = False,
    ) -> dict:
        body = {
            'action': 'set_channel',
            'actorDiscordId': actor_discord_id,
            'kind': kind,
        }
        if clear:
            body['clear'] = True
        if channel_id:
            body['channelId'] = channel_id
        return self._request('discord_notify.php', body, method='POST')

    def gear_roster(self) -> dict:
        return self._request('gear.php', {'action': 'roster'}, method='POST')

    def balls_rank_upsert(
        self,
        *,
        actor_discord_id: str,
        rank: str,
        title: str = '',
        need: int = 0,
        group: str = '',
        order: int = 0,
        manual: bool = False,
    ) -> dict:
        body = {
            'action': 'rank_upsert',
            'actorDiscordId': actor_discord_id,
            'rank': rank,
            'title': title,
            'need': int(need),
            'manual': 1 if manual else 0,
        }
        if group:
            body['group'] = group
        if order:
            body['ord'] = int(order)
        return self._request('balls.php', body, method='POST')

    def balls_rank_delete(self, *, actor_discord_id: str, rank: str) -> dict:
        return self._request(
            'balls.php',
            {'action': 'rank_delete', 'actorDiscordId': actor_discord_id, 'rank': rank},
            method='POST',
        )

    def balls_warn_issue(
        self,
        *,
        actor_discord_id: str,
        target_discord_id: str,
        level: str,
        text: str = '',
        days: int = 0,
    ) -> dict:
        return self._request(
            'balls.php',
            {
                'action': 'warn_issue',
                'actorDiscordId': actor_discord_id,
                'targetDiscordId': target_discord_id,
                'level': level,
                'text': text,
                'days': int(days),
            },
            method='POST',
        )

    def balls_warn_clear(
        self,
        *,
        actor_discord_id: str,
        target_discord_id: str = '',
        login: str = '',
        warn_id: str = '',
        reason: str = 'Снят',
    ) -> dict:
        body = {
            'action': 'warn_clear',
            'actorDiscordId': actor_discord_id,
            'reason': reason,
        }
        if target_discord_id:
            body['targetDiscordId'] = target_discord_id
        if login:
            body['login'] = login
        if warn_id:
            body['id'] = warn_id
        return self._request('balls.php', body, method='POST')

    def balls_warn_list(self, *, actor_discord_id: str, target_discord_id: str = '', login: str = '') -> dict:
        body = {'action': 'warn_list', 'actorDiscordId': actor_discord_id}
        if target_discord_id:
            body['targetDiscordId'] = target_discord_id
        if login:
            body['login'] = login
        return self._request('balls.php', body, method='POST')

    def balls_warn_archive_clear(
        self,
        *,
        actor_discord_id: str,
        target_discord_id: str = '',
        login: str = '',
        warn_id: str = 'ALL',
    ) -> dict:
        body = {
            'action': 'warn_archive_clear',
            'actorDiscordId': actor_discord_id,
            'id': warn_id or 'ALL',
        }
        if target_discord_id:
            body['targetDiscordId'] = target_discord_id
        if login:
            body['login'] = login
        return self._request('balls.php', body, method='POST')

    def balls_warn_expire(self) -> dict:
        return self._request('balls.php', {'action': 'warn_expire'}, method='POST')

    def balls_warn_sync_role(
        self,
        *,
        actor_discord_id: str,
        target_discord_id: str,
        role_id: str,
        added: bool,
    ) -> dict:
        return self._request(
            'balls.php',
            {
                'action': 'warn_sync_role',
                'actorDiscordId': actor_discord_id,
                'targetDiscordId': target_discord_id,
                'roleId': role_id,
                'added': 1 if added else 0,
            },
            method='POST',
        )

    def gear_one(self, *, login: str = '', callsign: str = '') -> dict:
        body: dict = {'action': 'one'}
        if login:
            body['login'] = login
        if callsign:
            body['callsign'] = callsign
        return self._request('gear.php', body, method='POST')
