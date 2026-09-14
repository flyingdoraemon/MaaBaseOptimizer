import json
from pathlib import Path
import unittest

from maabase.login_calendar import login_hours
from maabase.scheduler import _team_duration, build_rotation
from maabase.work_morale import morale_rates
from maabase.simulator import simulate
from maabase.morale_runtime import compile_morale
from maabase.model import evaluate_team, prepare_operators


def worker(operator='a', **kwargs):
    return {'key': 'gold', 'room': 'factory', 'operators': [operator], 'names': [operator],
            'details': [{'operator': operator, 'skills': []}], 'multiplier': 2., **kwargs}


class MoraleRuntimeTests(unittest.TestCase):
    def test_control_and_local_staff_reduction_applied_once(self):
        control = {'operators': ['c1', 'c2', 'c3', 'c4', 'c5'], 'key': 'control'}
        room = worker(operators=['a', 'b', 'c'])
        self.assertEqual(set(morale_rates(room, control).values()), {.65})
        self.assertEqual(set(morale_rates(control, control).values()), {.75})
        self.assertEqual(morale_rates(worker(), {}), {'a': 1.})

    def test_conditional_partner_and_product_morale(self):
        room = worker(details=[{'operator': 'a', 'skills': [
            {'description': '当与拉普兰德在同一个贸易站时，心情每小时消耗+0.3'},
            {'description': '进驻制造站时，生产作战记录类配方时，心情每小时消耗-0.25'}]}])
        self.assertEqual(morale_rates(room)['a'], 1.)
        self.assertEqual(morale_rates({**room, 'key': 'exp'})['a'], .75)

    def test_control_recovery_can_exceed_consumption(self):
        room = {'key': 'control', 'operators': list('abcde'), 'details': [
            {'operator': op, 'skills': [{'description': '控制中枢内所有干员的心情每小时恢复+0.2'}]} for op in 'abcde']}
        self.assertEqual(set(morale_rates(room).values()), {-.25})

    def test_exhaustion_changes_rate_without_offline_handover(self):
        result = simulate({'rooms': [worker()], 'days': 1, 'trials': 1, 'seed': 0,
                           'initial_morale': {'a': 2}, 'metrics': {'collection_interval_hours': 8}})
        exhausted = result['morale']['events'][0]
        self.assertEqual(exhausted, {'minute': 120., 'type': 'exhausted', 'operator': 'a', 'handover': False})
        self.assertEqual(result['morale']['exhausted_work_hours'], {'a': 22})
        self.assertEqual(result['completed_output']['gold_made_per_day'], 21)
        self.assertEqual([e['hour'] for e in result['collection_events']], [8, 16, 24])
        self.assertTrue(all(e['type'] == 'completion' for e in result['trace']))

    def test_no_artificial_morale_reset_at_day_boundary(self):
        result = simulate({'rooms': [worker()], 'days': 2, 'trials': 1, 'seed': 0})
        self.assertEqual(result['morale']['final_morale']['a'], 0)
        self.assertEqual(result['morale']['exhausted_work_hours']['a'], 24)
        self.assertEqual(result['simulated']['gold_made_per_day'], 30)

    def test_full_factory_pauses_morale_until_login(self):
        result = simulate({'rooms': [worker(output_capacity=2)], 'days': 1, 'trials': 1,
                           'metrics': {'collection_interval_hours': 12}})
        self.assertEqual(result['completed_output']['gold_made_per_day'], 4)
        self.assertAlmostEqual(result['morale']['final_morale']['a'], 21.6)

    def test_full_dorm_beds_are_not_reassigned_while_offline(self):
        schedules = [{'name': f'room-{i}', 'spans': [(480, 960, worker(str(i)))]} for i in range(21)]
        _, report = compile_morale(schedules, 960, 480, 480, {}, initial={str(i): 0 for i in range(21)})
        values = list(report['final_morale'].values())
        self.assertEqual(values.count(24), 20)
        self.assertEqual(values.count(0), 1)
        self.assertEqual(len(report['dorm_overflow_operators']), 1)

    def test_no_exhaustion_triggered_handover_between_logins(self):
        room = worker(details=[{'operator': 'a', 'skills': [{'description': '心情每小时消耗+20'}]}])
        self.assertEqual(_team_duration({'rooms': [room]}, 8, 1, 24), 8)

    def test_night_calendar_and_eight_hour_boundary(self):
        for interval in (1, 2, 3, 4, 5, 6, 7.5):
            with self.subTest(interval=interval):
                nodes = login_hours(interval, 72)
                self.assertTrue(all(6 <= hour % 24 < 24 for hour in nodes))
                self.assertIn(6, nodes)
                self.assertIn(30, nodes)
        self.assertEqual(login_hours(8, 24), [8, 16, 24])
        self.assertEqual(login_hours(12, 24), [12, 24])

    def test_wrapped_night_keeps_same_assignment_and_warmup(self):
        def team(op):
            return {'rooms': [worker(op)], 'metrics': {}}
        rotation = build_rotation(team('a'), team('b'), 24, schedule_mode='staggered',
                                  collection_interval_hours=2, max_work_hours=24)
        events = rotation['rooms'][0]['events']
        self.assertEqual(events[0]['team'], events[-1]['team'])
        self.assertTrue(events[0]['continuation'])
        self.assertGreater(events[0]['elapsed_offset_hours'], 0)
        self.assertTrue(all(6 <= e['time'] % 24 < 24 for e in rotation['handover_events']))
        result = simulate({'rotation': rotation, 'days': 2, 'trials': 1})
        self.assertTrue(all(6 <= e['hour'] % 24 < 24 for e in result['collection_events']))
        self.assertFalse(result['morale']['exhausted_work_hours'])

    def test_known_operator_subset_rebuilds_skills_after_exhaustion(self):
        catalog = json.loads((Path(__file__).parents[1] / 'data/catalog.json').read_text())
        operators = prepare_operators([{'id': 'char_123_fang', 'elite': 1, 'level': 55},
                                       {'id': 'char_502_nblade', 'elite': 0, 'level': 30}], catalog)
        candidate = {'room': 'factory', 'key': 'gold', **evaluate_team(operators, 'gold', catalog)}
        result = simulate({'rooms': [candidate], 'days': 1, 'trials': 1,
                           'initial_morale': {'char_123_fang': 1}}, catalog)
        self.assertIn('char_123_fang', result['morale']['exhausted_work_hours'])
        self.assertGreater(result['completed_output']['gold_made_per_day'], 20)

class CalendarRegressionTests(unittest.TestCase):
    def test_fixed_eight_hour_rotation_is_unchanged_with_short_collection_setting(self):
        def team(op):
            return {'rooms': [worker(op)], 'metrics': {}}
        rotation = build_rotation(team('a'), team('b'), 8, schedule_mode='fixed', collection_interval_hours=2)
        self.assertEqual(rotation['cycle_hours'], 16)
        self.assertIsNone(rotation['login_calendar']['quiet_hours'])
        self.assertEqual([(e['start'], e['end']) for e in rotation['rooms'][0]['events']], [(0, 8), (8, 16)])
        replay = simulate({'rotation': rotation, 'days': 1, 'trials': 1})
        self.assertEqual([e['hour'] for e in replay['collection_events']], list(range(2, 25, 2)))

    def test_fiammetta_does_not_inherit_max_dorm_base_recovery(self):
        def team():
            return {'rooms': [worker('target')], 'metrics': {}}
        rotation = build_rotation(team(), team(), 8, schedule_mode='fixed',
                                  fiammetta={'enabled': True, 'active': True, 'target_operator_id': 'target'})
        result = simulate({'rotation': rotation, 'initial_morale': {'target': 0}, 'days': 1, 'trials': 1})
        swaps = [e['minute'] for e in result['morale']['events'] if e['type'] == 'morale_swap']
        # At 8h she inherits zero. At 16h she has recovered only 16, not 24.
        self.assertEqual(swaps, [480])
        self.assertEqual(result['morale']['fiammetta_recovery_per_hour'], 2)

class SpecialMoraleRegressionTests(unittest.TestCase):
    def test_gladiia_counts_working_and_resting_hunters_in_separate_branches(self):
        gladiia = 'char_474_glady'
        skadi = 'char_263_skadi'
        room = {'key': 'control', 'operators': [gladiia], 'details': [{'operator': '歌蕾蒂娅', 'skills': [
            {'icon': 'bskill_ctrl_cost_aegir', 'description': '每有1个深海猎人干员进驻在宿舍以外的设施，则自身心情每小时消耗+0.5；反之则自身心情每小时恢复+0.5，如果进驻在宿舍内的深海猎人干员为满心情，则额外+0.5'}]}],
            'base_state': {'working_operator_ids': [skadi]}}
        # Include Gladiia herself even when a planner's working IDs only list production rooms.
        self.assertEqual(morale_rates(room)[gladiia], 1.95)
        room['base_state'] = {'working_operator_ids': [gladiia], 'dormitory_morale': {skadi: 12}}
        self.assertEqual(morale_rates(room)[gladiia], .95)
        room['base_state']['dormitory_morale'][skadi] = 24
        self.assertEqual(morale_rates(room)[gladiia], .45)

    def test_mlynar_extra_tenth_only_applies_to_support_rooms(self):
        control = {'operators': ['m'], 'details': [{'operator': '玛恩纳', 'skills': [
            {'icon': 'bskill_ctrl_cost', 'description': '控制中枢内所有干员的心情每小时恢复+0.05'},
            {'icon': 'bskill_ctrl_lonely', 'description': '部分设施内处于工作状态的干员心情每小时恢复+0.1'}]}]}
        self.assertEqual(morale_rates(worker(), control)['a'], .9)
        self.assertEqual(morale_rates(worker(key='power'), control)['a'], .8)


if __name__ == '__main__':
    unittest.main()
