"""CPU classroom preset using sum pooling for neighbours in the same grid cell."""
import json
import os
from pathlib import Path
import random
import sys
import time

import numpy as np
import torch


ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
torch.set_num_threads(2)
np.random.seed(42)
random.seed(42)
torch.manual_seed(42)


def last_value(extra, flags, default):
    value = default
    for index, token in enumerate(extra[:-1]):
        if token in flags:
            value = extra[index + 1]
    return value


def main():
    defaults = [
        '--path', 'circle_classroom', '--type', 'social', '--epochs', '10',
        '--obs_length', '8', '--pred_length', '12', '--batch_size', '2',
        '--hidden-dim', '32', '--coordinate-embedding-dim', '16',
        '--pool_dim', '32', '--latent_dim', '8', '--n', '4', '--cell_side', '1',
        '--save_every', '1', '--disable-cuda', '--seed', '42',
        '--output', 'sum_pooling_baseline',
    ]
    extra = sys.argv[1:]
    if any(x in extra for x in ['--path', '--obs_length', '--pred_length']):
        raise SystemExit(
            'Use the fixed classroom data and 8+12 windows; edit the preset for a different task.'
        )

    kind = last_value(extra, ['--type'], 'social')
    name = last_value(extra, ['--output', '-o'], 'sum_pooling_baseline')
    if '/' in name or '\\' in name or name in ['.', '..']:
        raise SystemExit('Output name must be a simple experiment name')
    output = ROOT / f'OUTPUT_BLOCK/circle_classroom/lstm_{kind}_{name}.pkl'
    if output.exists() or Path(str(output) + '.log').exists():
        raise SystemExit('Output already exists; choose a new --output name.')

    from trajnetbaselines.lstm.sum_gridbased_pooling import SumGridBasedPooling
    from trajnetbaselines.lstm import trainer

    trainer.GridBasedPooling = SumGridBasedPooling
    sys.argv = [sys.argv[0]] + defaults + extra
    start = time.perf_counter()
    trainer.main()
    duration = time.perf_counter() - start
    Path(str(output) + '.classroom.json').write_text(
        json.dumps(
            {
                'elapsed_seconds': duration,
                'arguments': sys.argv[1:],
                'torch': torch.__version__,
                'numpy': np.__version__,
                'device': 'CPU',
                'threads': 2,
                'same_cell_pooling': 'sum',
            },
            indent=2,
        ),
        encoding='utf-8',
    )
    print(f'Training + upstream validation elapsed: {duration:.2f} seconds')
    print('Same-cell pooling: sum')
    print('Checkpoint:', output)


if __name__ == '__main__':
    main()
