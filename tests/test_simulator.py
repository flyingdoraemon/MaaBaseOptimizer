import unittest

from maabase.simulator import simulate


def room(key='gold', speed=1, **extra):
    return {'key': key, 'room': '测试房间', 'operators': ['test'], 'multiplier': speed, **extra}


def run(rooms, **extra):
    return simulate({'rooms': rooms, 'days': 1, 'trials': 1, 'seed': 123, **extra})


class SimulatorTests(unittest.TestCase):
    def test_complete_products_and_uncollected_inventory(self):
        result = run([room()], metrics={'collection_interval_hours': 7})
        self.assertEqual(result['completed_output']['gold_made_per_day'], 20)
        self.assertEqual(result['simulated']['gold_made_per_day'], 16)
        self.assertEqual(result['pending_output']['gold_made_per_day'], 4)
        self.assertEqual([e['hour'] for e in result['collection_events']], [6, 13, 20])
        self.assertEqual(result['virtual_minutes'], 1440)

    def test_handover_keeps_unfinished_product_and_switches_speed(self):
        a, b = room(), room(speed=2)
        rotation = {'cycle_hours': 24, 'teams': {'A': {'rooms': [a]}, 'B': {'rooms': [b]}},
                    'rooms': [{'room': a['room'], 'key': 'gold', 'events': [
                        {'start': 0, 'end': 1, 'team': 'A'}, {'start': 1, 'end': 24, 'team': 'B'}]}]}
        result = run([], rotation=rotation)
        self.assertAlmostEqual(result['trace'][0]['minute'], 66)
        self.assertEqual(result['simulated']['gold_made_per_day'], 39)

    def test_warehouse_stops_until_collection(self):
        result = run([room(output_capacity=2)], metrics={'collection_interval_hours': 12})
        self.assertEqual(result['simulated']['gold_made_per_day'], 4)
        self.assertEqual([e['minute'] for e in result['trace']], [72, 144, 792, 864])

    def test_saved_strict_setting_still_allows_external_material_supply(self):
        result = run([room('orundum', output_capacity=2)], inventory_policy='strict')
        self.assertEqual(result['simulated']['orundum_per_day'], 120)
        self.assertEqual(result['pending_output']['orundum_per_day'], 0)
        self.assertEqual(result['collection_events'][-1]['shards'], -12)

    def test_factory_collection_precedes_trade_settlement(self):
        a = room('shard', room='碎片')
        b = room('orundum', room='订单')
        result = run([b, a], inventory_policy='strict')
        self.assertEqual(result['simulated']['orundum_per_day'], 240)
        self.assertEqual(result['simulated']['shards_net_per_day'], 0)
        self.assertEqual(result['simulated']['lmd_shard_cost_per_day'], 24 * 1600)
        self.assertEqual(result['collection_events'][-1]['gold'], 0)

    def test_drones_are_spent_only_at_online_nodes(self):
        result = run([room()], metrics={'collection_interval_hours': 12,
                     'drones_recovery_potential_per_day': 2,
                     'drone_effect': {'allocations': [{'target_operators': ['test'], 'kind': 'gold', 'drones_per_day': 2}]}})
        self.assertEqual([e['minute'] for e in result['drone_events']], [720, 1440])
        self.assertEqual([e['drones_spent'] for e in result['drone_events']], [1, 1])
        self.assertEqual(result['trace'][9]['minute'], 720)
        self.assertEqual(result['trace'][10]['minute'], 789)
        self.assertAlmostEqual(result['work_in_progress'][0]['remaining_base_minutes'], 66)

    def test_drone_reduces_base_minutes_at_high_staff_speed(self):
        metrics = {'collection_interval_hours': 8, 'drones_recovery_potential_per_day': 60,
                   'drone_effect': {'allocations': [{'target_operators': ['test'], 'kind': 'exp', 'drones_per_day': 60}]}}
        result = run([room('exp', speed=3)], metrics=metrics)
        self.assertEqual(result['simulated']['exp_per_day'], 25000)
        self.assertEqual(sum(event['drones_spent'] for event in result['drone_events']), 60)

    def test_hourly_skill_uses_phase_rate_before_completion(self):
        # No staffed baseline in this synthetic fixture: 1x first hour, 2x afterwards.
        a = room(operators=[], efficiency=50, time_profiles=[{'average_percent': 50, 'phases': [
            {'start_hour': 0, 'end_hour': 1, 'value_percent': 0},
            {'start_hour': 1, 'end_hour': 24, 'value_percent': 100}]}])
        result = run([a])
        self.assertAlmostEqual(result['trace'][0]['minute'], 66)
        self.assertEqual(result['simulated']['gold_made_per_day'], 39)

    def test_seed_reproduces_actual_order_trace_and_whole_run_percentiles(self):
        a = room('trade', trade={'distribution': [
            {'minutes': 144, 'gold': 2, 'lmd': 1000, 'probability': .3},
            {'minutes': 210, 'gold': 3, 'lmd': 1500, 'probability': .5},
            {'minutes': 276, 'gold': 4, 'lmd': 2000, 'probability': .2}]})
        first = run([a], trials=40)
        self.assertEqual(first, run([a], trials=40))
        self.assertNotEqual(first['trace'], run([a], seed=124)['trace'])
        self.assertLessEqual(first['simulated']['lmd_p05'], first['simulated']['lmd_p95'])
        self.assertGreater(first['standard_deviation']['lmd_per_day'], 0)

    def test_work_fraction_and_fractional_collection_nodes(self):
        result = run([room(work_fraction=.5)], metrics={'collection_interval_hours': 2.5}, days=10)
        self.assertEqual(result['collection_events'][0]['hour'], 6)
        self.assertEqual(result['collection_events'][-1]['hour'], 239.5)
        self.assertEqual(result['simulated']['gold_made_per_day'], 10)

    def test_rejects_missing_trade_distribution_and_duplicate_rooms(self):
        with self.assertRaises(ValueError):
            run([room('trade')])
        with self.assertRaises(ValueError):
            run([room(), room()])

    def test_large_seed_survives_browser_json_without_rounding(self):
        seed = 2**63 - 1
        first = run([room()], seed=seed)
        self.assertEqual(first['seed'], str(seed))
        self.assertEqual(first, run([room()], seed=first['seed']))


if __name__ == '__main__':
    unittest.main()
