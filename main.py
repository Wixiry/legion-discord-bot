#!/usr/bin/env python3
"""Legion Discord worker: periodic report import + optional realtime gateway."""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger('legion.worker')
ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path | None = None) -> None:
    """Load .env (Bothost checks python-dotenv; keep a tiny fallback)."""
    candidates = []
    if path is not None:
        candidates.append(Path(path))
    else:
        candidates.append(ROOT / '.env')
        candidates.append(Path.cwd() / '.env')
        candidates.append(Path('/app/.env'))
        data_dir = os.environ.get('DATA_DIR', '').strip()
        if data_dir:
            candidates.append(Path(data_dir) / '.env')
    seen = set()
    unique = []
    for p in candidates:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    try:
        from dotenv import load_dotenv as _load
        for p in unique:
            _load(p, override=False)
    except ImportError:
        for p in unique:
            if not p.is_file():
                continue
            for line in p.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    _apply_env_aliases()


def _apply_env_aliases() -> None:
    if not os.environ.get('DISCORD_BOT_TOKEN', '').strip():
        for name in ('TOKEN', 'BOT_TOKEN', 'DISCORD_TOKEN'):
            val = os.environ.get(name, '').strip()
            if val:
                os.environ['DISCORD_BOT_TOKEN'] = val
                break


def ensure_deps() -> None:
    """Install requirements.txt into ACL_PYTHON_PACKAGES if imports missing."""
    missing = []
    try:
        import discord  # noqa: F401
    except ImportError:
        missing.append('discord.py')
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append('requests')
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append('Pillow')
    try:
        import dotenv  # noqa: F401
    except ImportError:
        missing.append('python-dotenv')
    if not missing:
        return

    req = ROOT / 'requirements.txt'
    if not req.is_file():
        log.error('Missing packages %s and no requirements.txt', ', '.join(missing))
        sys.exit(32)

    target = os.environ.get('ACL_PYTHON_PACKAGES', str(ROOT / '.acl-python'))
    os.makedirs(target, exist_ok=True)
    log.info('Installing deps into %s: %s', target, ', '.join(missing))
    cmd = [
        sys.executable, '-m', 'pip', 'install',
        '--disable-pip-version-check', '-U',
        '--target', target,
        '-r', str(req),
    ]
    subprocess.check_call(cmd)
    if target not in sys.path:
        sys.path.insert(0, target)


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, '')
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def run_import_loop(api, *, once: bool, interval: int, full: bool, max_messages: int) -> int:
    total = 0
    round_no = 0
    body_full = full
    while True:
        round_no += 1
        out = api.import_reports(full=body_full, max_messages=max_messages)
        if not out.get('ok'):
            log.error('Import failed: %s', out)
            return 1
        n = int(out.get('importedCount') or 0)
        total += n
        log.info(
            'round=%s imported=%s refreshed=%s skipped=%s hasMore=%s',
            round_no,
            n,
            out.get('refreshed', 0),
            out.get('skipped', 0),
            out.get('hasMore'),
        )
        if once or not out.get('hasMore'):
            log.info('Import done, total=%s', total)
            break
        body_full = False
        time.sleep(1)
    return 0


def run_health(api) -> None:
    st = api.site_status()
    if st.get('ok'):
        log.info('Health OK maintenance=%s discord_only=%s', st.get('maintenance'), st.get('discord_only'))
    else:
        log.warning('Health check failed: %s', st)


def main() -> int:
    load_dotenv()
    ensure_deps()

    from legion_api import LegionApi

    ap = argparse.ArgumentParser(description='Legion Discord worker')
    ap.add_argument('--once', action='store_true', help='Single import pass')
    ap.add_argument('--full', action='store_true', help='Full backfill')
    ap.add_argument('--gateway', action='store_true', help='Run discord.py realtime listener')
    ap.add_argument('--interval', type=int, default=env_int('LEGION_IMPORT_INTERVAL', 90))
    ap.add_argument('--max-messages', type=int, default=env_int('LEGION_IMPORT_MAX_MESSAGES', 12))
    ap.add_argument('--health-every', type=int, default=env_int('LEGION_HEALTH_EVERY', 300))
    args = ap.parse_args()

    api = LegionApi()
    if not api.write_token:
        log.error('LEGION_WRITE_TOKEN not set — создай /home/container/.env')
        return 1

    if args.gateway:
        from report_listener import run_gateway
        run_gateway(api)
        return 0

    last_health = 0.0
    while True:
        now = time.time()
        if args.health_every > 0 and (now - last_health) >= args.health_every:
            run_health(api)
            last_health = now

        code = run_import_loop(
            api,
            once=args.once,
            interval=args.interval,
            full=args.full,
            max_messages=args.max_messages,
        )
        if code != 0:
            return code
        if args.once:
            return 0
        args.full = False
        time.sleep(max(30, args.interval))


if __name__ == '__main__':
    raise SystemExit(main())
