import copy
from dataclasses import replace
import math
import unittest
from pvsim.domain import Settings
from pvsim.radial import circle_crossing, local_control
from pvsim.radial_geometry import swept_obb_contact, projected_gap, basis, dot
from pvsim.policy import ReciprocalPolicy
from pvsim.simulation import simulate
from pvsim.scenarios import load_scenario


class CircleCrossingTests(unittest.TestCase):
    def test_alternating_inward_start_and_antipodal_goals(self):
        scene=circle_crossing(speed_jitter=0)
        self.assertEqual([a.spec.kind for a in scene.agents],['vehicle','pedestrian']*4)
        for a in scene.agents:
            self.assertAlmostEqual(math.hypot(a.x,a.y),12)
            self.assertAlmostEqual(dot((a.x,a.y),basis(scene.headings[a.spec.id])[0]),-12)
            self.assertEqual(scene.goals[a.spec.id],(-a.x,-a.y))

    def test_rotation_covariance(self):
        angle=.371
        a=simulate(circle_crossing(duration=2,rotation=0,speed_jitter=0))
        b=simulate(circle_crossing(duration=2,rotation=angle,speed_jitter=0))
        for fa,fb in zip(a['trace'],b['trace']):
            for x,y in zip(fa['agents'],fb['agents']):
                self.assertAlmostEqual(y['x'],x['x']*math.cos(angle)-x['y']*math.sin(angle),places=5)
                self.assertAlmostEqual(y['y'],x['x']*math.sin(angle)+x['y']*math.cos(angle),places=5)
                self.assertAlmostEqual(x['speed'],y['speed'],places=5)

    def test_type_and_mass_do_not_change_policy(self):
        a=circle_crossing(duration=2)
        b=copy.deepcopy(a)
        for agent in b.agents:agent.spec=replace(agent.spec,kind='unknown',mass=12345)
        self.assertEqual(simulate(a)['trace'],simulate(b)['trace'])

    def test_one_pair_arrives_without_teleporting(self):
        scene=circle_crossing(pairs=1,settings=Settings(record_every=1))
        result=simulate(scene)
        self.assertEqual(result['metrics']['status'],'completed')
        self.assertEqual(result['metrics']['arrived_total'],2)
        self.assertEqual(result['metrics']['collision_pairs'],0)
        previous=result['trace'][0]
        for frame in result['trace'][1:]:
            dt=frame['time']-previous['time']
            for old,new,spec in zip(previous['agents'],frame['agents'],scene.agents):
                self.assertLessEqual(new['speed']-old['speed'],spec.spec.max_accel*dt+2e-6)
                self.assertLessEqual(old['speed']-new['speed'],spec.spec.max_brake*dt+2e-6)
                self.assertLessEqual(abs(new['vy']-old['vy']),spec.spec.lateral_accel*dt+2e-6)
                e,n=basis(scene.headings[new['id']])
                self.assertAlmostEqual(new['x']-old['x'],(new['speed']*e[0]+new['vy']*n[0])*dt,places=5)
                self.assertAlmostEqual(new['y']-old['y'],(new['speed']*e[1]+new['vy']*n[1])*dt,places=5)
                if new['done']:self.assertEqual((new['speed'],new['vy']),(0,0))
            previous=frame

    def test_fixed_vehicle_has_no_lateral_drift(self):
        scene=circle_crossing(duration=3)
        result=simulate(scene)
        for frame in result['trace']:
            for a in frame['agents']:
                if a['id'].startswith('V'):
                    self.assertAlmostEqual(dot((a['x'],a['y']),basis(scene.headings[a['id']])[1]),0,places=5)

    def test_crossing_obb_collision_between_nonoverlapping_endpoints(self):
        scene=circle_crossing(pairs=1)
        a,b=scene.agents
        a,b=replace(a,x=-6,y=0),replace(b,x=0,y=-6)
        an,bn=replace(a,x=6),replace(b,y=6)
        self.assertGreater(projected_gap(a,b,0,math.pi/2),0)
        self.assertGreater(projected_gap(an,bn,0,math.pi/2),0)
        self.assertIsNotNone(swept_obb_contact(a,an,b,bn,0,math.pi/2))

    def test_arrived_body_remains_an_obstacle(self):
        scene=circle_crossing(pairs=1,speed_jitter=0)
        a,b=scene.agents
        # Put a stopped, already-arrived body directly in front of a vehicle.
        a=replace(a,x=5,y=0,speed=1)
        b=replace(b,x=1,y=0,speed=0,vy=0,done=True)
        scene.agents=[a,b]
        u=local_control(a,scene.agents,scene,ReciprocalPolicy(),scene.settings)
        free=local_control(a,[a],scene,ReciprocalPolicy(),scene.settings)
        self.assertLess(u.speed,free.speed)

    def test_dt_convergence_single_pair(self):
        results=[simulate(circle_crossing(pairs=1,settings=Settings(dt=dt)),record=False)['metrics'] for dt in (.05,.025)]
        self.assertEqual([r['status'] for r in results],['completed','completed'])
        self.assertLess(abs(results[0]['completion_time_s']-results[1]['completion_time_s']),.5)


if __name__=='__main__':unittest.main()
