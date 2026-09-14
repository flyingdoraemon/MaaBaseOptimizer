import json
from pathlib import Path
import unittest
from maabase.scheduler import build_rotation, build_staggered_production_curve
from maabase.simulator import _schedules, _source, simulate
from maabase.state_model import BaseContext, catalog_mechanism_coverage
from maabase.model import evaluate_team, prepare_operators
from maabase.morale_runtime import compile_morale

CATALOG = json.loads((Path(__file__).parents[1] / 'data/catalog.json').read_text())


def room(name, op, multiplier):
    return {'room':name,'key':'gold','operators':[op],'names':[op],
            'multiplier':multiplier,'efficiency':(multiplier-1)*100,
            'details':[{'operator':op,'skills':[{'description':'自身心情每小时消耗-0.5'}]}]}


def plan(label, first):
    return {'rooms':[room('long',label+'1',first),room('equal',label+'2',1)],'metrics':{}}


class MultidayTests(unittest.TestCase):
    def test_36_hour_shift_and_independent_common_period(self):
        rotation=build_rotation(plan('a',2),plan('b',1),36,schedule_mode='staggered',collection_interval_hours=2,max_work_hours=36)
        self.assertEqual(rotation['room_work_hours']['long'],{'A':36,'B':12})
        self.assertEqual(rotation['room_work_hours']['equal'],{'A':36,'B':36})
        self.assertEqual(rotation['display_hours'],72)
        self.assertEqual(rotation['natural_cycle_hours'],144)
        event=next(e for e in rotation['rooms'][0]['events'] if e['start']==6)
        self.assertEqual((event['start'],event['end']),(6,42))
        self.assertTrue(all(6<=e['time']%24<24 for e in rotation['handover_events']))
        schedules,cycle=_schedules({'rotation':rotation})
        long=next(row for row in schedules if row['name']=='long')
        self.assertEqual(_source(long,80*60,cycle)[0]['operators'],['a1'])
        self.assertEqual(_source(long,128*60,cycle)[0]['operators'],['a1'])
        # Clipping the display at 72h must not change the repeated schedule.
        self.assertEqual(_source(long,224*60,cycle)[0]['operators'],['a1'])

    def test_training_room_present_in_only_one_team_is_retained(self):
        a,b=plan('a',2),plan('b',1)
        a['support_rooms']=[{'room':'training','key':'training','operators':['trainer'],'names':['trainer'],'details':[]}]
        rotation=build_rotation(a,b,36,schedule_mode='staggered',collection_interval_hours=2,max_work_hours=36)
        row=next(row for row in rotation['rooms'] if row['key']=='training')
        self.assertTrue(any(event['operators']==['trainer'] for event in row['events']))
        self.assertTrue(any(event['operators']==[] for event in row['events']))
        schedules,_=_schedules({'rotation':rotation})
        self.assertTrue(any(row['name']=='training' for row in schedules))

    def test_full_period_curves_normalize_daily_income_and_drones(self):
        rotation=build_rotation(plan('a',2),plan('b',1),36,schedule_mode='staggered',collection_interval_hours=2,max_work_hours=36)
        curve=build_staggered_production_curve(rotation,CATALOG['constants'],drone_target='gold',external_gold_per_day=0,gold_net_target_per_day=0)
        days=curve['hours']/24
        self.assertEqual(curve['hours'],144)
        # 1.75 + 1 factory multipliers, plus 240 drones/day at 1/24 gold each.
        self.assertAlmostEqual(curve['points'][-1]['cumulative']['gold_made_per_day']/days,65)
        self.assertEqual(curve['drone_summary']['drones_spent'],240)
        self.assertEqual(sum(item['drones_per_day'] for item in curve['drone_summary']['allocations']),240)


class AddedMechanismsTests(unittest.TestCase):
    def ops(self,*names,elite=2):
        return prepare_operators([{'id':next(oid for oid,op in CATALOG['operators'].items() if op['name']==name),'elite':elite,'level':90} for name in names],CATALOG)

    def test_all_unlock_versions_have_production_rules(self):
        audit=catalog_mechanism_coverage(CATALOG)
        self.assertGreaterEqual(audit['total_relevant'],337)
        self.assertEqual(audit['partial'],[])

    def test_totter_uses_actual_morale_and_conditional_capacity_once(self):
        ops=self.ops('铅踝');oid=ops[0]['id']
        values=[evaluate_team(ops,'gold',CATALOG,BaseContext(operator_morale={oid:mood})) for mood in (24,12,11.99,8)]
        self.assertEqual([v['efficiency'] for v in values],[30,15,25,20])
        self.assertEqual([v['output_capacity'] for v in values],[27,27,30,30])
        for partner,bonus in [('泡泡',6),('红云',12)]:
            team=self.ops('铅踝',partner)
            high=evaluate_team(team,'gold',CATALOG,BaseContext(operator_morale={oid:12}))
            low=evaluate_team(team,'gold',CATALOG,BaseContext(operator_morale={oid:11.99}))
            self.assertEqual(low['efficiency']-high['efficiency'],10+bonus)

    def test_totter_replay_changes_at_real_morale_thresholds(self):
        ops=self.ops('铅踝');oid=ops[0]['id'];candidate={'room':'factory','key':'gold',**evaluate_team(ops,'gold',CATALOG)}
        schedules=[{'name':'factory','spans':[(0,240,candidate)]}]
        compiled,report=compile_morale(schedules,240,240,120,{},CATALOG,initial={oid:14})
        spans=compiled[0]['spans']
        self.assertEqual([(round(start),round(end),r['efficiency'],r['output_capacity']) for start,end,r in spans],[(0,120,20,27),(120,240,25,30)])

    def test_phonor_requires_logos_in_training_assistant_slot(self):
        ops=self.ops('PhonoR-0',elite=0)
        off=evaluate_team(ops,'power',CATALOG,BaseContext())
        on=evaluate_team(ops,'power',CATALOG,BaseContext(training_operator_ids=['char_4133_logos']))
        wrong=evaluate_team(ops,'power',CATALOG,BaseContext(control_operator_ids=['char_4133_logos']))
        self.assertEqual(on['efficiency']-off['efficiency'],5)
        self.assertEqual(off['efficiency'],wrong['efficiency'])

    def test_training_handover_changes_live_power_bonus_independently(self):
        phonor=self.ops('PhonoR-0',elite=0)
        power={'room':'power','key':'power',**evaluate_team(phonor,'power',CATALOG)}
        training={'room':'training','key':'training','operators':['char_4133_logos'],
                  'names':['逻各斯'],'operator_profiles':[{'id':'char_4133_logos','elite':2,'level':90}]}
        schedules=[{'name':'power','spans':[(0,960,power)]},
                   {'name':'training','spans':[(0,480,training)]}]
        compiled,_=compile_morale(schedules,960,960,480,{'schedule_mode':'fixed'},CATALOG)
        self.assertEqual(sum(end-start for start,end,room in compiled[0]['spans'] if room['efficiency']==15),480)
        self.assertTrue(all(room['efficiency']==10 for start,end,room in compiled[0]['spans'] if start>=480))

    def test_early_promotion_trade_conditions(self):
        for name,partner in [('赫德雷','char_4087_ines'),('深巡','char_4145_ulpia'),('贝洛内','char_427_vigil')]:
            ops=self.ops(name,elite=0)
            off=evaluate_team(ops,'trade',CATALOG,BaseContext())
            on=evaluate_team(ops,'trade',CATALOG,BaseContext(working_operator_ids=[partner]))
            self.assertEqual(on['efficiency']-off['efficiency'],5,name)
        ops=self.ops('图耶','绮良',elite=0)
        for lines,expected in [(3,10),(4,25),(8,55)]:
            self.assertEqual(evaluate_team(ops,'trade',CATALOG,BaseContext(gold_lines=lines))['efficiency'],expected)
