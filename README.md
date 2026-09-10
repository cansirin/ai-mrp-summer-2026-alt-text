# Alt text is not a caption

Vision-language models are being used to write alt text, the short description a screen reader
announces in place of an image. They are trained to describe what a picture looks like, but
accessibility asks a different question. For an icon inside a button, the correct alt text is
the action the button performs, not a description of the icon. For a purely decorative image,
the correct alt text is nothing at all. This project builds a benchmark of web images labeled
by the category the W3C alt decision tree assigns, runs vision-language models over it under
three prompting conditions, and scores the output against what each category actually
requires.

## Thesis

Prompting a model toward WCAG compliance does not produce accessible output, it trades a
visible failure for an invisible one. A model can learn to apply the decorative rule and the
text rule from a prompt, but it cannot infer what a control does, because interactive purpose
is not a property of the pixels, it lives in the DOM and the surrounding page.

## Reproducing

Set up the environment once.

    python3 -m venv .venv
    .venv/bin/pip install -e .

Then run the pipeline in order. Each step reads and writes only the files named in
docs/formats.md, so any step can be rerun on its own.

    .venv/bin/python scripts/make_dataset.py          # data/images and data/manifest.json
    scripts/run_all.sh                                # results/raw/<model>__<condition>.json
    .venv/bin/python scripts/score.py                 # results/scores.json
    .venv/bin/python scripts/summarize.py             # results/summary.json
    .venv/bin/python scripts/plot.py                  # presentation/fig_*.png
    .venv/bin/python presentation/build_deck.py       # presentation/slides.html

Export the deck to PDF with headless Chrome.

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        --headless --disable-gpu --no-pdf-header-footer \
        --print-to-pdf=presentation/slides.pdf presentation/slides.html

Model runs are resumable. If a run is interrupted, rerunning the same command skips the items
already written and continues. Add --limit N to any run for a quick smoke test.

## Repo layout

    data/images/            the benchmark images, one PNG per item
    data/manifest.json      per-item category, expected alt text, keyword rules, DOM context
    scripts/                dataset generation, model runs, scoring, summarizing, plotting
    results/raw/            one file per model and condition, raw model output
    results/scores.json     per-item correctness and severity
    results/summary.json    the aggregated numbers, the only source the deck reads
    results/human_subset.csv  the 30 item subset set aside for a second rater
    presentation/           build_deck.py, the figures, slides.html, slides.pdf
    docs/formats.md        the file formats every script agrees on
    docs/literature.md      annotated literature review with citations and links

## Design

Images are generated as HTML and captured with headless Chrome rather than scraped. That means
the correct alt text for every item is known exactly instead of being inferred after the fact,
and there are no licensing questions about the set.

Five categories from the W3C alt decision tree
(https://www.w3.org/WAI/tutorials/images/decision-tree/): functional, informative, decorative,
image of text, and complex. Three prompting conditions on the same images: a naive request for
alt text, a WCAG-informed prompt that states the rules, and the same WCAG prompt with the
element tag, its HTML, and nearby text appended.

Scoring is rule based, against the per-item required and forbidden keywords in the manifest,
and every item also gets a severity label: correct, harmless, degraded, silent, or misleading.
The severity axis exists because a wordy but accurate description and an empty alt on a live
control are both wrong and are not the same mistake. A 30 item subset is set aside for a second
rater. When results/human_ratings.csv is filled in, summarize.py reports the agreement.

## Results

See presentation/slides.pdf. Every number in the deck is read from results/summary.json at
build time, so the slides cannot drift from the scored output. Rerun the scoring and rebuild to
refresh them.

## Related work

docs/literature.md covers the captioning line (Show and Tell, BLIP, BLIP-2, LLaVA, Qwen2-VL),
the accessibility line (VizWiz, Facebook automatic alt text, alt text in the wild on Twitter,
what blind users want from descriptions), and why BLEU, CIDEr and SPICE cannot measure whether
alt text is functionally adequate.

## Course

MSCS2201 Advanced AI and ML, Sofia University, Summer 2026, Mini Research Problem.
Author: Can Sirin.
