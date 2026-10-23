"""Circle crossing: alternating vehicles/pedestrians moving to antipodal goals.

The corridor controllers are reused in each agent's fixed heading frame.
Other oriented footprints are conservatively projected into that frame.
No circular wall, signal, priority or collision projection is introduced.
"""
from dataclasses import dataclass, asdict, replace
from itertools import combinations
import copy
import math
import random
from .domain import AgentSpec, AgentState, Settings, Road
from .policy import ReciprocalPolicy, Control, safe_speed, clip
from .radial_geometry import basis, dot, support, projected_gap, swept_obb_contact, swept_gap_bound


@dataclass
class RadialScenario:
    agents: list
    headings: dict
    goals: dict
    settings: Settings
    radius: float
    passing_offset: float
    goal_tolerance: float
    seed: int
    metadata: dict
    name: str = 'circle_crossing'


def circle_crossing(radius=12.0, pairs=4, vehicle_lateral_speed=0.0, vehicle_speed=3.0,
                    pedestrian_speed=1.3, passing_offset=2.5, goal_tolerance=0.35,
                    duration=120.0, seed=0, speed_jitter=0.08, rotation=0.0, settings=None):
    if radius <= 0 or not isinstance(pairs, int) or pairs < 1 or passing_offset <= 0 or goal_tolerance <= 0:
        raise ValueError('Invalid circle-crossing geometry')
    c = replace(settings or Settings(), max_time=duration)
    rng = random.Random(seed)
    agents, headings, goals = [], {}, {}
    for i in range(2 * pairs):
        theta = rotation + math.pi * i / pairs
        vehicle = i % 2 == 0
        ident = ('V' if vehicle else 'P') + str(i // 2 + 1)
        speed = (vehicle_speed if vehicle else pedestrian_speed) * (1+rng.uniform(-speed_jitter,speed_jitter))
        spec = AgentSpec(ident, 'vehicle' if vehicle else 'pedestrian',
                         4.5 if vehicle else 0.5, 1.8 if vehicle else 0.6, speed,
                         1.5 if vehicle else 1.2, 3.0 if vehicle else 2.0,
                         vehicle_lateral_speed if vehicle else 0.7, 0.4 if vehicle else 1.0,
                         1, 1, 0.0, 1500 if vehicle else 70, encounter_speed=1.0)
        x, y = radius*math.cos(theta), radius*math.sin(theta)
        agents.append(AgentState(spec,x,y,speed))
        headings[ident], goals[ident] = theta+math.pi, (-x,-y)
    return RadialScenario(agents,headings,goals,c,radius,passing_offset,goal_tolerance,seed,
                          {'type':'circle_crossing','pairs':pairs,'vehicle_lateral_speed':vehicle_lateral_speed,
                           'vehicle_speed':vehicle_speed,'speed_jitter':speed_jitter,'rotation':rotation,
                           'goal':'antipodal_point','orientation':'fixed_initial_inward_heading',
                           'interaction':'original_policy_in_agent_local_frame','walls':False})


def world_velocity(a, headings):
    e,n = basis(headings[a.spec.id])
    return (a.speed*e[0]+a.vy*n[0], a.speed*e[1]+a.vy*n[1])


def local_control(a, agents, scene, policy, settings):
    gx,gy = scene.goals[a.spec.id]
    if math.hypot(a.x-gx,a.y-gy) <= scene.goal_tolerance:
        return Control(max(0.0,a.speed-a.spec.max_brake*settings.dt),
                       a.vy+clip(-a.vy,-a.spec.lateral_accel*settings.dt,a.spec.lateral_accel*settings.dt),
                       'BRAKE',False)
    e,n = basis(scene.headings[a.spec.id])
    local = []
    for other in agents:
        pos = (other.x,other.y)
        velocity = world_velocity(other,scene.headings)
        other_e,_ = basis(scene.headings[other.spec.id])
        forward = dot(e,other_e)
        direction = 1 if forward > 1e-8 else -1
        spec = replace(other.spec,
                       length=2*support(other.spec,scene.headings[other.spec.id],e),
                       width=2*support(other.spec,scene.headings[other.spec.id],n),direction=direction)
        if other.spec.id == a.spec.id:
            spec = replace(a.spec,direction=1,side=1,home_y=0.0)
        # Arrived bodies remain present as stationary obstacles.
        local.append(replace(other,spec=spec,x=dot(pos,e),y=dot(pos,n),
                             speed=abs(dot(velocity,e)),vy=dot(velocity,n),done=False))
    own = next(x for x in local if x.spec.id == a.spec.id)
    # This width supplies a lateral target band, not a physical road boundary.
    width = 2*scene.passing_offset+a.spec.width+2*settings.wall_clearance
    road = Road(4*scene.radius,((0.0,width),(4*scene.radius,width)),physical_walls=False)
    result = policy.control(own,local,road,settings)
    remaining = dot(scene.goals[a.spec.id],e)-own.x
    cap = safe_speed(max(0.0,remaining-scene.goal_tolerance/3),a.spec.max_brake,settings.dt)
    low = max(0.0,a.speed-a.spec.max_brake*settings.dt)
    speed = clip(min(result.speed,cap),low,a.speed+a.spec.max_accel*settings.dt)
    return replace(result,speed=speed,braking_infeasible=result.braking_infeasible or cap < low-1e-9)


def radial_snapshot(t, agents):
    return {'time':round(t,6),'agents':[{'id':a.spec.id,'x':round(a.x,6),'y':round(a.y,6),
            'speed':round(a.speed,6),'vy':round(a.vy,6),'mode':a.mode,'done':a.done} for a in agents]}


def validate_circle(scene):
    ids = [a.spec.id for a in scene.agents]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate ids')
    for a in scene.agents:
        if not all(math.isfinite(v) for v in (a.x,a.y,a.speed,a.vy,scene.headings[a.spec.id],*scene.goals[a.spec.id])):
            raise ValueError('Nonfinite initial state')
    for a,b in combinations(scene.agents,2):
        if swept_obb_contact(a,a,b,b,scene.headings[a.spec.id],scene.headings[b.spec.id]) is not None:
            raise ValueError('Initial oriented footprints overlap: '+a.spec.id+'/'+b.spec.id)


def simulate_circle(scene, policy=None, record=True):
    validate_circle(scene)
    policy = policy or ReciprocalPolicy()
    agents = copy.deepcopy(scene.agents)
    c = scene.settings
    trace = [radial_snapshot(0,agents)] if record else []
    events, collisions = [], set()
    t,quiet,min_gap,infeasible = 0.0,0.0,float('inf'),0
    min_radius = {a.spec.id:math.hypot(a.x,a.y) for a in agents}
    status = 'timeout'
    for step in range(1,math.ceil(c.max_time/c.dt)+1):
        dt = min(c.dt,c.max_time-t)
        controls = {a.spec.id:local_control(a,agents,scene,policy,replace(c,dt=dt)) for a in agents if not a.done}
        following = []
        for a in agents:
            if a.done:
                following.append(a)
                continue
            u = controls[a.spec.id]
            e,n = basis(scene.headings[a.spec.id])
            b = replace(a,x=a.x+dt*(u.speed*e[0]+u.vy*n[0]),y=a.y+dt*(u.speed*e[1]+u.vy*n[1]),
                        speed=u.speed,vy=u.vy,mode=u.mode,committed=u.committed)
            b.path_length += math.hypot(b.x-a.x,b.y-a.y)
            if math.hypot(b.speed,b.vy)<c.stop_speed: b.waiting_time += dt
            b.peak_decel = max(a.peak_decel,(a.speed-b.speed)/dt)
            min_radius[a.spec.id] = min(min_radius[a.spec.id],math.hypot(b.x,b.y))
            infeasible += int(u.braking_infeasible)
            following.append(b)
        for i,j in combinations(range(len(agents)),2):
            a,b,an,bn = agents[i],agents[j],following[i],following[j]
            ha,hb = scene.headings[a.spec.id],scene.headings[b.spec.id]
            contact = swept_obb_contact(a,an,b,bn,ha,hb)
            min_gap = min(min_gap,swept_gap_bound(a,an,b,bn,ha,hb))
            if contact is not None:
                pair = tuple(sorted((a.spec.id,b.spec.id)))
                collisions.add(pair)
                events.append({'time':t+contact*dt,'type':'collision','agents':pair})
        t += dt
        agents = following
        for a in agents:
            if a.done: continue
            gx,gy = scene.goals[a.spec.id]
            if math.hypot(a.x-gx,a.y-gy)<=scene.goal_tolerance and a.speed==0 and a.vy==0:
                a.done,a.mode,a.exit_time = True,'DONE',t
                # No position snapping and no instantaneous velocity reset.
                events.append({'time':t,'type':'goal_arrival','agent':a.spec.id})
        if record and step % c.record_every == 0: trace.append(radial_snapshot(t,agents))
        if collisions:
            status='collision';break
        if all(a.done for a in agents):
            status='completed';break
        live=[a for a in agents if not a.done]
        quiet = quiet+dt if all(math.hypot(a.speed,a.vy)<c.stop_speed for a in live) else 0.0
        if quiet >= c.stall_time:
            status='deadlock_policy'
            events.append({'time':t,'type':'stall','classification':status})
            break
    if record and (not trace or abs(trace[-1]['time']-t)>1e-7): trace.append(radial_snapshot(t,agents))
    passed = {kind:sum(a.done and a.spec.kind==kind for a in agents) for kind in ('pedestrian','vehicle')}
    metrics={'status':status,'observation_time_s':t,'completion_time_s':t if status=='completed' else None,
             'pedestrians_passed':passed['pedestrian'],'vehicles_passed':passed['vehicle'],
             'pedestrians_total':sum(a.spec.kind=='pedestrian' for a in agents),
             'vehicles_total':sum(a.spec.kind=='vehicle' for a in agents),
             'collision_pairs':len(collisions),'boundary_violations':0,'pair_passages':None,
             'arrived_total':sum(a.done for a in agents),'total_agent_waiting_s':sum(a.waiting_time for a in agents),
             'min_pair_gap_m':min_gap,'gap_definition':'conservative whole-step SAT lower bound; not exact Euclidean distance',
             'min_wall_gap_m':None,'safety_margins_satisfied':not collisions and min_gap>=c.lateral_clearance-c.clearance_tolerance,
             'speed_ceiling_unreachable_agent_steps':infeasible,
             'closest_radius_by_agent_m':min_radius,
             'agents':[{'id':a.spec.id,'arrival_time_s':a.exit_time,'goal_error_m':math.hypot(a.x-scene.goals[a.spec.id][0],a.y-scene.goals[a.spec.id][1]),
                        'waiting_time_s':a.waiting_time,'path_length_m':a.path_length,'peak_decel_m_s2':a.peak_decel} for a in agents]}
    return {'policy':{'name':getattr(policy,'name',type(policy).__name__),
                      'parameters':asdict(policy.parameters) if hasattr(policy,'parameters') else {}},
            'scenario':{'name':scene.name,'seed':scene.seed,'settings':asdict(c),'agents':[asdict(a.spec) for a in scene.agents],
                        'initial_states':[asdict(a) for a in scene.agents],'metadata':scene.metadata,
                        'radius':scene.radius,'headings':scene.headings,'goals':scene.goals,
                        'passing_offset':scene.passing_offset,'goal_tolerance':scene.goal_tolerance},
            'metrics':metrics,'events':events,'trace':trace}
