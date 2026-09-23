"""Build the Week 03 metric table and comparison figures from saved results."""
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


WEEK03 = Path(__file__).resolve().parents[1]
METRICS = WEEK03 / 'results' / 'metrics'
FIGURES = WEEK03 / 'results' / 'figures'

EXPERIMENTS = [
    ('baseline_social', 'Baseline social'),
    ('no_interaction_vanilla', 'No interaction'),
    ('fine_grid_n8_cell0.5', 'Fine grid'),
    ('sum_pooling', 'Sum pooling'),
]


def load_metrics(name, split):
    with (METRICS / f'{name}.{split}.json').open(encoding='utf-8') as file:
        return json.load(file)['model']


def write_summary():
    rows = []
    for name, label in EXPERIMENTS:
        val = load_metrics(name, 'val')
        test = load_metrics(name, 'test')
        rows.append({
            'experiment': name,
            'label': label,
            'val_ADE': val['ADE'],
            'val_FDE': val['FDE'],
            'test_ADE': test['ADE'],
            'test_FDE': test['FDE'],
        })
    with (METRICS / 'summary.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return rows


def plot_metrics(rows):
    labels = [row['label'] for row in rows]
    colors = ['#4c78a8', '#f58518', '#54a24b', '#e45756']
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    panels = [
        ('val_ADE', 'Validation ADE'),
        ('val_FDE', 'Validation FDE'),
        ('test_ADE', 'Test ADE'),
        ('test_FDE', 'Test FDE'),
    ]
    for axis, (key, title) in zip(axes.flat, panels):
        values = [row[key] for row in rows]
        bars = axis.bar(range(len(rows)), values, color=colors)
        axis.set_title(title)
        axis.set_ylabel('Scaled coordinate units (lower is better)')
        axis.grid(axis='y', alpha=0.25)
        axis.bar_label(bars, fmt='%.3f', padding=3, fontsize=9)
        axis.set_xticks(range(len(rows)), labels, rotation=15, ha='right')
        axis.set_ylim(0, max(values) * 1.22)
    fig.suptitle('Week 03: ADE/FDE comparison', fontsize=15)
    fig.tight_layout()
    fig.savefig(FIGURES / 'metrics_comparison.png', dpi=180, bbox_inches='tight')
    plt.close(fig)


def plot_trajectories():
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    for axis, (name, label) in zip(axes.flat, EXPERIMENTS):
        image = plt.imread(FIGURES / f'{name}.test.png')
        axis.imshow(image)
        axis.set_title(label, fontsize=13)
        axis.axis('off')
    fig.suptitle('First test scene: trajectory comparison', fontsize=16)
    fig.tight_layout()
    fig.savefig(FIGURES / 'trajectory_comparison.png', dpi=180, bbox_inches='tight')
    plt.close(fig)


if __name__ == '__main__':
    summary_rows = write_summary()
    plot_metrics(summary_rows)
    plot_trajectories()
    print('Wrote summary.csv, metrics_comparison.png, trajectory_comparison.png')
