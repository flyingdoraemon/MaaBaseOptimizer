import json
from pathlib import Path
import unittest

from maabase.model import evaluate_team, prepare_operators, _value
from maabase.optimizer import production_counts, _metrics
from maabase.state_model import BaseContext, _control_effect, _target_matches
from maabase.valuation import resource_values, candidate_daily_value, metrics_daily_value, DRONE_VALUE, LMD_VALUE
from scripts.build_catalog import enum_number


class ProductionUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/catalog.json').read_text())

    def prepare(self, *ids, elite=2):
        return prepare_operators([{'id': id, 'elite': elite, 'level': 1} for id in ids], self.catalog)

    def test_all_factory_and_trade_product_combinations(self):
        cases = 0
        for trade, factory in ((2, 4), (1, 5), (3, 3)):
            for gold in range(factory + 1):
                for exp in range(factory - gold + 1):
                    shard = factory - gold - exp
                    for orundum in range(trade + 1):
                        got = production_counts({'gold_factories': gold, 'exp_factories': exp,
                                                 'shard_factories': shard, 'orundum_trades': orundum}, factory, trade)
                        self.assertEqual(got, (gold, exp, shard, orundum))
                        cases += 1
        self.assertEqual(cases, 127)

    def test_invalid_combinations_are_not_silently_clamped(self):
        for payload in ({'exp_factories': 3, 'shard_factories': 2}, {'exp_factories': -1},
                        {'orundum_trades': 3}, {'shard_factories': 1.5}, {'gold_factories': 4}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                production_counts(payload, 4, 2)

    def test_latest_sees_unlock_control_and_factory_count(self):
        makoto = self.prepare('char_4217_makoto')
        self.assertEqual(evaluate_team(makoto, 'gold', self.catalog)['efficiency'], 25)
        context = BaseContext(sees_operator_ids=['char_4217_makoto', 'char_4219_yukari', 'char_4218_aigis', 'char_4220_kormr'])
        for product in ('gold', 'exp', 'shard'):
            self.assertEqual(evaluate_team(makoto, product, self.catalog, context)['efficiency'], 40)
        e0 = self.prepare('char_4217_makoto', elite=0)
        self.assertEqual(evaluate_team(e0, 'gold', self.catalog)['efficiency'], 0)
        _, control = _control_effect(tuple(e0), BaseContext(control_factory_speed=2))
        self.assertEqual(control.control_factory_speed, 2)

    def test_aigis_raw_zero_efficiency_and_manufacturing_condition(self):
        aigis = self.prepare('char_4218_aigis')
        self.assertEqual(evaluate_team(aigis, 'power', self.catalog)['efficiency'], 15)
        ctx = BaseContext(factory_operator_ids=['char_4217_makoto'])
        self.assertEqual(evaluate_team(aigis, 'power', self.catalog, ctx)['efficiency'], 20)

    def test_product_specific_skills_do_not_leak_into_other_chains(self):
        self.assertEqual(_value({'Money': 90, 'SyntheticJade': 20}, 'orundum'), 20)
        self.assertFalse(_target_matches({'targets': ['F_GOLD']}, 'shard'))
        self.assertEqual(enum_number('PHASE_2'), 2)
        self.assertEqual(enum_number(2), 2)

    def test_yituliu_farming_price_and_full_resource_ledger_agree(self):
        for recipe, material, count, lmd in [('rock', 1.2, 2, 1600), ('device', 3.5, 1, 1000)]:
            settings = {'orundum_pricing': recipe, recipe: material}
            values = resource_values(settings)
            self.assertAlmostEqual(values['orundum'], (count * material + lmd * LMD_VALUE + 40 * DRONE_VALUE) / 10)
            shard = {'multiplier': 1, 'valuation': settings, 'shard_recipe': recipe}
            trade = {'orundum': {'orundum_per_day': 240, 'shards_per_day': 24}, 'valuation': settings}
            metrics = {'orundum_per_day': 240, 'shards_net_per_day': 0,
                       'lmd_shard_cost_per_day': 24 * lmd, 'shard_material_used_per_day': count * 24,
                       'shard_recipe': recipe, 'valuation': settings}
            self.assertAlmostEqual(metrics_daily_value(metrics), candidate_daily_value(shard, 'shard') + candidate_daily_value(trade, 'orundum'))
            self.assertAlmostEqual(metrics_daily_value(metrics), 960 * DRONE_VALUE)

    def test_drone_manufacturing_yield_does_not_scale_with_staff_speed(self):
        for multiplier in (1, 3):
            candidate = {'multiplier': multiplier, 'operators': ['exp'], 'names': ['测试']}
            metrics = _metrics({'exp': [candidate]}, self.catalog, 'exp')
            self.assertAlmostEqual(metrics['drone_effect']['exp_per_day'], 4000)
            self.assertEqual(metrics['exp_per_day'], 8000 * multiplier + 4000)

    def test_unpriced_materials_are_explicit_and_invalid_prices_rejected(self):
        self.assertEqual(resource_values()['unpriced_materials'], ['rock', 'device'])
        with self.assertRaises(ValueError):
            resource_values({'orundum_pricing': 'rock'})
        with self.assertRaises(ValueError):
            resource_values({'orundum': float('nan')})


if __name__ == '__main__':
    unittest.main()
