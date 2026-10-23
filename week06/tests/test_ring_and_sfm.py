import copy
from dataclasses import replace
import unittest
from pvsim.scenarios import ring, corridor
from pvsim.simulation import simulate, validate
from pvsim.domain import Settings
from pvsim.topology import pair_images, neighbor_images
from pvsim.geometry import swept_contact
from pvsim.social_force import SocialForcePolicy, GuidedSocialForcePolicy, SocialForceParameters


class RingAndSFMTests(unittest.TestCase):
    def test_ring_repeated_encounters_and_no_exits(self):
        r = simulate(ring(duration=120), record=False)
        self.assertEqual(r["metrics"]["status"], "sustained")
        self.assertGreater(r["metrics"]["pair_passages"], 6)
        self.assertGreater(r["metrics"]["total_laps"], 0)
        self.assertIsNone(r["metrics"]["completion_time_s"])
        self.assertEqual(r["metrics"]["pedestrians_passed"], 0)
        self.assertEqual(r["metrics"]["collision_pairs"], 0)

    def test_seam_neighbor_and_continuous_collision(self):
        case = ring(pedestrians=1, vehicles=1)
        a, b = case.agents
        a, b = replace(a, x=75, y=0), replace(b, x=5, y=0)
        bi = neighbor_images(a, [a, b], case.road)[0]
        self.assertAlmostEqual(bi.x, 85)
        an, bn = replace(a, x=85), replace(b, x=-5)
        self.assertTrue(any(swept_contact(a, an, i, j) is not None for i, j in pair_images(a, b, bn, case.road)))

    def test_seam_initial_overlap_rejected(self):
        case = ring(pedestrians=1, vehicles=1)
        case.agents[0].x, case.agents[1].x = 79.5, .5
        with self.assertRaises(ValueError):
            validate(case)

    def test_sfm_is_type_and_mass_invariant(self):
        case = corridor(pedestrians=1, vehicles=1, settings=Settings(max_time=3))
        other = copy.deepcopy(case)
        for a in other.agents:
            a.spec = replace(a.spec, kind="unlabeled", mass=99999)
        self.assertEqual(simulate(case, SocialForcePolicy())["trace"], simulate(other, SocialForcePolicy())["trace"])

    def test_hybrid_releases_resolved_conflict(self):
        result = simulate(corridor(width=3.2), GuidedSocialForcePolicy(), record=False)
        self.assertEqual(result["metrics"]["status"], "completed")
        self.assertEqual(result["metrics"]["collision_pairs"], 0)

    def test_short_range_sfm_failure_is_reported(self):
        result = simulate(corridor(width=3.2), SocialForcePolicy(SocialForceParameters(A=4, B=.8)), record=False)
        self.assertIn(result["metrics"]["status"], ("collision", "boundary_violation"))


if __name__ == "__main__":
    unittest.main()
