from __future__ import annotations

import json
import unittest
from pathlib import Path

from maabase.importers import parse_roster
from maabase.mechanics import mechanic_is_partial, resolve_trade_mechanics, warmed_order_probabilities
from maabase.model import _orundum_economics, _trade_economics, active_skills, evaluate_team, prepare_operators
from maabase.morale import analyze_morale
from maabase.state_model import BaseContext, _average_empty_order_slots
from maabase.optimizer import _metrics, optimize
from maabase.scheduler import build_rotation


ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))

    def test_nested_maa_import(self):
        payload = {"details": {"own_opers": [{"id": "char_002_amiya", "name": "阿米娅", "own": True, "elite": 2, "level": 50}]}}
        roster, warnings = parse_roster(payload, self.catalog)
        self.assertEqual(roster[0]["name"], "阿米娅")
        self.assertEqual(roster[0]["elite"], 2)
        self.assertFalse(warnings)

    def test_skill_upgrade_uses_highest_unlocked_level(self):
        skills_e0 = active_skills({"id": "char_241_panda", "elite": 0, "level": 1}, self.catalog)
        skills_e2 = active_skills({"id": "char_241_panda", "elite": 2, "level": 1}, self.catalog)
        self.assertTrue(any("30%" in x["description"] for x in skills_e0))
        self.assertTrue(any("35%" in x["description"] for x in skills_e2))

    def test_global_schedule_has_no_duplicate_operator(self):
        roster = [
            {"id": op_id, "name": op["name"], "elite": 2, "level": 90, "potential": 1}
            for op_id, op in self.catalog["operators"].items()
        ]
        result = optimize({"operators": roster, "exp_factories": 1, "drone_target": "trade", "candidate_limit": 90}, self.catalog, include_frontier=False)
        assigned = [op for room in result["rooms"] for op in room["operators"]]
        self.assertEqual(len(assigned), 21)
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertEqual(len([x for x in result["rooms"] if x["key"] == "gold"]), 3)

    def test_proviso_order_economics_match_public_expectation(self):
        team = [
            {"icons": {"bskill_tra_law", "bskill_tra_against2"}},
            {"icons": set()},
            {"icons": set()},
        ]
        trade = _trade_economics(team, 0.0)
        self.assertAlmostEqual(trade["expected_lmd"], 2250.0)
        self.assertAlmostEqual(trade["expected_gold"], 4.5)
        self.assertAlmostEqual(trade["expected_minutes"], 203.4)
        self.assertAlmostEqual(trade["lmd_per_day"] / 1.03, 15929.20354, places=4)
        self.assertAlmostEqual(trade["gold_per_day"] / 1.03, 31.858407, places=4)

    def test_shamare_proviso_tequila_special_order_priority(self):
        team = [
            {"icons": {"bskill_tra_vodfox", "bskill_tra_wt&cost1"}},
            {"icons": {"bskill_tra_law", "bskill_tra_against2"}},
            {"icons": {"bskill_tra_long2"}},
        ]
        trade = _trade_economics(team, 90.0)
        # 2/3-Gold branches become breach orders, so Tequila only affects the
        # original 4-Gold branch: 15%*2000 + 30%*2500 + 55%*2500.
        self.assertAlmostEqual(trade["expected_lmd"], 2425.0)
        self.assertAlmostEqual(trade["expected_gold"], 4.3)
        self.assertAlmostEqual(trade["expected_minutes"], 236.4)
        self.assertAlmostEqual(trade["lmd_per_day"] / 1.93, 14771.573604, places=4)

    def test_rules_are_mechanic_level_and_partial_state_is_visible(self):
        state = resolve_trade_mechanics({"bskill_tra_against2", "bskill_tra_long2"})
        self.assertEqual(state.breach_extra_gold, 2)
        self.assertEqual(state.normal_large_order_lmd, 500)
        self.assertTrue(mechanic_is_partial({"icon": "other", "description": "每有1个木天蓼，生产力+1%"}))

    def test_max_dorm_uses_bed_hours_and_allows_two_teams(self):
        rooms = [
            {"operators": [f"op-{i}" for i in range(3)], "details": [
                {"operator": f"op-{i}", "skills": []} for i in range(3)
            ]}
            for _ in range(7)
        ]
        audit = analyze_morale(rooms, [], self.catalog, 8)
        self.assertEqual(audit["active_slots"], 29)
        self.assertTrue(audit["two_team_feasible"])
        self.assertEqual(audit["recommended_rotation_teams"], 2)
        self.assertEqual(audit["minimum_distinct_operators"], 58)

    def test_order_quality_uses_shift_average_warmup(self):
        probabilities, label = warmed_order_probabilities(["bskill_tra_wt&cost1"], 8)
        self.assertAlmostEqual(probabilities[0], 0.178125)
        self.assertAlmostEqual(probabilities[1], 0.3375)
        self.assertAlmostEqual(probabilities[2], 0.484375)
        self.assertIn("线性暖机", label)

    def test_fang_hourly_skill_is_integrated_by_stage(self):
        fang = prepare_operators([{"id": "char_123_fang", "elite": 1, "level": 1}], self.catalog)
        result = evaluate_team(fang, "gold", self.catalog, BaseContext(shift_hours=8))
        self.assertAlmostEqual(result["efficiency"], 23.125)
        profile = result["time_profiles"][0]
        self.assertEqual(profile["phases"][0]["value_percent"], 20)
        self.assertEqual(profile["phases"][-1]["value_percent"], 25)

    def test_orundum_order_has_fixed_two_shard_exchange(self):
        result = _orundum_economics([{"icons": set()}, {"icons": set()}, {"icons": set()}], 0)
        self.assertAlmostEqual(result["orundum_per_day"], 247.2)
        self.assertAlmostEqual(result["shards_per_day"], 24.72)

    def test_two_team_rotation_alternates_and_recovers(self):
        def team(operator_id, name):
            room = {"key": "power", "room": "发电站 1", "operators": [operator_id], "names": [name],
                    "details": [{"operator": name, "skills": []}], "efficiency": 0, "time_profiles": []}
            return {"rooms": [room], "support_rooms": [], "metrics": {"lmd_per_day": 0, "exp_per_day": 0,
                    "gold_net_per_day": 0, "gold_inventory": 0}}
        rotation = build_rotation(team("a", "A干员"), team("b", "B干员"), 8)
        self.assertEqual(rotation["pattern"], ["A", "B", "A", "B", "A", "B"])
        self.assertTrue(rotation["morale"]["feasible"])
        self.assertEqual({row["id"] for row in rotation["operators"]}, {"a", "b"})

    def test_catnip_formula_types_and_control_speed_are_real_speed(self):
        raw = [
            {"id": "char_4077_palico", "name": "泰拉大陆调查团", "elite": 0, "level": 30},
            {"id": "char_253_greyy", "name": "格雷伊", "elite": 0, "level": 1},
            {"id": "char_277_sqrrel", "name": "阿消", "elite": 0, "level": 1},
        ]
        team = prepare_operators(raw, self.catalog)
        context = BaseContext(catnip=12, control_trade_speed=7, formula_types=2)
        result = evaluate_team(team, "trade", self.catalog, context)
        # Terra Research Commission: 5% direct + 12*3%; control center +7%.
        self.assertAlmostEqual(result["efficiency"], 48.0)
        catnip = next(x for x in result["context_effects"] if x["state"] == "catnip")
        self.assertEqual(catnip["available"], 12)
        self.assertEqual(catnip["contribution_percent"], 36)

    def test_external_gold_is_a_separate_inventory_flow(self):
        selected = {
            "trade": [{"multiplier": 1.0, "trade": {"lmd_per_day": 15000, "gold_per_day": 30}, "names": ["测试贸易站"]}],
            "gold": [], "exp": [], "power": [],
        }
        metrics = _metrics(selected, self.catalog, "none", external_gold_per_day=5, gold_inventory=100)
        self.assertEqual(metrics["gold_production_net_per_day"], -30)
        self.assertEqual(metrics["gold_net_per_day"], -25)
        self.assertEqual(metrics["gold_inventory_days"], 4)

    def test_power_station_speed_changes_drone_multiplier(self):
        team = prepare_operators(
            [{"id": "char_253_greyy", "name": "格雷伊", "elite": 0, "level": 1}],
            self.catalog,
        )
        result = evaluate_team(team, "power", self.catalog, BaseContext())
        self.assertAlmostEqual(result["efficiency"], 20.0)
        self.assertAlmostEqual(result["multiplier"], 1.21)

    def test_jaye_queue_expectation_responds_to_collection_interval(self):
        frequent = _average_empty_order_slots(14, 72.0, 4.0)
        normal = _average_empty_order_slots(14, 72.0, 8.0)
        rare = _average_empty_order_slots(14, 72.0, 24.0)
        self.assertGreater(frequent, normal)
        self.assertGreater(normal, rare)
        self.assertGreaterEqual(rare, 0.0)


if __name__ == "__main__":
    unittest.main()
