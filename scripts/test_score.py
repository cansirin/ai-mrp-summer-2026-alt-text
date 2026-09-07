"""Checks for the scoring rules in score.py.

Run with pytest:

    .venv/bin/python -m pytest scripts/test_score.py

or directly, which uses a small built in runner:

    python scripts/test_score.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from score import (  # noqa: E402
    is_empty_alt,
    keyword_present,
    normalize_alt,
    score_alt,
    similarity,
    stem,
)

SEARCH_BUTTON = {
    "id": "functional_0001",
    "category": "functional",
    "expected_alt": "Search",
    "must_include": ["search"],
    "must_not_include": ["magnifying", "magnifying glass", "blue"],
}

TRASH_ICON = {
    "id": "functional_0002",
    "category": "functional",
    "expected_alt": "Delete",
    "must_include": ["delete"],
    "must_not_include": ["trash can", "red"],
}

DIVIDER = {
    "id": "decorative_0001",
    "category": "decorative",
    "expected_alt": "",
    "must_include": [],
    "must_not_include": [],
}

LOGO = {
    "id": "image_of_text_0001",
    "category": "image_of_text",
    "expected_alt": "Binclusive.",
    "must_include": ["binclusive"],
    "must_not_include": [],
}

CHART = {
    "id": "complex_0001",
    "category": "complex",
    "expected_alt": "Caption errors per 1000 words: alpha 48, beta 21, gamma 39",
    "must_include": ["caption", "errors", "48", "21", "39"],
    "must_not_include": [],
}

DOG_PHOTO = {
    "id": "informative_0001",
    "category": "informative",
    "expected_alt": "A golden retriever carrying a stick across a lawn",
    "must_include": ["dog", "stick"],
    "must_not_include": [],
}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


# Normalization


def test_normalize_strips_boilerplate():
    check(normalize_alt("  An image of a Search button. ") == "search button",
          normalize_alt("  An image of a Search button. "))
    check(normalize_alt('"Binclusive."') == "binclusive", normalize_alt('"Binclusive."'))
    check(normalize_alt("Alt text: A picture of a red trash can") == "red trash can",
          normalize_alt("Alt text: A picture of a red trash can"))
    check(normalize_alt(None) == "", "None should normalize to an empty string")


def test_empty_markers():
    for value in ["", "  ", "EMPTY", "empty", "Empty.", "none", "None", "N/A",
                  "(decorative)", "null", '""', "alt=\"\"", "no alt text"]:
        check(is_empty_alt(value), f"{value!r} should read as an empty alt")
    for value in ["Search", "a red trash can", "empty shopping cart icon"]:
        check(not is_empty_alt(value), f"{value!r} should not read as an empty alt")


def test_stemming_and_synonyms():
    check(stem("searching") == "search", stem("searching"))
    check(keyword_present("search", "searching the catalogue"), "searching matches search")
    check(keyword_present("delete", "remove this row"), "remove matches delete")
    check(keyword_present("menu", "open navigation"), "navigation matches menu")
    check(not keyword_present("delete", "a red icon"), "no action word present")


def test_similarity():
    check(similarity("binclusive", "binclusive") == 1.0, "identical strings")
    check(similarity("binclusive", "binclusiv") >= 0.85, "one character short still matches")
    check(similarity("binclusive", "a bird flying") < 0.5, "unrelated strings")


# Decorative


def test_decorative_empty_is_correct():
    result = score_alt(DIVIDER, "Empty")
    check(result["correct"] is True, result)
    check(result["severity"] == "correct", result)


def test_decorative_short_description_is_harmless():
    result = score_alt(DIVIDER, "A decorative swash divider")
    check(result["correct"] is False, result)
    check(result["severity"] == "harmless", result)


def test_decorative_long_description_is_degraded():
    long_alt = ("there is a picture of a white background with a line of thread and a "
                "small dot in the middle of the frame")
    result = score_alt(DIVIDER, long_alt)
    check(result["severity"] == "degraded", result)


# Functional


def test_functional_action_named_is_correct():
    result = score_alt(SEARCH_BUTTON, "Search")
    check(result["correct"] is True, result)
    check(result["severity"] == "correct", result)


def test_functional_synonym_counts():
    result = score_alt(TRASH_ICON, "Remove item")
    check(result["correct"] is True, result)


def test_functional_empty_is_silent():
    result = score_alt(SEARCH_BUTTON, "Empty")
    check(result["correct"] is False, result)
    check(result["severity"] == "silent", result)


def test_functional_appearance_is_degraded():
    result = score_alt(SEARCH_BUTTON,
                       "a close up of a cell phone with a magnifying glass on it")
    check(result["correct"] is False, result)
    check(result["severity"] == "degraded", result)


def test_functional_hallucination_is_misleading():
    result = score_alt(TRASH_ICON, "a close up of a bird flying in the air")
    check(result["severity"] == "misleading", result)


def test_functional_verbose_but_correct_is_harmless():
    alt = ("Search button that lets a shopper look for products across the whole catalogue "
           "by typing a query into the field to the left of it and then pressing the "
           "control shown here on the page")
    result = score_alt(SEARCH_BUTTON, alt)
    check(result["correct"] is True, result)
    check(result["severity"] == "harmless", result)


# Image of text


def test_image_of_text_exact_is_correct():
    result = score_alt(LOGO, "Binclusive.")
    check(result["correct"] is True, result)
    check(result["severity"] == "correct", result)


def test_image_of_text_near_miss_is_correct():
    result = score_alt(LOGO, "Binclusiv")
    check(result["correct"] is True, result)


def test_image_of_text_hallucination_is_misleading():
    result = score_alt(LOGO, "a close up of a bird flying in the air with a bird on it's back")
    check(result["correct"] is False, result)
    check(result["severity"] == "misleading", result)


def test_image_of_text_empty_is_silent():
    result = score_alt(LOGO, "EMPTY")
    check(result["severity"] == "silent", result)


def test_image_of_text_partial_is_degraded():
    item = dict(LOGO, expected_alt="Binclusive accessibility platform",
                must_include=["binclusive", "accessibility", "platform"])
    result = score_alt(item,
                       "the words accessibility platform written in white on a dark banner")
    check(result["severity"] == "degraded", result)


# Informative


def test_informative_complete_is_correct():
    result = score_alt(DOG_PHOTO, "A dog carrying a stick across a lawn")
    check(result["correct"] is True, result)


def test_informative_partial_is_degraded():
    result = score_alt(DOG_PHOTO, "A dog on the grass")
    check(result["correct"] is False, result)
    check(result["severity"] == "degraded", result)


def test_informative_empty_is_silent():
    result = score_alt(DOG_PHOTO, "")
    check(result["severity"] == "silent", result)


def test_informative_wrong_is_misleading():
    result = score_alt(DOG_PHOTO, "a red sports car parked outside a house")
    check(result["severity"] == "misleading", result)


# Complex


def test_complex_title_and_data_is_correct():
    result = score_alt(CHART, "Bar chart of caption errors per 1000 words: 48, 21 and 39")
    check(result["correct"] is True, result)


def test_complex_title_only_is_degraded():
    result = score_alt(CHART, "A bar chart of caption errors per 1000 words")
    check(result["correct"] is False, result)
    check(result["severity"] == "degraded", result)


def test_complex_empty_is_silent():
    result = score_alt(CHART, "empty")
    check(result["severity"] == "silent", result)


def test_complex_wrong_is_misleading():
    result = score_alt(CHART, "a photograph of two people shaking hands")
    check(result["severity"] == "misleading", result)


# The five cases carried over from the feasibility run


def test_feasibility_cases():
    cases = [
        (SEARCH_BUTTON, "a close up of a cell phone with a magnifying glass on it",
         False, "degraded"),
        (SEARCH_BUTTON, "Empty", False, "silent"),
        (LOGO, "Binclusive.", True, "correct"),
        (DIVIDER, "Empty", True, "correct"),
        (LOGO, "a close up of a bird flying in the air with a bird on it's back",
         False, "misleading"),
    ]
    for item, alt, correct, severity in cases:
        result = score_alt(item, alt)
        check(result["correct"] is correct,
              f"{item['id']} / {alt!r}: correct {result['correct']}, wanted {correct}")
        check(result["severity"] == severity,
              f"{item['id']} / {alt!r}: severity {result['severity']}, wanted {severity}")


def _run() -> int:
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"pass {name}")
        except AssertionError as exc:
            failures.append((name, exc))
            print(f"FAIL {name}: {exc}")
    print(f"\n{len(tests) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
