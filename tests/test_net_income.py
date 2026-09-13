import json
from pathlib import Path
import unittest

from maabase.optimizer import _metrics
from maabase.scheduler import _production_curve, build_staggered_production_curve
from maabase.simulator import simulate


class NetIncomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((Path(__file__).parents[1] / 'data/catalog.json').read_text())

    def test_manufacturing_drone_cost_matches_both_timeline_engines(self):
        room = {'key': 'shard', 'room': '碎片制造站', 'operators': ['worker'],
                'names': ['测试'], 'multiplier': 1, 'efficiency': 0}
        for recipe, unit_cost in [('rock', 1600), ('device', 1000)]:
            with self.subTest(recipe=recipe):
                metrics = _metrics({'shard': [room]}, self.catalog, 'shard', shard_recipe=recipe)
                team = {'rooms': [room], 'metrics': metrics}
                fixed = _production_curve({'A': team, 'B': team}, {'A': 12, 'B': 12}, 8)
                staggered = build_staggered_production_curve({
                    'teams': {'A': team}, 'average_metrics': metrics,
                    'collection_interval_hours': 8, 'cycle_hours': 24,
                    'rooms': [{'room': room['room'], 'events': [{'start': 0, 'end': 24, 'team': 'A'}]}],
                }, self.catalog['constants'], drone_target='shard', external_gold_per_day=0,
                    gold_net_target_per_day=0)
                for curve in (fixed, staggered):
                    final = curve['points'][-1]['cumulative']
                    self.assertAlmostEqual(final['shards_made_per_day'], 36)
                    self.assertAlmostEqual(final['lmd_shard_cost_per_day'], 36 * unit_cost)
                    self.assertAlmostEqual(final['lmd_net_after_shards_per_day'], -36 * unit_cost)
                    self.assertAlmostEqual(final['lmd_shard_cost_per_day'], metrics['lmd_shard_cost_per_day'])
                    for point in curve['points']:
                        for series in ('cumulative', 'rates_per_hour'):
                            values = point[series]
                            self.assertAlmostEqual(values['lmd_net_after_shards_per_day'],
                                                   values['lmd_per_day'] - values['lmd_shard_cost_per_day'], places=5)

    def test_simulation_deducts_completed_uncollected_shards_and_reports_net_interval(self):
        for recipe, unit_cost in [('rock', 1600), ('device', 1000)]:
            with self.subTest(recipe=recipe):
                result = simulate({'rooms': [{'key': 'shard', 'room': '碎片站', 'multiplier': 1}],
                                   'metrics': {'shard_recipe': recipe, 'collection_interval_hours': 2,
                                               'lmd_net_after_shards_per_day': -24 * unit_cost},
                                   'days': 1, 'trials': 3, 'seed': 11})
                simulated = result['simulated']
                self.assertEqual(simulated['lmd_per_day'], 0)
                self.assertEqual(result['pending_output']['shards_made_per_day'], 2)
                self.assertEqual(simulated['lmd_shard_cost_per_day'], 24 * unit_cost)
                self.assertEqual(simulated['lmd_net_after_shards_per_day'], -24 * unit_cost)
                self.assertEqual(simulated['lmd_net_p05'], -24 * unit_cost)
                self.assertEqual(simulated['lmd_net_p95'], -24 * unit_cost)
                self.assertEqual(result['difference_percent']['lmd_net_after_shards_per_day'], 0)
                collected = result['collection_events'][-1]['collected']
                self.assertEqual(collected['lmd_net_after_shards_per_day'], -22 * unit_cost)

    def test_no_shard_manufacturing_has_no_cash_cost(self):
        result = simulate({'rooms': [{'key': 'orundum', 'room': '源石订单', 'multiplier': 1}],
                           'days': 1, 'trials': 1})
        self.assertGreater(result['simulated']['orundum_per_day'], 0)
        self.assertEqual(result['simulated']['lmd_shard_cost_per_day'], 0)
        self.assertEqual(result['simulated']['lmd_net_after_shards_per_day'], 0)


if __name__ == '__main__':
    unittest.main()
