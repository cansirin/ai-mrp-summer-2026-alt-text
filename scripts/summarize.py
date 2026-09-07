"""Aggregate results/scores.json into results/summary.json and results/human_subset.csv.

Produces per model, per condition, per category accuracy and severity counts, a set of
illustrative examples per severity, an inter-rater agreement block computed from
results/human_ratings.csv when that file exists, and a 30 item stratified sample with
empty rater columns for two human raters to fill in.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CATEGORIES = ("functional", "informative", "decorative", "image_of_text", "complex")
SEVERITIES = ("correct", "harmless", "degraded", "silent", "misleading")

SUBSET_N = 30
SUBSET_CONDITIONS = ("wcag", "wcag_context")
SUBSET_MODEL_HINT = "qwen"
EXAMPLES_PER_SEVERITY = 4

# Categories whose examples illustrate a severity most sharply.
EXAMPLE_PREFERENCE = {
    "silent": ("functional",),
    "misleading": ("image_of_text", "informative"),
    "degraded": ("functional",),
    "harmless": ("decorative",),
    "correct": (),
}

SUBSET_COLUMNS = ["id", "file", "category", "expected_alt", "model", "condition", "alt",
                  "rater_correct", "rater_severity", "rater_notes",
                  "second_rater_correct", "second_rater_severity", "second_rater_notes"]


def load_json(path: Path):
    return json.loads(path.read_text())


def manifest_index(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {item["id"]: item for item in load_json(path).get("items", [])}


def accuracy_and_severity(rows: list[dict]):
    """Nested model -> condition -> category accuracy and severity counts."""
    buckets: dict[str, dict[str, dict[str, list[dict]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        buckets[row["model"]][row["condition"]][row["category"]].append(row)
        buckets[row["model"]][row["condition"]]["all"].append(row)

    accuracy: dict = {}
    severity: dict = {}
    for model in sorted(buckets):
        accuracy[model] = {}
        severity[model] = {}
        for condition in sorted(buckets[model]):
            acc_row: dict[str, float] = {}
            sev_row: dict[str, dict[str, int]] = {}
            for key in sorted(buckets[model][condition]):
                group = buckets[model][condition][key]
                acc_row[key] = round(sum(1 for r in group if r["correct"]) / len(group), 4)
                counts = {s: 0 for s in SEVERITIES}
                for r in group:
                    counts[r["severity"]] = counts.get(r["severity"], 0) + 1
                counts["n"] = len(group)
                sev_row[key] = counts
            accuracy[model][condition] = acc_row
            severity[model][condition] = sev_row
    return accuracy, severity


def pick_examples(rows: list[dict]) -> dict[str, list[dict]]:
    """Up to four rows per severity, preferring the categories that illustrate it."""
    out: dict[str, list[dict]] = {}
    for severity in SEVERITIES:
        pool = [r for r in rows if r["severity"] == severity]
        preferred = EXAMPLE_PREFERENCE.get(severity, ())

        def rank(row: dict):
            try:
                pref = preferred.index(row["category"])
            except ValueError:
                pref = len(preferred)
            return (pref, row["model"], row["condition"], row["id"])

        pool.sort(key=rank)
        chosen: list[dict] = []
        seen_ids: set[str] = set()
        # Prefer distinct items before allowing a second output of the same image.
        for row in pool:
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            chosen.append(row)
            if len(chosen) >= EXAMPLES_PER_SEVERITY:
                break
        for row in pool:
            if len(chosen) >= EXAMPLES_PER_SEVERITY:
                break
            if row not in chosen:
                chosen.append(row)
        out[severity] = [{"id": r["id"], "model": r["model"], "condition": r["condition"],
                          "category": r["category"], "alt": r["alt"], "rule": r["rule"],
                          "reason": r["reason"]}
                         for r in chosen]
    return out


def _truthy(value: str):
    """Parse a rater cell into True, False, or None when it is blank or unreadable."""
    v = (value or "").strip().lower()
    if v in ("1", "true", "t", "yes", "y", "correct", "ok"):
        return True
    if v in ("0", "false", "f", "no", "n", "incorrect", "wrong"):
        return False
    return None


def _rater_columns(fieldnames: list[str]) -> list[str]:
    """Column names that hold a per-rater correctness judgment."""
    cols = [c for c in fieldnames if c.strip().lower().endswith("correct")]
    # Keep a stable order, author style column first when present.
    cols.sort(key=lambda c: (0 if "rater_correct" == c.strip().lower() else 1, c))
    return cols


def cohen_kappa(a: list[bool], b: list[bool]) -> float:
    """Cohen's kappa for two binary rating vectors."""
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    pa_true = sum(1 for x in a if x) / n
    pb_true = sum(1 for x in b if x) / n
    expected = pa_true * pb_true + (1 - pa_true) * (1 - pb_true)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def agreement_block(ratings_path: Path) -> dict:
    """Percent agreement and Cohen's kappa between the two rater columns."""
    empty = {"n": 0, "raters": [], "cohen_kappa": 0.0, "percent": 0.0,
             "note": "results/human_ratings.csv not present or not filled in"}
    if not ratings_path.exists():
        return empty
    with ratings_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    cols = _rater_columns(fieldnames)
    if len(cols) < 2:
        note = dict(empty)
        note["note"] = ("results/human_ratings.csv needs two columns whose names end in "
                        "'correct', one per rater")
        return note
    first, second = cols[0], cols[1]
    a: list[bool] = []
    b: list[bool] = []
    for row in rows:
        va, vb = _truthy(row.get(first, "")), _truthy(row.get(second, ""))
        if va is None or vb is None:
            continue
        a.append(va)
        b.append(vb)
    if not a:
        return empty
    percent = sum(1 for x, y in zip(a, b) if x == y) / len(a)
    return {"n": len(a), "raters": [first, second],
            "cohen_kappa": round(cohen_kappa(a, b), 4),
            "percent": round(percent, 4)}


def build_subset(rows: list[dict], manifest: dict[str, dict], n: int = SUBSET_N) -> list[dict]:
    """Stratified sample across categories and conditions for human rating."""
    pool = [r for r in rows
            if r["condition"] in SUBSET_CONDITIONS
            and SUBSET_MODEL_HINT in r["model"].lower()]
    if not pool:
        # No Qwen run present, fall back to whatever conditions exist.
        pool = [r for r in rows if r["condition"] in SUBSET_CONDITIONS] or list(rows)

    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in pool:
        buckets[(row["category"], row["condition"])].append(row)

    rng = random.Random(20260906)
    for key in buckets:
        buckets[key].sort(key=lambda r: (r["model"], r["id"]))
        rng.shuffle(buckets[key])

    keys = sorted(buckets)
    picked: list[dict] = []
    cursor = {k: 0 for k in keys}
    while len(picked) < n and any(cursor[k] < len(buckets[k]) for k in keys):
        for key in keys:
            if len(picked) >= n:
                break
            if cursor[key] < len(buckets[key]):
                picked.append(buckets[key][cursor[key]])
                cursor[key] += 1

    out = []
    for row in picked:
        item = manifest.get(row["id"], {})
        out.append({
            "id": row["id"],
            "file": item.get("file", ""),
            "category": row["category"],
            "expected_alt": item.get("expected_alt", ""),
            "model": row["model"],
            "condition": row["condition"],
            "alt": row["alt"],
            "rater_correct": "",
            "rater_severity": "",
            "rater_notes": "",
            "second_rater_correct": "",
            "second_rater_severity": "",
            "second_rater_notes": "",
        })
    out.sort(key=lambda r: (r["category"], r["condition"], r["id"]))
    return out


def write_subset(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUBSET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def summarize(scores: dict, manifest: dict[str, dict], ratings_path: Path) -> dict:
    rows = scores.get("rows", [])
    accuracy, severity = accuracy_and_severity(rows)

    if manifest:
        by_category = {c: 0 for c in CATEGORIES}
        for item in manifest.values():
            by_category[item["category"]] = by_category.get(item["category"], 0) + 1
        n_items = len(manifest)
    else:
        seen: dict[str, str] = {row["id"]: row["category"] for row in rows}
        by_category = {c: 0 for c in CATEGORIES}
        for category in seen.values():
            by_category[category] = by_category.get(category, 0) + 1
        n_items = len(seen)

    return {
        "n_items": n_items,
        "n_rows": len(rows),
        "by_category": by_category,
        "models": sorted({row["model"] for row in rows}),
        "conditions": sorted({row["condition"] for row in rows}),
        "accuracy": accuracy,
        "severity": severity,
        "agreement": agreement_block(ratings_path),
        "examples": pick_examples(rows),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Summarize scored alt text results.")
    parser.add_argument("--scores", default=str(REPO_ROOT / "results" / "scores.json"))
    parser.add_argument("--manifest", default=str(REPO_ROOT / "data" / "manifest.json"))
    parser.add_argument("--ratings", default=str(REPO_ROOT / "results" / "human_ratings.csv"))
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "summary.json"))
    parser.add_argument("--subset-out",
                        default=str(REPO_ROOT / "results" / "human_subset.csv"))
    parser.add_argument("--subset-n", type=int, default=SUBSET_N)
    args = parser.parse_args(argv)

    scores_path = Path(args.scores)
    if not scores_path.exists():
        print(f"scores not found: {scores_path}, run score.py first")
        return 1
    scores = load_json(scores_path)
    manifest = manifest_index(Path(args.manifest))

    summary = summarize(scores, manifest, Path(args.ratings))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2) + "\n")

    subset = build_subset(scores.get("rows", []), manifest, args.subset_n)
    write_subset(Path(args.subset_out), subset)

    print(f"summary -> {out_path} ({summary['n_rows']} rows, {summary['n_items']} items)")
    print(f"human subset -> {args.subset_out} ({len(subset)} rows)")
    agreement = summary["agreement"]
    if agreement["n"]:
        print(f"agreement n={agreement['n']} percent={agreement['percent']:.3f} "
              f"kappa={agreement['cohen_kappa']:.3f}")
    else:
        print("agreement: no filled human ratings found")
    for model in summary["models"]:
        for condition in sorted(summary["accuracy"][model]):
            acc = summary["accuracy"][model][condition]
            functional = acc.get("functional")
            line = f"  {model} / {condition}: all={acc.get('all', 0):.3f}"
            if functional is not None:
                line += f" functional={functional:.3f}"
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
