import threading
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from maabase.calculation import Calculation, calculation, stage, current_calculation
from maabase.jobs import JobStore


class CalculationTests(unittest.TestCase):
    def test_nested_stages_do_not_double_count(self):
        now = [0.0]
        with patch('maabase.calculation.perf_counter', side_effect=lambda: now[0]):
            tracker = Calculation()
            with tracker.stage('efficiency', '制造站'):
                now[0] = 2
                with tracker.stage('solver'):
                    now[0] = 5
                now[0] = 7
            report = tracker.snapshot()
        self.assertEqual(report['stage_seconds'], {'efficiency': 4, 'solver': 3})
        self.assertEqual(report['elapsed_seconds'], 7)

    def test_recursive_calculation_shares_scope_but_next_request_does_not(self):
        scopes = []
        @calculation
        def run(n):
            scopes.append(current_calculation())
            if n:
                run(n-1)
            with stage('simulation', '虚拟时间 7 天'):
                pass
            return {'answer': n}
        result = run(1)
        run(0)
        self.assertIs(scopes[0], scopes[1])
        self.assertIsNot(scopes[1], scopes[2])
        self.assertIn('simulation', result['performance']['stage_seconds'])

    def test_job_returns_before_calculation_and_reports_progress_and_result(self):
        entered, finish = threading.Event(), threading.Event()
        @calculation
        def run(payload):
            with stage('efficiency', 'A 班 / 赤金'):
                entered.set()
                finish.wait(2)
            return {'value': payload['value']}
        store = JobStore(max_pending=2)
        try:
            job = store.submit(run, {'value': 42})
            self.assertTrue(entered.wait(1))
            self.assertEqual(store.get(job)['progress']['stage'], 'efficiency')
            self.assertEqual(store.get(job)['status'], 'running')
            finish.set()
            store.wait(job, timeout=2)
            self.assertEqual(store.result(job)['value'], 42)
            self.assertEqual(store.get(job)['status'], 'completed')
        finally:
            finish.set()
            store.close()

    def test_failed_job_finishes_with_error(self):
        store = JobStore()
        try:
            def fail(_):
                raise ValueError('干员不足')
            job = store.submit(fail, {})
            store.wait(job, timeout=2)
            self.assertEqual(store.get(job)['status'], 'failed')
            self.assertEqual(store.get(job)['error'], '干员不足')
        finally:
            store.close()

    def test_candidate_reuse_preserves_full_context_and_isolates_mutations(self):
        from maabase import model
        from maabase.state_model import BaseContext
        catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/catalog.json').read_text())
        ops = model.prepare_operators([{'id': oid, 'elite': 2, 'level': 1}
                                       for oid in ['char_002_amiya', 'char_003_kalts', 'char_017_huang', 'char_101_sora']], catalog)
        @calculation
        def run():
            with patch.object(model, '_generate_candidates', wraps=model._generate_candidates) as generator:
                a = model.generate_candidates(ops, 'gold', catalog, 120, BaseContext())
                expected = json.loads(json.dumps(a))
                a[0]['details'][0]['operator'] = 'changed'
                b = model.generate_candidates(ops, 'gold', catalog, 120, BaseContext())
                self.assertEqual(b, expected)
                equivalent = model.generate_candidates(ops, 'gold', catalog, 120,
                             BaseContext(working_operator_ids=['unrelated'], audit=['different annotation']))
                self.assertEqual(equivalent, expected)
                different = model.generate_candidates(ops, 'gold', catalog, 120, BaseContext(control_factory_speed=10))
                self.assertEqual(generator.call_count, 2)
                self.assertAlmostEqual(different[0]['multiplier'] - b[0]['multiplier'], .1)
            return {}
        self.assertEqual(run()['performance']['cache_hits']['candidates'], 2)

    def test_cached_candidates_equal_fresh_calculation_across_skill_states(self):
        from maabase import model
        from maabase.state_model import BaseContext
        catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/catalog.json').read_text())
        names = {'但书', '龙舌兰', '孑', '德克萨斯', '拉普兰德', '温蒂', '森蚺', '清流',
                 '红云', '泡泡', '火神', '砾', '迷迭香', '迷图', '淬羽赫默', '冬时', '结城理', '澄闪'}
        ops = model.prepare_operators([{'id': oid, 'elite': 2, 'level': 90}
                                      for oid, op in catalog['operators'].items() if op['name'] in names], catalog)
        self.assertGreaterEqual(len(ops), 14)
        contexts = [BaseContext(), BaseContext(shift_hours=24, control_factory_speed=2,
                    control_trade_speed=7, platform_power_count=2, gold_lines=2,
                    working_group_counts={'rhine': 3}, factory_operator_ids=['char_4217_makoto']),
                    BaseContext(shift_hours=12, operator_morale={op['id']: 4 for op in ops},
                                human_fire=60, thought_chain=20, drone_capacity=100)]
        @calculation
        def run():
            for product in ('trade', 'orundum', 'gold', 'exp', 'shard', 'power'):
                for ctx in [*contexts, contexts[0]]:
                    fresh = model._generate_candidates(ops, product, catalog, 120, ctx)
                    cached = model.generate_candidates(ops, product, catalog, 120, ctx)
                    self.assertEqual(cached, fresh, product)
            return {}
        self.assertGreaterEqual(run()['performance']['cache_hits']['candidates'], 6)
