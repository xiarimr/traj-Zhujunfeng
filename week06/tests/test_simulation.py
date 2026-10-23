import copy
from dataclasses import replace
import unittest
from pvsim import Settings, Road, Scenario
from pvsim.scenarios import corridor
from pvsim.simulation import simulate, validate
from pvsim.geometry import swept_contact, swept_separation, swept_wall_gap
from pvsim.policy import Control, ReciprocalPolicy


class SimulationTests(unittest.TestCase):
    def test_safe_threshold_and_no_contact(self):
        r = simulate(corridor(width=2.8), record=False)
        self.assertEqual(r["metrics"]["status"], "completed")
        self.assertEqual(r["metrics"]["collision_pairs"], 0)
        self.assertEqual(r["metrics"]["boundary_violations"], 0)
        self.assertEqual(r["metrics"]["pedestrians_passed"], 3)
        self.assertEqual(r["metrics"]["vehicles_passed"], 2)
        self.assertGreaterEqual(r["metrics"]["min_pair_gap_m"], 0.2 - 1e-5)
        for a in r["metrics"]["agents"]:
            self.assertIsNotNone(a["exit_time_s"])

    def test_physical_fits_but_safety_does_not(self):
        r = simulate(corridor(width=2.6), record=False)
        self.assertTrue(r["feasibility"]["physical_cross_section_fits"])
        self.assertFalse(r["feasibility"]["safe_cross_section_fits"])
        self.assertEqual(r["metrics"]["status"], "waiting_clearance")
        self.assertIsNone(r["metrics"]["completion_time_s"])
        self.assertEqual(r["metrics"]["collision_pairs"], 0)

    def test_fixed_centered_pose_and_small_vehicle_shift(self):
        stopped = simulate(corridor(width=2.9, centered_vehicle=True), record=False)
        passed = simulate(corridor(width=2.9, centered_vehicle=True, vehicle_lateral_speed=.2), record=False)
        self.assertEqual(stopped["metrics"]["status"], "waiting_alignment")
        self.assertEqual(passed["metrics"]["status"], "completed")

    def test_narrowing_waits_and_wider_narrowing_passes(self):
        self.assertEqual(simulate(corridor(width=2.6, bottleneck=True), record=False)["metrics"]["status"], "waiting_clearance")
        self.assertEqual(simulate(corridor(width=3.2, bottleneck=True), record=False)["metrics"]["status"], "completed")

    def test_type_labels_and_mass_do_not_change_motion(self):
        base = corridor(width=3.0, pedestrians=1, vehicles=1)
        changed = copy.deepcopy(base)
        for a in changed.agents:
            a.spec = replace(a.spec, kind="other", mass=a.spec.mass * 100)
        self.assertEqual(simulate(base)["trace"], simulate(changed)["trace"])

    def test_order_independence_synchronous_updates(self):
        base = corridor()
        reversed_scenario = copy.deepcopy(base)
        reversed_scenario.agents.reverse()
        r1, r2 = simulate(base), simulate(reversed_scenario)
        for frame1, frame2 in zip(r1["trace"], r2["trace"]):
            self.assertEqual(sorted(frame1["agents"], key=lambda a: a["id"]),
                             sorted(frame2["agents"], key=lambda a: a["id"]))

    def test_limits_and_fixed_vehicle_lane(self):
        scenario = corridor(settings=Settings(record_every=1))
        result = simulate(scenario)
        specs = {a.spec.id: a.spec for a in scenario.agents}
        for previous, current in zip(result["trace"], result["trace"][1:]):
            dt = current["time"] - previous["time"]
            for a, b in zip(previous["agents"], current["agents"]):
                p = specs[a["id"]]
                self.assertLessEqual((b["speed"] - a["speed"]) / dt, p.max_accel + 1e-4)
                self.assertGreaterEqual((b["speed"] - a["speed"]) / dt, -p.max_brake - 1e-4)
                self.assertLessEqual(abs(b["vy"] - a["vy"]) / dt, p.lateral_accel + 1e-4)
                if p.lateral_speed == 0:
                    self.assertEqual(a["y"], b["y"])

    def test_swept_detection_catches_tunneling(self):
        a, b = corridor(pedestrians=1, vehicles=1).agents
        a0, a1 = replace(a, x=10, y=0), replace(a, x=30, y=0)
        b0, b1 = replace(b, x=30, y=0), replace(b, x=10, y=0)
        self.assertIsNotNone(swept_contact(a0, a1, b0, b1))
        self.assertEqual(swept_separation(a0, a1, b0, b1), 0)
        far = replace(b0, y=10)
        self.assertIsNone(swept_contact(a0, a1, far, far))

    def test_swept_wall_checks_interior_bottleneck(self):
        a = corridor(pedestrians=1, vehicles=1).agents[0]
        road = Road(60, ((0, 5), (20, 5), (25, 2), (30, 5), (60, 5)))
        start, end = replace(a, x=10, y=1), replace(a, x=40, y=1)
        self.assertLess(swept_wall_gap(road, start, end), 0)

    def test_unsafe_initial_speed_is_not_hidden_by_position_projection(self):
        r = simulate(corridor(width=2.6, pedestrians=1, vehicles=1,
                              vehicle_speed=12, initial_gap=5, speed_jitter=0))
        self.assertEqual(r["metrics"]["status"], "collision")
        self.assertGreater(r["metrics"]["speed_ceiling_unreachable_agent_steps"], 0)

    def test_invalid_overlap_rejected(self):
        bad = corridor(pedestrians=1, vehicles=1)
        bad.agents[1].x = bad.agents[0].x
        with self.assertRaises(ValueError):
            validate(bad)

    def test_timeout_is_not_completion_or_stall(self):
        r = simulate(corridor(settings=Settings(max_time=.1)), record=False)
        self.assertEqual(r["metrics"]["status"], "timeout")
        self.assertIsNone(r["metrics"]["completion_time_s"])

    def test_repeatable_and_no_mutation(self):
        case = corridor(seed=42)
        original = copy.deepcopy(case)
        self.assertEqual(simulate(case)["metrics"], simulate(case)["metrics"])
        self.assertEqual(case, original)

    def test_dt_convergence(self):
        times = [simulate(corridor(width=2.9, settings=Settings(dt=dt)), record=False)["metrics"]["completion_time_s"]
                 for dt in (.1, .05, .025)]
        self.assertLess(max(times) - min(times), .7)


if __name__ == "__main__":
    unittest.main()
