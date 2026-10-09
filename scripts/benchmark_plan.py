#!/usr/bin/env python3
"""Time a real saved Box without printing operator or account information."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maabase.optimizer import optimize
from maabase.roster_store import load_roster
from maabase.simulator import simulate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster', type=Path, default=ROOT / 'data/user_roster.json')
    parser.add_argument('--recycle-level', type=int, choices=range(4), default=3)
    parser.add_argument('--simulate-trials', type=int, default=0)
    args = parser.parse_args()
    catalog = json.loads((ROOT / 'data/catalog.json').read_text())
    roster = load_roster(args.roster, catalog)
    last = 0

    def progress(report):
        nonlocal last
        if report['elapsed_seconds'] - last >= 30:
            print(json.dumps(report, ensure_ascii=False), flush=True)
            last = report['elapsed_seconds']

    result = optimize(dict(operators=roster, base_layout='243', exp_factories=1,
                      shard_factories=1, orundum_trades=1, drone_target='auto_balance',
                      gold_net_target_per_day=-20, objective_mode='layout_output',
                      schedule_mode='staggered', shift_hours=36, max_work_hours=36,
                      collection_interval_hours=8, include_rotation=True,
                      candidate_limit=320, recycle_level=args.recycle_level), catalog, progress=progress)
    print(json.dumps({'operators': len(roster), 'optimization': result['performance']}, ensure_ascii=False, indent=2))
    if args.simulate_trials:
        last = 0
        replay = simulate({'rotation': result['rotation'], 'days': 30,
                           'trials': args.simulate_trials, 'seed': 0}, catalog, progress=progress)
        print(json.dumps({'simulation': replay['performance']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
