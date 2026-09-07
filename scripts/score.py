"""Rule based scorer for model alt text against data/manifest.json.

Reads the manifest and every results/raw/<model>__<condition>.json file, applies a
deterministic per-category rule to each model output, and writes results/scores.json
with a correctness flag, a severity label, the rule that fired, and a one line reason.

No model or network call is involved; the same inputs always produce the same output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CATEGORIES = ("functional", "informative", "decorative", "image_of_text", "complex")
SEVERITIES = ("correct", "harmless", "degraded", "silent", "misleading")

# Verbosity ceiling. A correct alt longer than this is still correct but is flagged
# harmless, since length is itself a cost to a screen reader user.
VERBOSE_WORDS = 30

# A non-empty alt on a decorative image is tolerable while it stays this short.
SHORT_DECORATIVE_WORDS = 8

# Similarity floor for accepting a transcription as matching the expected string.
TEXT_MATCH_RATIO = 0.85

# Leading boilerplate stripped before any comparison.
LEADING_BOILERPLATE = (
    "alt text:",
    "alt-text:",
    "alt:",
    "alt text is",
    "the alt text would be",
    "the alt text is",
    "here is the alt text",
    "an image of",
    "a image of",
    "the image of",
    "image of",
    "an picture of",
    "a picture of",
    "the picture of",
    "picture of",
    "a photo of",
    "an photo of",
    "photo of",
    "a photograph of",
    "photograph of",
    "this is an image of",
    "this is a picture of",
    "this image shows",
    "the image shows",
    "this image is",
    "the image is",
    "it is an image of",
    "there is",
    "there are",
    "a close up of",
    "close up of",
    "a screenshot of",
    "screenshot of",
    "an icon of",
    "a icon of",
    "icon of",
    "a graphic of",
    "graphic of",
    "a rendering of",
    "an illustration of",
    "illustration of",
    "a diagram of",
    "diagram of",
    "showing",
    "depicting",
)

# Strings a model produces when it means "no alt text".
EMPTY_MARKERS = {
    "",
    "empty",
    "emptystring",
    "empty string",
    "empty alt",
    "empty alt text",
    "none",
    "n/a",
    "na",
    "null",
    "nil",
    "nothing",
    "no alt text",
    "no alt",
    "no text",
    "decorative",
    "decorative image",
    "purely decorative",
    "alt=",
    'alt=""',
    "-",
    "--",
}

# Groups of words that mean the same action for alt text purposes. Any member of a
# group satisfies a required keyword belonging to the same group.
SYNONYM_GROUPS = [
    {"delete", "remove", "discard", "trash", "bin", "erase"},
    {"close", "dismiss", "exit", "cancel"},
    {"menu", "navigation", "nav", "hamburger"},
    {"cart", "basket", "trolley", "bag"},
    {"home", "homepage", "main page", "start page"},
    {"settings", "preferences", "options", "configuration", "config"},
    {"edit", "modify", "change", "rename", "update"},
    {"download", "save", "export"},
    {"upload", "import", "attach"},
    {"share", "send to", "distribute"},
    {"play", "start", "resume"},
    {"pause", "stop", "halt"},
    {"search", "find", "look up", "query"},
    {"add", "create", "new", "plus", "insert"},
    {"next", "forward", "continue"},
    {"previous", "back", "backward", "prior"},
    {"expand", "open", "show more", "unfold"},
    {"collapse", "hide", "show less", "fold"},
    {"print", "printer"},
    {"profile", "account", "user", "avatar"},
    {"favorite", "favourite", "bookmark", "star", "like", "save for later"},
    {"notification", "alert", "bell"},
    {"help", "support", "assistance", "faq"},
    {"login", "log in", "sign in", "signin"},
    {"logout", "log out", "sign out", "signout"},
    {"filter", "refine", "sort"},
    {"refresh", "reload", "sync", "update"},
    {"zoom", "magnify", "enlarge"},
    {"copy", "duplicate", "clone"},
    {"submit", "confirm", "apply", "ok"},
    {"volume", "sound", "audio", "mute"},
    {"calendar", "schedule", "date"},
    {"location", "map", "address", "directions"},
    {"phone", "call", "telephone"},
    {"email", "mail", "message", "contact"},
    {"chart", "graph", "plot"},
    {"percent", "percentage", "pct"},
]

_SYNONYM_INDEX: dict[str, set[str]] = {}
for _group in SYNONYM_GROUPS:
    for _member in _group:
        _SYNONYM_INDEX.setdefault(_member, set()).update(_group)


def strip_accents(text: str) -> str:
    """Return text with combining marks removed."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_alt(text: str | None) -> str:
    """Lowercase, unquote, strip leading boilerplate, and drop trailing punctuation."""
    if text is None:
        return ""
    out = strip_accents(str(text))
    out = out.replace("’", "'").replace("“", '"').replace("”", '"')
    out = re.sub(r"\s+", " ", out).strip().lower()

    # Drop wrapping quotes, possibly repeated.
    for _ in range(3):
        stripped = out.strip().strip("`")
        if len(stripped) >= 2 and stripped[0] in "\"'" and stripped[-1] in "\"'":
            stripped = stripped[1:-1].strip()
        if stripped == out:
            break
        out = stripped

    # Drop leading boilerplate, possibly stacked ("alt text: an image of a cat").
    changed = True
    while changed:
        changed = False
        out = out.lstrip(" \t:;,-")
        for prefix in LEADING_BOILERPLATE:
            if out.startswith(prefix + " ") or out == prefix:
                out = out[len(prefix):].strip()
                changed = True
                break
        # A leading article left behind by the boilerplate strip carries no meaning.
        for article in ("a ", "an ", "the "):
            if out.startswith(article):
                out = out[len(article):].strip()
                changed = True
                break

    out = out.strip().strip("\"'` ")
    out = re.sub(r"[.!,;:\s]+$", "", out)
    return out.strip()


def is_empty_alt(text: str | None) -> bool:
    """True when the model output means "no alt text"."""
    raw = "" if text is None else str(text).strip().strip("\"'`").strip()
    if raw == "":
        return True
    marker = re.sub(r"[\s]+", " ", raw.lower()).strip()
    marker = re.sub(r"^[\(\[\{]|[\)\]\}]$", "", marker).strip()
    marker = re.sub(r"[.!]+$", "", marker).strip()
    if marker in EMPTY_MARKERS:
        return True
    # Wordings such as "empty (decorative)" or "alt="" (decorative image)".
    condensed = re.sub(r"[^a-z ]", "", marker).strip()
    return condensed in EMPTY_MARKERS


def words(text: str) -> list[str]:
    """Alphanumeric tokens of a normalized string."""
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


def word_count(text: str) -> int:
    return len(words(text))


def stem(token: str) -> str:
    """Crude suffix stripper good enough to join search/searches/searching."""
    t = token.lower()
    for suffix, keep in (("ingly", 0), ("edly", 0), ("ing", 3), ("ers", 3), ("ies", 3),
                         ("ied", 3), ("ed", 3), ("es", 3), ("er", 4), ("s", 3)):
        if t.endswith(suffix) and len(t) - len(suffix) >= keep:
            base = t[: len(t) - len(suffix)]
            if suffix in ("ies", "ied"):
                base += "y"
            # Undouble a final consonant left by -ing / -ed ("stopping" -> "stop").
            if suffix in ("ing", "ed") and len(base) > 2 and base[-1] == base[-2]:
                base = base[:-1]
            return base
    return t


def _variants(term: str) -> set[str]:
    """Every surface form that satisfies a required term, synonyms included."""
    term = term.strip().lower()
    forms = {term}
    forms.update(_SYNONYM_INDEX.get(term, set()))
    for w in list(forms):
        forms.add(stem(w))
    return {f for f in forms if f}


def keyword_present(term: str, alt_norm: str) -> bool:
    """True when a required manifest keyword is expressed anywhere in the alt."""
    term = str(term).strip().lower()
    if not term:
        return True
    alt_tokens = words(alt_norm)
    alt_stems = {stem(t) for t in alt_tokens}
    alt_tokens_set = set(alt_tokens)

    for form in _variants(term):
        if " " in form:
            if form in alt_norm:
                return True
            continue
        if form in alt_tokens_set or form in alt_stems or stem(form) in alt_stems:
            return True
    # Numbers and other literals may sit inside punctuation ("48%", "1,000").
    if re.fullmatch(r"[\d.,%$]+", term):
        digits = term.replace(",", "").rstrip("%")
        compact = alt_norm.replace(",", "")
        if digits and digits in compact:
            return True
    return False


def present_terms(terms, alt_norm: str) -> list[str]:
    return [t for t in (terms or []) if keyword_present(t, alt_norm)]


def levenshtein(a: str, b: str) -> int:
    """Edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def similarity(a: str, b: str) -> float:
    """1.0 for identical strings, falling to 0.0 as edits accumulate."""
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - levenshtein(a, b) / longest


def squash(text: str) -> str:
    """Letters and digits only, for punctuation insensitive text comparison."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> list[str]:
    """Numeric literals with grouping separators removed."""
    out = []
    for match in NUMBER_RE.findall(text or ""):
        cleaned = match.replace(",", "")
        cleaned = cleaned.rstrip(".")
        if cleaned:
            out.append(cleaned)
    return out


def _verdict(correct: bool, severity: str, rule: str, reason: str) -> dict:
    return {"correct": correct, "severity": severity, "rule": rule, "reason": reason}


def _apply_verbosity(verdict: dict, alt_norm: str) -> dict:
    """Downgrade a correct but long alt to harmless, keeping correct true."""
    if verdict["correct"] and verdict["severity"] == "correct":
        n = word_count(alt_norm)
        if n > VERBOSE_WORDS:
            verdict = dict(verdict)
            verdict["severity"] = "harmless"
            verdict["rule"] = verdict["rule"] + "+verbose"
            verdict["reason"] = f"meets the requirement but runs {n} words"
    return verdict


def score_decorative(alt_norm: str, empty: bool, item: dict) -> dict:
    if empty:
        return _verdict(True, "correct", "decorative_empty",
                        "empty alt on a decorative image")
    n = word_count(alt_norm)
    if n < SHORT_DECORATIVE_WORDS:
        return _verdict(False, "harmless", "decorative_short_text",
                        f"decorative image described in {n} words instead of left empty")
    return _verdict(False, "degraded", "decorative_verbose_text",
                    f"decorative image described at length ({n} words)")


def score_functional(alt_norm: str, empty: bool, item: dict) -> dict:
    must = item.get("must_include") or []
    must_not = item.get("must_not_include") or []
    if empty:
        return _verdict(False, "silent", "functional_empty",
                        "empty alt on a control, the element is silent to a screen reader")
    hits = present_terms(must, alt_norm)
    if must and len(hits) == len(must):
        return _verdict(True, "correct", "functional_action_named",
                        "names the control action")
    if not must:
        return _verdict(True, "correct", "functional_no_keywords",
                        "non-empty alt and no required keywords declared")
    appearance = present_terms(must_not, alt_norm)
    if appearance:
        return _verdict(False, "degraded", "functional_appearance",
                        "describes appearance (" + ", ".join(appearance)
                        + ") instead of the action")
    if hits:
        return _verdict(False, "degraded", "functional_partial_action",
                        "names part of the action, missing "
                        + ", ".join(t for t in must if t not in hits))
    return _verdict(False, "misleading", "functional_wrong",
                    "does not state the action and does not describe the control")


def score_image_of_text(alt_norm: str, empty: bool, item: dict) -> dict:
    expected = normalize_alt(item.get("expected_alt") or "")
    must = item.get("must_include") or []
    if empty:
        return _verdict(False, "silent", "text_empty",
                        "empty alt on an image whose content is text")
    hits = present_terms(must, alt_norm)
    ratio = similarity(squash(alt_norm), squash(expected)) if expected else 0.0
    contains = bool(expected) and squash(expected) in squash(alt_norm)
    if contains or ratio >= TEXT_MATCH_RATIO or (must and len(hits) == len(must)):
        return _verdict(True, "correct", "text_transcribed",
                        f"transcribes the visible text (similarity {ratio:.2f})")
    if must and len(hits) * 2 >= len(must):
        return _verdict(False, "degraded", "text_partial",
                        f"transcribes part of the text ({len(hits)} of {len(must)} words)")
    return _verdict(False, "misleading", "text_wrong",
                    f"does not reproduce the visible text (similarity {ratio:.2f})")


def score_informative(alt_norm: str, empty: bool, item: dict) -> dict:
    must = item.get("must_include") or []
    if empty:
        return _verdict(False, "silent", "informative_empty",
                        "empty alt on an image that carries information")
    hits = present_terms(must, alt_norm)
    if not must or len(hits) == len(must):
        return _verdict(True, "correct", "informative_complete",
                        "covers the required content")
    if hits:
        return _verdict(False, "degraded", "informative_partial",
                        "covers " + ", ".join(hits) + ", missing "
                        + ", ".join(t for t in must if t not in hits))
    return _verdict(False, "misleading", "informative_wrong",
                    "none of the required content appears")


def score_complex(alt_norm: str, empty: bool, item: dict) -> dict:
    must = [str(t) for t in (item.get("must_include") or [])]
    numeric = [t for t in must if NUMBER_RE.fullmatch(t.replace(",", ""))]
    title_terms = [t for t in must if t not in numeric]
    if empty:
        return _verdict(False, "silent", "complex_empty",
                        "empty alt on a chart, the data is unavailable")
    title_hits = present_terms(title_terms, alt_norm)
    alt_numbers = set(numbers_in(alt_norm))
    number_hits = [n for n in numeric if n.replace(",", "").rstrip(".") in alt_numbers]
    title_ok = not title_terms or len(title_hits) == len(title_terms)
    numbers_ok = not numeric or len(number_hits) * 2 >= len(numeric)
    if title_ok and numbers_ok:
        return _verdict(True, "correct", "complex_title_and_data",
                        f"states the subject and {len(number_hits)} of {len(numeric)} values")
    if title_ok:
        return _verdict(False, "degraded", "complex_title_only",
                        f"states the subject but only {len(number_hits)} of "
                        f"{len(numeric)} data values")
    if title_hits or number_hits:
        return _verdict(False, "degraded", "complex_partial",
                        "partial subject and data coverage")
    return _verdict(False, "misleading", "complex_wrong",
                    "neither the subject nor the data appears")


SCORERS = {
    "decorative": score_decorative,
    "functional": score_functional,
    "image_of_text": score_image_of_text,
    "informative": score_informative,
    "complex": score_complex,
}


def score_alt(item: dict, alt: str | None) -> dict:
    """Score one model output against one manifest item.

    Returns a dict with correct, severity, rule, reason.
    """
    category = item.get("category")
    scorer = SCORERS.get(category)
    if scorer is None:
        return _verdict(False, "misleading", "unknown_category",
                        f"category {category!r} is not one of {', '.join(CATEGORIES)}")
    alt_norm = normalize_alt(alt)
    empty = is_empty_alt(alt)
    verdict = scorer(alt_norm, empty, item)
    return _apply_verbosity(verdict, alt_norm)


def load_manifest(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text())
    items = {}
    for item in data.get("items", []):
        items[item["id"]] = item
    return items


def raw_files(raw_dir: Path) -> list[Path]:
    return sorted(p for p in raw_dir.glob("*.json") if p.is_file())


def score_all(manifest_path: Path, raw_dir: Path) -> dict:
    items = load_manifest(manifest_path)
    rows = []
    missing_ids = set()
    for path in raw_files(raw_dir):
        run = json.loads(path.read_text())
        model = run.get("model", path.stem)
        condition = run.get("condition", "unknown")
        for item_id, output in (run.get("outputs") or {}).items():
            item = items.get(item_id)
            if item is None:
                missing_ids.add(item_id)
                continue
            alt = output.get("alt") if isinstance(output, dict) else output
            verdict = score_alt(item, alt)
            rows.append({
                "id": item_id,
                "model": model,
                "condition": condition,
                "category": item.get("category"),
                "alt": "" if alt is None else str(alt),
                "correct": verdict["correct"],
                "severity": verdict["severity"],
                "rule": verdict["rule"],
                "reason": verdict["reason"],
            })
    rows.sort(key=lambda r: (r["model"], r["condition"], r["id"]))
    if missing_ids:
        print(f"warning: {len(missing_ids)} output ids absent from the manifest, skipped",
              file=sys.stderr)
    return {"rows": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score model alt text against the manifest.")
    parser.add_argument("--manifest", default=str(REPO_ROOT / "data" / "manifest.json"))
    parser.add_argument("--raw-dir", default=str(REPO_ROOT / "results" / "raw"))
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "scores.json"))
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    raw_dir = Path(args.raw_dir)
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    if not raw_dir.exists():
        print(f"raw directory not found: {raw_dir}", file=sys.stderr)
        return 1

    scores = score_all(manifest_path, raw_dir)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(scores, indent=2) + "\n")

    counts: dict[str, int] = {}
    for row in scores["rows"]:
        counts[row["severity"]] = counts.get(row["severity"], 0) + 1
    n = len(scores["rows"])
    n_correct = sum(1 for r in scores["rows"] if r["correct"])
    print(f"scored {n} rows from {len(raw_files(raw_dir))} runs -> {out_path}")
    if n:
        print(f"overall accuracy {n_correct / n:.3f}")
    print("severity " + "  ".join(f"{s}={counts.get(s, 0)}" for s in SEVERITIES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
