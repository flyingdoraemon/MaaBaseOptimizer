import json
from pathlib import Path
import unittest

from maabase.model import prepare_operators
from maabase.optimizer import _support_rows
from maabase.recycle import settings, evaluate_recycle
from maabase.simulator import simulate
from maabase.work_morale import morale_rates
from maabase.state_model import catalog_mechanism_coverage


class RecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/catalog.json').read_text())

    def test_levels_use_client_slots_capacity_and_speed(self):
        for level, slots, capacity, speed in [(1, 1, 5, 1), (2, 2, 10, 1), (3, 2, 10, 1.2)]:
            config = settings({'recycle_level': level}, self.catalog)
            self.assertEqual((config['slots'], config['capacity'], config['base_multiplier']), (slots, capacity, speed))
            self.assertEqual(config['base_minutes'], 2880)
        self.assertIsNone(settings({'recycle_level': 0}, self.catalog))
        with self.assertRaises(ValueError):
            settings({'recycle_level': 2, 'recycle_boost': True}, self.catalog)

    def test_hbound_unlock_and_continuous_supply(self):
        config = settings({}, self.catalog)
        for elite, efficiency in [(0, 20), (1, 20), (2, 30)]:
            team = prepare_operators([{'id': 'char_4232_hbound', 'elite': elite, 'level': 1}], self.catalog)
            room = evaluate_recycle(team, config)
            self.assertEqual(room['efficiency'], efficiency)
            self.assertAlmostEqual(room['multiplier'], 1.21 + efficiency/100)
        boosted = evaluate_recycle(team, settings({'recycle_boost': True}, self.catalog))
        self.assertAlmostEqual(boosted['multiplier'] - room['multiplier'], .5)
        self.assertGreaterEqual(catalog_mechanism_coverage(self.catalog)['exact_count'], 339)

    def test_specialist_reserved_before_neutral_support_and_no_duplicates(self):
        roster = [{'id': oid, 'elite': 2, 'level': 1} for oid in
                  ['char_4232_hbound', 'char_002_amiya', 'char_003_kalts', 'char_101_sora', 'char_103_angel', 'char_017_huang']]
        ops = prepare_operators(roster, self.catalog)
        rows = _support_rows(ops, set(), 24, recycle_config=settings({}, self.catalog))
        recycler = next(row for row in rows if row['key'] == 'recycle')
        self.assertIn('char_4232_hbound', recycler['operators'])
        ids = [oid for row in rows for oid in row['operators']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_progress_survives_handover_and_collects_only_when_online(self):
        # Unstaffed level 1: one conversion every 48h, repeated 16h/8h
        # handovers must not reset the physical room's unfinished conversion.
        room = evaluate_recycle([], settings({'recycle_level': 1}, self.catalog))
        rotation = {'cycle_hours': 24, 'schedule_mode': 'fixed', 'collection_interval_hours': 8,
                    'teams': {'A': {'rooms': [room]}, 'B': {'rooms': [room]}},
                    'rooms': [{'room': '回收站', 'key': 'recycle', 'events': [
                        {'team': 'A', 'start': 0, 'end': 16}, {'team': 'B', 'start': 16, 'end': 24}]}]}
        replay = simulate({'rotation': rotation, 'days': 7, 'trials': 1, 'seed': 1}, self.catalog)
        self.assertEqual(replay['completed_output']['recycle_cycles_per_day'], 3)
        self.assertEqual(replay['simulated']['recycle_cycles_per_day'], round(3/7, 6))
        self.assertEqual([x['minute'] for x in replay['trace'] if x.get('product') == 'recycle'], [2880, 5760, 8640])
        self.assertTrue(all(event['hour'] % 8 == 0 for event in replay['collection_events']))

    def test_zero_morale_disables_skill_but_keeps_natural_conversion(self):
        ops = prepare_operators([{'id': 'char_4232_hbound', 'elite': 2, 'level': 1}], self.catalog)
        room = evaluate_recycle(ops, settings({}, self.catalog))
        control = {'operators': ['a', 'b', 'c', 'd', 'e']}
        self.assertEqual(morale_rates(room, control)['char_4232_hbound'], .75)
        result = simulate({'rooms': [room], 'days': 7, 'trials': 1, 'seed': 0,
                           'initial_morale': {'char_4232_hbound': 0}}, self.catalog)
        self.assertEqual(result['completed_output']['recycle_cycles_per_day'], 4)
        self.assertTrue(result['morale']['exhausted_work_hours'])
