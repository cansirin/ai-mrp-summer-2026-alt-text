"""Build the slide deck from the scored results.

Every number on a slide is read from results/summary.json. Category counts come
from data/manifest.json, example thumbnails from data/images, and the three
charts from the PNG files in this directory. Nothing is written by hand, so
re-scoring and rebuilding keeps the deck and the results in step.

    python presentation/build_deck.py

Useful flags:

    --summary PATH    read a different summary file (also ALT_TEXT_SUMMARY)
    --manifest PATH   read a different manifest
    --images DIR      directory holding the example images
    --figures DIR     directory holding the three chart PNGs
    --out PATH        where to write the HTML

Then export to PDF with headless Chrome:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
        --headless --disable-gpu --no-pdf-header-footer \\
        --print-to-pdf=presentation/slides.pdf presentation/slides.html
"""

import argparse
import base64
import html
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent

REPO_URL = "https://github.com/cansirin/ai-mrp-summer-2026-alt-text"
DECISION_TREE_URL = "https://www.w3.org/WAI/tutorials/images/decision-tree/"
WCAG_URL = "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html"

CATEGORY_ORDER = [
    "functional",
    "informative",
    "decorative",
    "image_of_text",
    "complex",
]
CATEGORY_LABELS = {
    "functional": "Functional",
    "informative": "Informative",
    "decorative": "Decorative",
    "image_of_text": "Image of text",
    "complex": "Complex",
}

CONDITION_ORDER = ["caption", "naive", "wcag", "wcag_context"]
CONDITION_LABELS = {
    "caption": "Caption only",
    "naive": "Naive prompt",
    "wcag": "WCAG prompt",
    "wcag_context": "WCAG plus context",
}

SEVERITY_ORDER = ["correct", "harmless", "degraded", "silent", "misleading"]
SEVERITY_LABELS = {
    "correct": "Correct",
    "harmless": "Harmless",
    "degraded": "Degraded",
    "silent": "Silent",
    "misleading": "Misleading",
}

# Models are tried in this order when picking the one the headline slides use.
PREFERRED_MODELS = [
    "Qwen/Qwen2-VL-7B-Instruct",
    "Qwen/Qwen2-VL-2B-Instruct",
]

FIGURES = [
    "fig_functional_by_condition.png",
    "fig_accuracy_heatmap.png",
    "fig_severity_stack.png",
]

CSS = """
@page { size: 1280px 720px; margin: 0; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  color: #16181d;
  background: #fff;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}
section {
  width: 1280px; height: 720px;
  padding: 60px 84px;
  page-break-after: always;
  break-after: page;
  display: flex; flex-direction: column;
  position: relative;
  overflow: hidden;
}
section:last-child { page-break-after: auto; break-after: auto; }
section::after {
  content: attr(data-page);
  position: absolute; bottom: 28px; right: 84px;
  font-size: 14px; color: #9aa1ad;
}
.kicker {
  font-size: 14px; letter-spacing: .14em; text-transform: uppercase;
  color: #6b7280; margin-bottom: 14px; font-weight: 600;
}
h1 { font-size: 58px; line-height: 1.06; margin: 0 0 22px; letter-spacing: -.02em; }
h2 { font-size: 40px; line-height: 1.12; margin: 0 0 22px; letter-spacing: -.02em; }
p { font-size: 23px; line-height: 1.45; margin: 0 0 15px; max-width: 64ch; color: #2b2f38; }
.lead { font-size: 27px; color: #16181d; }
.dim { color: #6b7280; }
ul { margin: 0 0 12px; padding-left: 24px; }
li { font-size: 22px; line-height: 1.4; margin-bottom: 9px; max-width: 62ch; color: #2b2f38; }
li .dim { font-size: 20px; }
.cover { justify-content: center; }
.cover h1 { font-size: 66px; margin-bottom: 24px; }
.meta { font-size: 21px; color: #6b7280; line-height: 1.55; }
.spacer { flex: 1; }
.note { font-size: 18px; color: #6b7280; margin-top: 14px; max-width: 92ch; }
.big { font-size: 74px; font-weight: 700; letter-spacing: -.03em; line-height: 1; margin: 4px 0 2px; }
.statrow { display: flex; gap: 56px; margin: 22px 0 8px; align-items: flex-end; }
.stat .label {
  font-size: 16px; color: #6b7280; text-transform: uppercase; letter-spacing: .07em;
  font-weight: 600;
}
.stat .sub { font-size: 17px; color: #9aa1ad; margin-top: 4px; }
.pos { color: #15803d; }
.neg { color: #b91c1c; }
.arrow { font-size: 44px; color: #c7ccd6; padding-bottom: 14px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; }
table { border-collapse: collapse; width: 100%; margin-top: 4px; }
th, td { padding: 9px 12px; text-align: right; font-size: 20px; border-bottom: 1px solid #e5e7eb; }
th:first-child, td:first-child { text-align: left; }
thead th {
  font-size: 15px; text-transform: uppercase; letter-spacing: .07em;
  color: #6b7280; border-bottom: 2px solid #16181d;
}
.refs li { font-size: 21px; margin-bottom: 11px; }
.refs .src { color: #6b7280; font-size: 18px; }
figure {
  margin: 0; flex: 1; min-height: 0; max-height: 400px;
  display: flex; flex-direction: column; justify-content: center;
}
figure img { display: block; max-width: 100%; max-height: 100%; margin: 0 auto; }
.missing {
  border: 2px dashed #d1d5db; border-radius: 8px; padding: 40px;
  text-align: center; color: #9aa1ad; font-size: 19px;
}
.compact th, .compact td { padding: 6px 12px; font-size: 18px; }
.compact thead th { font-size: 14px; }
.cards { display: flex; gap: 20px; margin: 4px 0 10px; }
.card {
  flex: 1; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px;
  display: flex; flex-direction: column; min-width: 0;
}
.card .thumb {
  height: 74px; display: flex; align-items: center; justify-content: center;
  background: #f7f8fa; border-radius: 5px; margin-bottom: 8px; overflow: hidden;
}
.card .thumb img { max-height: 68px; max-width: 100%; }
.card .thumb .none { color: #b6bcc7; font-size: 15px; }
.card .id { font-size: 13px; color: #9aa1ad; letter-spacing: .04em; margin-bottom: 7px; }
.card .row { font-size: 16px; line-height: 1.3; margin-bottom: 6px; color: #2b2f38; }
.card .row .k {
  display: block; font-size: 13px; text-transform: uppercase; letter-spacing: .07em;
  color: #6b7280; font-weight: 600; margin-bottom: 2px;
}
.card .row.bad { color: #b91c1c; }
.two { display: flex; gap: 44px; }
.two > div { flex: 1; min-width: 0; }
"""


# --- loading -----------------------------------------------------------------


def load_summary(path):
    if not path.exists():
        raise SystemExit(
            f"no summary at {path}\n"
            "The deck is built only from the scored results. Run the scoring and "
            "summarize steps first, or pass --summary to point at another file."
        )
    with path.open() as fh:
        return json.load(fh)


def load_manifest(path):
    """Return the manifest items keyed by id, or an empty mapping if absent."""
    if not path.exists():
        return {}
    with path.open() as fh:
        doc = json.load(fh)
    return {item["id"]: item for item in doc.get("items", [])}


def data_uri(path):
    """Return a base64 data URI for a PNG, or None when the file is not there."""
    if not path or not Path(path).exists():
        return None
    raw = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


# --- small helpers -----------------------------------------------------------


def esc(text):
    return html.escape(str(text))


def model_label(model_id):
    """Shorten a Hugging Face id to the name that fits on a slide."""
    name = model_id.split("/")[-1]
    for suffix in ("-Instruct", "-instruct"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def pick_model(accuracy):
    """Choose the model the headline slides report, preferring the largest Qwen2-VL."""
    if not accuracy:
        raise SystemExit("summary.json has no accuracy block, nothing to report")
    for candidate in PREFERRED_MODELS:
        if candidate in accuracy:
            return candidate
    three = [m for m, conds in accuracy.items() if len(conds) >= 3]
    return sorted(three or accuracy)[0]


def pct(value):
    return f"{value * 100:.0f}%" if isinstance(value, (int, float)) else "n/a"


def agreement_vs_script(agreement):
    """One clause per human rater giving their agreement with the rule-based scorer."""
    bits = []
    for col, got in (agreement.get("versus_script") or {}).items():
        name = col.replace("_correct", "").replace("_", " ").strip() or "rater"
        bits.append(f" {name} versus the script, {got['n']} items: {pct1(got['percent'])} agreement, kappa {got['cohen_kappa']:.2f}.")
    return "".join(bits)


def pct1(value):
    return f"{value * 100:.1f}%" if isinstance(value, (int, float)) else "n/a"


def get_acc(summary, model, condition, category):
    return (
        summary.get("accuracy", {})
        .get(model, {})
        .get(condition, {})
        .get(category)
    )


def severity_counts(summary, model, condition, category):
    return (
        summary.get("severity", {})
        .get(model, {})
        .get(condition, {})
        .get(category, {})
    )


def conditions_for(summary, model):
    present = set(summary.get("accuracy", {}).get(model, {}))
    return [c for c in CONDITION_ORDER if c in present]


def category_counts(summary, manifest):
    counts = dict(summary.get("by_category") or {})
    if not counts and manifest:
        for item in manifest.values():
            counts[item["category"]] = counts.get(item["category"], 0) + 1
    return counts


def figure_block(figures_dir, name, alt):
    uri = data_uri(Path(figures_dir) / name)
    if uri:
        return f'<figure><img src="{uri}" alt="{esc(alt)}"></figure>'
    return (
        f'<figure><div class="missing">Chart not built yet: {esc(name)}<br>'
        "Run the plotting step, then rebuild the deck.</div></figure>"
    )


# --- slide fragments ---------------------------------------------------------


def category_table(counts):
    rows = []
    for cat in CATEGORY_ORDER:
        if cat not in counts:
            continue
        rows.append(
            f"<tr><td>{CATEGORY_LABELS[cat]}</td><td>{counts[cat]}</td>"
            f"<td class='dim'>{esc(CATEGORY_RULES[cat])}</td></tr>"
        )
    if not rows:
        return "<p class='dim'>No category counts recorded.</p>"
    return (
        "<table><thead><tr><th>Category</th><th>Images</th>"
        "<th style='text-align:right'>Correct alt is</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


CATEGORY_RULES = {
    "functional": "the action or destination",
    "informative": "the meaning the image carries",
    "decorative": "empty",
    "image_of_text": "the text, transcribed",
    "complex": "a short label plus the data",
}


def condition_stat_row(summary, model, category, conditions):
    """Three big numbers, one per condition, with the arrows between them."""
    parts = []
    for i, cond in enumerate(conditions):
        value = get_acc(summary, model, cond, category)
        if i:
            parts.append('<div class="arrow">&rarr;</div>')
        parts.append(
            '<div class="stat">'
            f'<div class="label">{CONDITION_LABELS[cond]}</div>'
            f'<div class="big">{pct(value)}</div>'
            "</div>"
        )
    return f'<div class="statrow">{"".join(parts)}</div>'


def accuracy_table(summary, model, conditions, categories):
    head = "".join(f"<th>{CATEGORY_LABELS[c]}</th>" for c in categories)
    rows = []
    for cond in conditions:
        cells = []
        for cat in categories:
            cells.append(f"<td>{pct(get_acc(summary, model, cond, cat))}</td>")
        overall = pct(get_acc(summary, model, cond, "all"))
        rows.append(
            f"<tr><td>{CONDITION_LABELS[cond]}</td>{''.join(cells)}<td>{overall}</td></tr>"
        )
    return (
        f"<table><thead><tr><th>Condition</th>{head}<th>All</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def severity_table(summary, model, conditions, category):
    rows = []
    for cond in conditions:
        counts = severity_counts(summary, model, cond, category)
        cells = "".join(f"<td>{counts.get(s, 0)}</td>" for s in SEVERITY_ORDER)
        rows.append(f"<tr><td>{CONDITION_LABELS[cond]}</td>{cells}</tr>")
    head = "".join(f"<th>{SEVERITY_LABELS[s]}</th>" for s in SEVERITY_ORDER)
    return (
        f"<table class='compact'><thead><tr><th>Condition</th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def example_cards(summary, manifest, images_dir, severity, limit=3):
    """Cards for the worst examples: thumbnail, expected alt, model alt."""
    picked = (summary.get("examples") or {}).get(severity) or []
    if not picked:
        return "<p class='dim'>No examples of this kind were recorded.</p>"

    cards = []
    for ex in picked[:limit]:
        item = manifest.get(ex.get("id"), {})
        file_name = item.get("file")
        thumb_uri = None
        if file_name:
            candidate = Path(images_dir).parent / file_name
            if not candidate.exists():
                candidate = Path(images_dir) / Path(file_name).name
            thumb_uri = data_uri(candidate)
        thumb = (
            f'<img src="{thumb_uri}" alt="">'
            if thumb_uri
            else '<span class="none">image not found</span>'
        )
        expected = item.get("expected_alt")
        expected_text = f'"{expected}"' if expected else "empty, by design" if expected == "" else "not recorded"
        got = (ex.get("alt") or "").strip()
        got_text = f'"{got}"' if got else "nothing at all"
        cards.append(
            '<div class="card">'
            f'<div class="thumb">{thumb}</div>'
            f'<div class="id">{esc(ex.get("id", ""))} &middot; '
            f'{esc(CONDITION_LABELS.get(ex.get("condition", ""), ex.get("condition", "")))}</div>'
            f'<div class="row"><span class="k">Correct alt</span>{esc(expected_text)}</div>'
            f'<div class="row bad"><span class="k">Model alt</span>{esc(got_text)}</div>'
            "</div>"
        )
    return f'<div class="cards">{"".join(cards)}</div>'


# --- the deck ----------------------------------------------------------------


def slides(summary, manifest, images_dir, figures_dir):
    accuracy = summary.get("accuracy") or {}
    model = pick_model(accuracy)
    label = model_label(model)
    conditions = conditions_for(summary, model)
    prompt_conditions = [c for c in conditions if c != "caption"]
    headline = [c for c in ("naive", "wcag", "wcag_context") if c in conditions]

    counts = category_counts(summary, manifest)
    categories = [c for c in CATEGORY_ORDER if c in counts] or CATEGORY_ORDER
    n_items = summary.get("n_items") or sum(counts.values())
    n_models = len(accuracy)
    model_list = ", ".join(model_label(m) for m in sorted(accuracy))

    naive_f = get_acc(summary, model, "naive", "functional")
    wcag_f = get_acc(summary, model, "wcag", "functional")
    ctx_f = get_acc(summary, model, "wcag_context", "functional")

    def delta_words(a, b):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return "not measured"
        points = (b - a) * 100
        if points > 0.5:
            return f"up {points:.0f} points"
        if points < -0.5:
            return f"down {abs(points):.0f} points"
        return "flat"

    wcag_move = delta_words(naive_f, wcag_f)
    _acc = summary["accuracy"].get(model, {})
    _bits = []
    for _cat, _label in (("decorative", "decorative"), ("image_of_text", "image of text")):
        _w = _acc.get("wcag", {}).get(_cat); _c = _acc.get("wcag_context", {}).get(_cat)
        if isinstance(_w, (int, float)) and isinstance(_c, (int, float)):
            _bits.append(f"{_label} {_w * 100:.0f}% to {_c * 100:.0f}%")
    ctx_cost = ("Accuracy on " + " and ".join(_bits) + ".") if _bits else ""
    ctx_move = delta_words(wcag_f, ctx_f)

    silent_wcag = severity_counts(summary, model, "wcag", "functional").get("silent", 0)
    silent_naive = severity_counts(summary, model, "naive", "functional").get("silent", 0)
    n_functional = counts.get("functional", 0)

    agreement = summary.get("agreement") or {}
    kappa = agreement.get("cohen_kappa")
    kappa_text = f"{kappa:.2f}" if isinstance(kappa, (int, float)) else "not recorded"
    agree_pct = agreement.get("percent")
    agree_text = pct1(agree_pct / 100 if isinstance(agree_pct, (int, float)) and agree_pct > 1 else agree_pct)
    agree_n = agreement.get("n", 0)
    versus = agreement_vs_script(agreement)
    if agree_n:
        rater_short = f"Two human raters scored {agree_n} items independently."
        rater_long = (f"Two human raters scored {agree_n} items: {esc(agree_text)} agreement, "
                      f"Cohen kappa {esc(kappa_text)}.{esc(versus)}")
    elif versus:
        rater_short = "A human rater scored a 30 item subset against the script."
        rater_long = f"Human check on the scorer:{esc(versus)} A second rater is still to come."
    else:
        rater_short = "A 30 item subset is set aside for a second rater."
        rater_long = "The 30 item second rater subset is in the repo and not yet scored, so no agreement number is claimed."

    deck = []

    # 1
    deck.append(
        f"""<!--
Speaker notes. Open on the sentence that carries the whole talk: an alt text generator can
be fluent, accurate about the pixels, and still leave a button silent. Point at the three
numbers and say that the middle one is the surprise, because that is the run where the model
was told to follow the accessibility rules. Do not explain the categories yet, that is slide
five. Thirty seconds here, no more.
-->
<section class="cover">
  <div class="kicker">MSCS2201 Advanced AI and ML &middot; Sofia University &middot; Summer 2026</div>
  <h1>Alt text is not a caption</h1>
  <p class="lead">Vision models describe pixels. Accessibility needs function. Telling a model to follow WCAG fixes the visible failures and creates an invisible one.</p>
  {condition_stat_row(summary, model, "functional", headline)}
  <p class="note">Accuracy on functional images (icons, buttons, linked logos), {esc(label)}, n = {n_items}. WCAG prompt {esc(wcag_move)}. Adding page context {esc(ctx_move)}.</p>
  <div class="spacer"></div>
  <div class="meta">Can Sirin &middot; {REPO_URL[8:]}</div>
</section>"""
    )

    # 2
    deck.append(
        f"""<!--
Speaker notes. Ground the problem in a person, not a metric. A screen reader user hits an
image with no text alternative and gets either silence or a filename. WCAG 1.1.1 is the rule
that says every non-text element needs an equivalent, and the equivalent for a button is what
it does. Say that this is shipping code already, not a thought experiment: Facebook has been
generating alt text automatically since 2016 and Office and browsers do it now. Bad generated
alt is worse than none, because it looks handled.
-->
<section>
  <div class="kicker">Why this matters</div>
  <h2>Generated alt text is already in production</h2>
  <ul>
    <li>A screen reader announces the alt attribute. When it is missing the user gets a filename or silence, and when it is wrong the user gets a confident wrong answer.</li>
    <li>WCAG 1.1.1 Non-text Content asks for a text alternative that serves the <em>equivalent purpose</em>. For a control, the purpose is the action, not the picture.</li>
    <li>Facebook shipped automatic alt text in 2016. Microsoft Office suggests alt text. Browsers and screen readers now describe images on their own.</li>
    <li>So the question is no longer whether machines will write alt text. It is whether what they write is usable, and where it breaks.</li>
  </ul>
  <p class="note">{WCAG_URL}</p>
</section>"""
    )

    # 3
    deck.append(
        f"""<!--
Speaker notes. Walk the captioning line quickly, one sentence each, and make the shape of it
obvious: the field got much better at describing what is in a picture. Show and Tell set the
encoder-decoder pattern, BLIP and BLIP-2 scaled pretraining, LLaVA and Qwen2-VL turned
captioning into instruction following, which is what makes the prompting conditions in this
work possible at all. The point to land is that every one of these optimises description.
-->
<section>
  <div class="kicker">Literature review, 1 of 2</div>
  <h2>The captioning line got very good at describing pixels</h2>
  <ul class="refs">
    <li>Vinyals et al., Show and Tell, CVPR 2015. <span class="src">Encoder-decoder captioning, the pattern everything after it inherits.</span></li>
    <li>Li et al., BLIP, ICML 2022. <span class="src">Bootstrapped image-text pretraining, one model for understanding and generation.</span></li>
    <li>Li et al., BLIP-2, ICML 2023. <span class="src">A light query transformer bridges a frozen vision encoder to a frozen language model.</span></li>
    <li>Liu et al., LLaVA, NeurIPS 2023. <span class="src">Visual instruction tuning. The model now follows an instruction about the image, not just a caption objective.</span></li>
    <li>Wang et al., Qwen2-VL, 2024. <span class="src">Dynamic resolution, strong text reading in images, small enough to run locally.</span></li>
  </ul>
  <p class="note">The objective across all of them is description quality. None of them is trained on what an image is for on a page.</p>
</section>"""
    )

    # 4
    deck.append(
        f"""<!--
Speaker notes. The accessibility line asked a different question and got different answers.
VizWiz put real blind photographers in the loop. Wu and colleagues shipped automatic alt text
to a billion users and reported what happened. Gleason measured alt text in the wild on
Twitter and found almost nobody writes it. Stangl asked blind users what they actually want
and the answer depends on the page. Then land the metric critique hard: BLEU, CIDEr and SPICE
all score overlap with reference descriptions, and none of them can see whether a button is
usable. That gap is the reason this project has its own scorer.
-->
<section>
  <div class="kicker">Literature review, 2 of 2</div>
  <h2>The accessibility line asked a different question</h2>
  <ul class="refs">
    <li>Gurari et al., VizWiz Grand Challenge, CVPR 2018, and VizWiz-Captions, ECCV 2020. <span class="src">Images taken by blind people, the canonical accessibility vision dataset.</span></li>
    <li>Wu et al., Automatic Alt-Text, CSCW 2017. <span class="src">Facebook shipping generated descriptions, and what users made of them.</span></li>
    <li>Gleason et al., WWW 2019. <span class="src">Alt text in the wild on Twitter: roughly 0.1 percent of images carried a description.</span></li>
    <li>Stangl et al., CHI 2020. <span class="src">What blind and low vision users want depends on where the image sits.</span></li>
    <li>BLEU, CIDEr, SPICE. <span class="src">All measure overlap with reference descriptions. None can see functional adequacy.</span></li>
  </ul>
  <p class="note">Kreiss et al., EMNLP 2022, make the same point directly: context matters for image descriptions, and the standard metrics do not carry it.</p>
</section>"""
    )

    # 5
    deck.append(
        f"""<!--
Speaker notes. This is the gap slide, so slow down. W3C publishes a decision tree that sorts
every image on the web into a handful of categories, and the correct alt text is a different
kind of thing in each one. Empty is the right answer for a decorative image. A verb is the
right answer for a button. No captioning benchmark is organized this way, so no benchmark
reports the one number that matters most, which is whether a control is usable. Say the
category counts out loud so the audience knows the set is balanced.
-->
<section>
  <div class="kicker">The gap</div>
  <h2>No benchmark is organized by what the image is for</h2>
  <p>The W3C alt decision tree sorts web images into categories, and the correct answer is a different kind of thing in each one.</p>
  {category_table(counts)}
  <p class="note">{n_items} images. Functional is the category where a wrong answer costs the most, because the user cannot operate the page, and it is the category no captioning benchmark separates out. {DECISION_TREE_URL}</p>
</section>"""
    )

    # 6
    deck.append(
        f"""<!--
Speaker notes. Method slide, keep it to a minute. Images are generated as HTML and
screenshotted, which means no rights questions and the correct answer is known exactly rather
than guessed. Three prompting conditions on the same images isolate the prompt as the
variable. Scoring is rule based against per-item keyword requirements, plus a severity label,
because an empty alt on a live control and a wordy but correct one are not the same mistake.
A second rater subset is set aside and the agreement number, once scored, lands on the limitations slide.
-->
<section>
  <div class="kicker">Approach</div>
  <h2>One image set, three prompts, one scorer</h2>
  <div class="two">
    <div>
      <p><strong>Images.</strong> {n_items} generated as HTML and captured with headless Chrome, so the correct alt text is known rather than inferred, and there are no licensing questions.</p>
      <p><strong>Conditions.</strong> {esc(", ".join(CONDITION_LABELS[c] for c in prompt_conditions))}. Same images, same decoding, only the prompt changes. The context condition adds the element tag, its HTML, and nearby text.</p>
    </div>
    <div>
      <p><strong>Models.</strong> {esc(model_list)}. BLIP is the pure captioner baseline.</p>
      <p><strong>Scoring.</strong> Rule based against per-item required and forbidden keywords, plus a severity label: correct, harmless, degraded, silent, misleading. {rater_short}</p>
    </div>
  </div>
  <p class="note">Code {REPO_URL} &middot; decision tree {DECISION_TREE_URL} &middot; models on Hugging Face: {esc(model_list)}</p>
</section>"""
    )

    # 7
    deck.append(
        f"""<!--
Speaker notes. This is the money chart, so stop talking and let people read it. Trace the
line with a finger: naive, then the WCAG prompt, then the WCAG prompt with page context.
The dip in the middle is the whole result. Say plainly that the drop happens because the
model applied the decorative rule to things that are not decorative, and that it applied it
because the prompt told it the rule exists.
-->
<section>
  <div class="kicker">Results, the main effect</div>
  <h2>Telling the model the rules made functional images worse</h2>
  {figure_block(figures_dir, "fig_functional_by_condition.png", "Functional accuracy by condition")}
  <p class="note">Functional accuracy, {esc(label)}, {n_functional} functional images. Naive {pct(naive_f)}, WCAG prompt {pct(wcag_f)} ({esc(wcag_move)}), WCAG plus context {pct(ctx_f)} ({esc(ctx_move)} against the WCAG prompt).</p>
</section>"""
    )

    # 8
    deck.append(
        f"""<!--
Speaker notes. The heatmap shows the trade being made. The WCAG prompt lifts decorative,
image of text and complex, which is exactly what it was written to do, and it is the only
column that goes the other way that matters. Note that the overall number barely moves
between conditions, which is why an aggregate score hides this entirely. That is the
argument for reporting per category.
-->
<section>
  <div class="kicker">Results, by category</div>
  <h2>The prompt trades one category for another</h2>
  {figure_block(figures_dir, "fig_accuracy_heatmap.png", "Accuracy by category and condition")}
  {accuracy_table(summary, model, prompt_conditions, categories)}
  <p class="note">{esc(label)}. An aggregate score hides the trade, because the categories move in opposite directions.</p>
</section>"""
    )

    # 9
    deck.append(
        f"""<!--
Speaker notes. This is the slide people remember, so give it time. A wrong description is
annoying and the user routes around it. An empty alt on a live control is different in kind:
the screen reader says nothing, and the user does not learn the button exists. Read one
example out loud, the correct alt and then what the model produced. Make the severity point
explicitly, that correctness alone would score these two failures the same.
-->
<section>
  <div class="kicker">The failure that matters</div>
  <h2>Silent alt on a real control</h2>
  <p>An empty alt hides the control completely. The naive run left {silent_naive} functional images silent, the WCAG run left {silent_wcag} of {n_functional}.</p>
  {example_cards(summary, manifest, images_dir, "silent")}
  {severity_table(summary, model, prompt_conditions, "functional")}
  <p class="note">{esc(label)}, functional images only. Severity is what a correctness score cannot see.</p>
</section>"""
    )

    # 10
    deck.append(
        f"""<!--
Speaker notes. The recovery slide, and the reason the finding is useful rather than just
alarming. Purpose is not in the pixels. A magnifying glass is a magnifying glass until we
know it sits inside a submit button next to the word Search. Feed the model that, and
functional accuracy moves. Say what the practical recommendation is: an alt text generator
that only sees the image is solving the wrong problem, and the fix is cheap, because a
browser extension already has the DOM.
-->
<section>
  <div class="kicker">Does context fix it</div>
  <h2>Purpose is in the DOM, not the pixels</h2>
  {condition_stat_row(summary, model, "functional", [c for c in ("wcag", "wcag_context") if c in conditions])}
  <p>Same model, same images, same rules in the prompt. The only addition is the element tag, its HTML, and the text next to it. Functional accuracy goes {esc(ctx_move)}.</p>
  {figure_block(figures_dir, "fig_severity_stack.png", "Severity mix by condition")}
  <p class="note">Not a free win at this size: with context the model over-reads the page. {esc(ctx_cost)} The practical version still holds: a generator that sees only the image cannot recover interactive purpose, and anything running in a browser already has the DOM.</p>
</section>"""
    )

    # 11
    deck.append(
        f"""<!--
Speaker notes. Say the limits before anyone asks, it costs nothing and buys credibility.
Generated images are clean, and real web images are messier, so the numbers are a ceiling.
One model family means this measures Qwen2-VL and not vision models in general. The scorer is
rules, and rules encode judgment calls, which are written down in the repo rather than left
implicit. Give the agreement number as it is, whatever it is.
-->
<section>
  <div class="kicker">Limitations</div>
  <h2>What this does not show</h2>
  <ul>
    <li>Images are generated, not scraped. Clean and unambiguous, so these numbers are an upper bound on real web images.</li>
    <li>{n_models} model{"s" if n_models != 1 else ""} evaluated, one family plus a captioner baseline. This is not a claim about vision models in general.</li>
    <li>Scoring is rule based on per-item keywords. The judgment calls are in the repo, not hidden: partial credit rules, what counts as a synonym, how padding is treated.</li>
    <li>n = {n_items}, so per-category cells are small. {rater_long}</li>
  </ul>
  <p class="note">The effect on functional images is large enough to survive all of this. The exact percentages are not the claim, the direction is.</p>
</section>"""
    )

    # 12
    deck.append(
        f"""<!--
Speaker notes. Close on the one sentence you want repeated back. Prompting a model toward
compliance does not produce accessibility, it moves the failure somewhere nobody is looking.
The reason is structural, not a prompting bug: interactive purpose is not a visual property.
Point at the repo, say everything in the deck is generated from the results file, and stop.
-->
<section>
  <div class="kicker">Takeaway</div>
  <h2>Compliance prompting moves the failure out of sight</h2>
  <p class="lead">A model can apply the decorative rule and the text rule. It cannot infer what a control does, because that is not a visual property.</p>
  <p>The visible failure, a description where a verb belonged, becomes an invisible one: nothing announced at all. Correctness scores rate these the same. Users do not.</p>
  <p>The fix is not a better prompt. It is giving the model the context that carries function, which anything running in a page already has.</p>
  <div class="spacer"></div>
  <p class="meta">{REPO_URL}<br><span class="dim">Image generator, model runs, scorer, and the summary file every number in this deck is read from.</span></p>
</section>"""
    )

    return deck


def build(summary, manifest, images_dir, figures_dir):
    body = []
    for i, section in enumerate(slides(summary, manifest, images_dir, figures_dir), start=1):
        body.append(section.replace("<section", f'<section data-page="{i}"', 1))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Alt text is not a caption</title>"
        f"<style>{CSS}</style></head><body>{''.join(body)}</body></html>"
    )


def main():
    parser = argparse.ArgumentParser(description="Build the slide deck from the scored results.")
    parser.add_argument(
        "--summary",
        default=os.environ.get("ALT_TEXT_SUMMARY", str(ROOT / "results" / "summary.json")),
    )
    parser.add_argument("--manifest", default=str(ROOT / "data" / "manifest.json"))
    parser.add_argument("--images", default=str(ROOT / "data" / "images"))
    parser.add_argument("--figures", default=str(HERE))
    parser.add_argument("--out", default=str(HERE / "slides.html"))
    args = parser.parse_args()

    summary = load_summary(Path(args.summary))
    manifest = load_manifest(Path(args.manifest))

    missing = [f for f in FIGURES if not (Path(args.figures) / f).exists()]
    if missing:
        print("figures not found, placeholders will be drawn: " + ", ".join(missing))

    html_text = build(summary, manifest, args.images, args.figures)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text)
    print(f"wrote {out} (12 slides) from {args.summary}")


if __name__ == "__main__":
    main()
