"""Render the presentation figures from results/summary.json.

Writes three PNG files at 1600x900, 200 dpi:

  presentation/fig_functional_by_condition.png  functional accuracy, grouped by model
  presentation/fig_accuracy_heatmap.png         category by condition accuracy per model
  presentation/fig_severity_stack.png           severity mix per condition, functional only

Figures carry axis labels and legends but no headline text; the slide supplies the title.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]

FIG_W, FIG_H, DPI = 8.0, 4.5, 200

CONDITION_ORDER = ["caption", "naive", "wcag", "wcag_context"]
CATEGORY_ORDER = ["functional", "informative", "image_of_text", "complex", "decorative"]
SEVERITY_ORDER = ["correct", "harmless", "degraded", "silent", "misleading"]

CATEGORY_LABEL = {
    "functional": "functional",
    "informative": "informative",
    "image_of_text": "image of text",
    "complex": "complex",
    "decorative": "decorative",
}
CONDITION_LABEL = {
    "caption": "caption",
    "naive": "naive",
    "wcag": "WCAG",
    "wcag_context": "WCAG + context",
}

# Okabe-Ito, safe for the common forms of colour vision deficiency.
OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442"]

SEVERITY_COLOR = {
    "correct": "#009E73",
    "harmless": "#56B4E9",
    "degraded": "#E69F00",
    "silent": "#000000",
    "misleading": "#D55E00",
}

BASE_FONT = 13

# Height drawn for a zero valued bar so its colour stays visible.
ZERO_STUB = 0.012


def apply_style() -> None:
    plt.rcParams.update({
        "figure.dpi": DPI,
        "savefig.dpi": DPI,
        "font.size": BASE_FONT,
        "axes.titlesize": BASE_FONT + 2,
        "axes.labelsize": BASE_FONT + 2,
        "xtick.labelsize": BASE_FONT,
        "ytick.labelsize": BASE_FONT,
        "legend.fontsize": BASE_FONT,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#D9D9D9",
        "grid.linewidth": 0.8,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })


def short_model(name: str) -> str:
    """Drop the org prefix and the instruct suffix from a model id."""
    tail = name.split("/")[-1]
    for suffix in ("-Instruct", "-instruct", "-hf"):
        if tail.endswith(suffix):
            tail = tail[: -len(suffix)]
    return tail


def model_order(block: dict) -> list:
    """Caption only baselines first, then the instruction following models by name."""
    def key(name):
        conditions = set(block.get(name, {}))
        return (0 if conditions == {"caption"} else 1, name.lower())
    return sorted(block, key=key)


def ordered(values, order) -> list:
    known = [v for v in order if v in values]
    extra = sorted(v for v in values if v not in order)
    return known + extra


def new_fig(nrows=1, ncols=1, **kwargs):
    return plt.subplots(nrows, ncols, figsize=(FIG_W, FIG_H), **kwargs)


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches=None)
    plt.close(fig)
    print(f"wrote {path}")


def plot_functional_by_condition(summary: dict, out: Path) -> None:
    """Grouped bars: functional accuracy, one group per model, one bar per condition."""
    accuracy = summary["accuracy"]
    models = model_order(accuracy)
    conditions = ordered({c for m in accuracy.values() for c in m}, CONDITION_ORDER)

    fig, ax = new_fig()
    group_width = 0.72
    # Widest group decides the bar width so every group uses the same bar size.
    per_model = {m: [c for c in conditions if "functional" in accuracy[m].get(c, {})]
                 for m in models}
    widest = max((len(v) for v in per_model.values()), default=1) or 1
    bar_width = group_width / widest

    handles: dict[str, object] = {}
    for mi, model in enumerate(models):
        present = per_model[model]
        span = bar_width * len(present)
        for slot, condition in enumerate(present):
            value = accuracy[model][condition]["functional"]
            x = mi - span / 2 + bar_width * (slot + 0.5)
            ci = conditions.index(condition)
            # A zero bar still gets a visible stub so the reader can see which
            # condition produced it.
            drawn = max(value, ZERO_STUB)
            bars = ax.bar([x], [drawn], width=bar_width * 0.88,
                          color=OKABE_ITO[ci % len(OKABE_ITO)],
                          edgecolor="white", linewidth=0.6)
            ax.bar_label(bars, labels=[f"{value:.2f}"], padding=3,
                         fontsize=BASE_FONT - 1)
            handles.setdefault(condition, bars[0])

    ax.set_xticks(range(len(models)))
    ax.set_xticklabels([short_model(m) for m in models])
    ax.set_xlim(-0.6, len(models) - 0.4)
    ax.set_ylabel("functional accuracy")
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.xaxis.grid(False)
    fig.legend([handles[c] for c in conditions if c in handles],
               [CONDITION_LABEL.get(c, c) for c in conditions if c in handles],
               title="prompt condition", frameon=False,
               ncol=min(len(handles), 4), loc="upper center",
               bbox_to_anchor=(0.5, 0.995))
    fig.tight_layout(rect=(0, 0, 1, 0.87))
    save(fig, out)


def plot_accuracy_heatmap(summary: dict, out: Path) -> None:
    """One panel per model: category rows by condition columns, accuracy shaded."""
    accuracy = summary["accuracy"]
    models = model_order(accuracy)
    categories = ordered(
        {c for m in accuracy.values() for cond in m.values() for c in cond
         if c != "all"},
        CATEGORY_ORDER)

    cmap = LinearSegmentedColormap.from_list(
        "accuracy", ["#F7F7F7", "#9ECAE1", "#0072B2"])

    per_model = {m: ordered(accuracy[m].keys(), CONDITION_ORDER) for m in models}

    fig = plt.figure(figsize=(FIG_W, FIG_H), layout="constrained")
    axes = fig.subplots(1, max(len(models), 1), squeeze=False,
                        width_ratios=[max(len(per_model[m]), 1) for m in models])[0]
    im = None
    for ax, model in zip(axes, models):
        conditions = per_model[model]
        grid = [[accuracy[model].get(cond, {}).get(cat) for cond in conditions]
                for cat in categories]
        plot_grid = [[0.0 if v is None else v for v in row] for row in grid]
        im = ax.imshow(plot_grid, cmap=cmap, vmin=0.0, vmax=1.0, aspect="auto")
        ax.set_xticks(range(len(conditions)))
        ax.set_xticklabels([CONDITION_LABEL.get(c, c).replace(" + ", "\n+ ")
                            for c in conditions])
        ax.set_yticks(range(len(categories)))
        ax.set_yticklabels([CATEGORY_LABEL.get(c, c) for c in categories])
        ax.set_xlabel(short_model(model), labelpad=8)
        ax.tick_params(length=0)
        ax.grid(False)
        for r, row in enumerate(grid):
            for c, value in enumerate(row):
                if value is None:
                    continue
                colour = "white" if value > 0.55 else "#1A1A1A"
                ax.text(c, r, f"{value:.2f}", ha="center", va="center",
                        color=colour, fontsize=BASE_FONT - 1)
        if ax is not axes[0]:
            ax.set_yticklabels([])

    for ax in axes[len(models):]:
        ax.axis("off")

    if im is not None:
        fig.colorbar(im, ax=list(axes), fraction=0.04, pad=0.02, label="accuracy")
    save(fig, out)


def plot_severity_stack(summary: dict, out: Path) -> None:
    """Stacked severity counts for the functional category, one bar per run."""
    severity = summary["severity"]
    models = model_order(severity)

    labels, columns = [], []
    for model in models:
        for condition in ordered(severity[model].keys(), CONDITION_ORDER):
            counts = severity[model][condition].get("functional")
            if not counts:
                continue
            labels.append((short_model(model),
                           CONDITION_LABEL.get(condition, condition)))
            columns.append(counts)

    fig, ax = new_fig()
    xs = list(range(len(columns)))
    bottoms = [0.0] * len(columns)
    for sev in SEVERITY_ORDER:
        values = [float(col.get(sev, 0)) for col in columns]
        if not any(values):
            continue
        ax.bar(xs, values, bottom=bottoms, width=0.62, label=sev,
               color=SEVERITY_COLOR[sev], edgecolor="white", linewidth=0.7)
        bottoms = [b + v for b, v in zip(bottoms, values)]

    ax.set_xticks(xs)
    ax.set_xticklabels([cond for _, cond in labels])
    ax.set_ylabel("functional items")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
    ax.xaxis.grid(False)
    if bottoms:
        ax.set_ylim(0, max(bottoms) * 1.15 or 1)
    ax.set_xlim(-0.7, len(columns) - 0.3)

    # One model name per run of bars, centred under the conditions it covers.
    if len(models) > 1:
        span = blended_transform_factory(ax.transData, ax.transAxes)
        start = 0
        for index in range(len(labels) + 1):
            if index == len(labels) or labels[index][0] != labels[start][0]:
                centre = (start + index - 1) / 2
                ax.text(centre, -0.16, labels[start][0], transform=span,
                        ha="center", va="top", fontsize=BASE_FONT)
                start = index

    fig.legend(*ax.get_legend_handles_labels(), title="severity", frameon=False,
               ncol=min(len(SEVERITY_ORDER), 5), loc="upper center",
               bbox_to_anchor=(0.5, 0.995))
    fig.tight_layout(rect=(0, 0.03, 1, 0.87))
    save(fig, out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render the presentation figures.")
    parser.add_argument("--summary", default=str(REPO_ROOT / "results" / "summary.json"))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "presentation"))
    args = parser.parse_args(argv)

    summary_path = Path(args.summary)
    if not summary_path.exists():
        print(f"summary not found: {summary_path}, run summarize.py first")
        return 1
    summary = json.loads(summary_path.read_text())
    if not summary.get("accuracy"):
        print("summary has no accuracy data, nothing to plot")
        return 1

    apply_style()
    out_dir = Path(args.out_dir)
    plot_functional_by_condition(summary, out_dir / "fig_functional_by_condition.png")
    plot_accuracy_heatmap(summary, out_dir / "fig_accuracy_heatmap.png")
    plot_severity_stack(summary, out_dir / "fig_severity_stack.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
