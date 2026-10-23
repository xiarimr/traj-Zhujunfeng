"""Matched-seed circle-crossing experiments, independent of corridor scans."""
from pathlib import Path
from collections import defaultdict, Counter
import json
from .radial import circle_crossing
from .simulation import simulate
from .social_force import make_policy
from .export import save_result, save_replay, save_homepage
from .experiments import write_csv, mean, wilson


def designs():
    return [
        ('baseline','4人4车 · 半径12 m · 车辆不侧移',{}),
        ('mobile','4人4车 · 车辆侧移上限0.2 m/s',{'vehicle_lateral_speed':.2}),
        ('one_pair','1人1车 · 对向穿越',{'pairs':1}),
        ('two_pairs','2人2车 · 十字汇聚',{'pairs':2}),
        ('dense','6人6车 · 密集汇聚',{'pairs':6}),
        ('radius_8','4人4车 · 初始半径8 m',{'radius':8}),
        ('radius_16','4人4车 · 初始半径16 m',{'radius':16}),
        ('slow_vehicle','4人4车 · 车速基值1.5 m/s',{'vehicle_speed':1.5}),
    ]


def run_radial(directory, seeds=5):
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    rows,replay=[],[]
    with (out/'runs.jsonl').open('w',encoding='utf-8') as log:
        for slug,label,params in designs():
            for seed in range(seeds):
                scene=circle_crossing(seed=seed,**params)
                for policy in ('reciprocal','social_force','sfm_guided'):
                    result=simulate(scene,make_policy(policy),record=seed==0)
                    m=result['metrics']
                    row={'case':slug,'label':label,'seed':seed,'policy':policy,'radius_m':scene.radius,
                         'pairs':scene.metadata['pairs'],'vehicle_lateral_speed_m_s':scene.metadata['vehicle_lateral_speed'],
                         'vehicle_speed_m_s':scene.metadata['vehicle_speed'],
                         **{key:m[key] for key in ('status','observation_time_s','completion_time_s','arrived_total',
                            'pedestrians_passed','vehicles_passed','collision_pairs','min_pair_gap_m',
                            'total_agent_waiting_s','safety_margins_satisfied')}}
                    rows.append(row)
                    log.write(json.dumps({'design':{'case':slug,'params':params},'result':dict(result,trace=[])},ensure_ascii=False)+'\n')
                    if seed==0:
                        save_result(result,out/'trajectories'/(slug+'_'+policy))
                        replay.append((label+' · '+policy,result))
            print(f'circle crossing {slug}: {seeds} seeds x 3 policies',flush=True)
    groups=defaultdict(list)
    for row in rows:groups[(row['case'],row['policy'])].append(row)
    summary=[]
    for (case,policy),rs in groups.items():
        successes=sum(r['status']=='completed' for r in rs)
        lo,hi=wilson(successes,len(rs))
        summary.append({'case':case,'label':rs[0]['label'],'policy':policy,'runs':len(rs),
                        'completion_rate':successes/len(rs),'wilson_low':lo,'wilson_high':hi,
                        'completion_mean_s':mean([r['completion_time_s'] for r in rs if r['completion_time_s'] is not None]),
                        'mean_arrived':mean([r['arrived_total'] for r in rs]),
                        'collision_runs':sum(r['collision_pairs']>0 for r in rs),
                        'mean_waiting_s':mean([r['total_agent_waiting_s'] for r in rs]),
                        'min_gap_lower_bound_m':min(r['min_pair_gap_m'] for r in rs),
                        'status_counts':json.dumps(dict(Counter(r['status'] for r in rs)),ensure_ascii=False)})
    write_csv(out/'runs.csv',rows);write_csv(out/'summary.csv',summary)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    save_replay(replay,out/'replay.html')
    if out.resolve()==Path('results/circle_crossing').resolve():
        save_homepage(out/'replay.html',Path.cwd())
    return rows,summary
