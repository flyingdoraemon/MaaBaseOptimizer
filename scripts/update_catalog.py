#!/usr/bin/env python3
"""Download one pinned CN revision and atomically rebuild the local catalog."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

from build_catalog import build

ROOT = Path(__file__).resolve().parents[1]
GAME_REPO = 'Kengxxiao/ArknightsGameData'


def fetch(url: str) -> bytes:
    with urlopen(Request(url, headers={'User-Agent': 'MaaBaseOptimizer-catalog'}), timeout=90) as response:
        return response.read()


def update(output: Path, revision: str = 'master', maa_path: Path | None = None) -> dict:
    commit = json.loads(fetch(f'https://api.github.com/repos/{GAME_REPO}/commits/{revision}'))
    sha = commit['sha']
    hashes = {}
    with tempfile.TemporaryDirectory(prefix='maabase-catalog-') as temp:
        directory = Path(temp)
        for name in ('building_data.json', 'character_table.json', 'uniequip_table.json'):
            raw = fetch(f'https://raw.githubusercontent.com/{GAME_REPO}/{sha}/zh_CN/gamedata/excel/{name}')
            json.loads(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
            (directory / name).write_bytes(raw)
        if maa_path is None:
            maa_commit = json.loads(fetch('https://api.github.com/repos/MaaAssistantArknights/MaaAssistantArknights/commits/dev-v2'))
            maa_sha = maa_commit['sha']
            maa_path = directory / 'infrast.json'
            maa_path.write_bytes(fetch(f'https://raw.githubusercontent.com/MaaAssistantArknights/MaaAssistantArknights/{maa_sha}/resource/infrast.json'))
        else:
            maa_sha = 'local-file'
        hashes['infrast.json'] = hashlib.sha256(maa_path.read_bytes()).hexdigest()
        catalog = build(directory / 'building_data.json', directory / 'character_table.json', maa_path)
        catalog['sources'].update(building_data=f'{GAME_REPO}/zh_CN', game_revision=sha,
                                  game_updated_at=commit['commit']['committer']['date'],
                                  game_version=commit['commit']['message'], maa_revision=maa_sha,
                                  fetched_at=datetime.now(timezone.utc).isoformat(), sha256=hashes)
        # All parsing completes before the existing catalog is touched.
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=output.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(catalog, stream, ensure_ascii=False, separators=(',', ':'))
            os.replace(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='master')
    parser.add_argument('--maa-infrast', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/catalog.json')
    args = parser.parse_args()
    result = update(args.output, args.revision, args.maa_infrast)
    print(f"Updated {args.output}: {len(result['operators'])} operators, {len(result['buffs'])} buffs; {result['sources']['game_revision']}")


if __name__ == '__main__':
    main()
