# Data contract

Every script reads and writes only these files. The deck is built from
results/summary.json and nothing else, so numbers cannot drift.

## data/manifest.json

    {
      "version": 1,
      "items": [
        {
          "id": "functional_0001",
          "file": "images/functional_0001.png",
          "category": "functional",        // functional | informative | decorative | image_of_text | complex
          "expected_alt": "Search",         // "" for decorative
          "must_include": ["search"],       // lowercase keywords a correct alt must contain; [] allowed
          "must_not_include": ["magnifying"], // appearance words that signal a describe-not-function failure; [] allowed
          "context": {                      // the DOM around the image, given to the model in the context condition
            "tag": "button",
            "html": "<button type=\"submit\" class=\"btn\"><img src=\"...\"></button>",
            "nearby_text": "Search products"
          },
          "notes": "free text, provenance or generation params"
        }
      ]
    }

Rules: ids are category prefix plus 4 digit index. Images are PNG, 1x, natural size
between 64 and 1200 px on the long side. Decorative items have expected_alt "" and
must_include []. Image-of-text items put the exact visible text in expected_alt.
Complex items put title plus the key data values in must_include.

## results/raw/<model>__<condition>.json

    {
      "model": "Qwen/Qwen2-VL-2B-Instruct",
      "condition": "naive",                // naive | wcag | wcag_context   (blip: caption only)
      "prompt": "the exact prompt text, {context} substituted per item",
      "device": "mps",
      "load_sec": 94.1,
      "outputs": { "<item id>": { "alt": "raw model text", "sec": 1.2 } }
    }

Model file stem is the model id with "/" replaced by "__".

## results/scores.json

    {
      "rows": [
        {
          "id": "...", "model": "...", "condition": "...", "category": "...",
          "alt": "the model text",
          "correct": true,
          "severity": "correct",           // correct | harmless | degraded | silent | misleading
          "rule": "empty_expected",        // which scorer rule or judge decided
          "reason": "one line"
        }
      ]
    }

Severity definitions:
  correct     meets the category requirement
  harmless    wordy or slightly off but a screen reader user gets the right idea
  degraded    describes appearance, purpose is guessable but not stated
  silent      empty alt on an item that needed alt (a real control or informative image)
  misleading  confidently wrong content, hallucinated objects or wrong text

## results/summary.json

    {
      "n_items": 240,
      "by_category": {"functional": 60, ...},
      "accuracy": { "<model>": { "<condition>": { "<category>": 0.83, "all": 0.71 } } },
      "severity": { "<model>": { "<condition>": { "<category>": {"correct": 50, "silent": 7, ...} } } },
      "agreement": { "n": 30, "raters": ["author", "second"], "cohen_kappa": 0.0, "percent": 0.0 },
      "examples": { "<severity>": [ {"id": "...", "model": "...", "condition": "...", "alt": "..."} ] }
    }

## results/human_subset.csv

Thirty items sampled across categories and conditions for two human raters.
Columns: id, file, category, expected_alt, model, condition, alt, rater_correct, rater_severity, rater_notes.
