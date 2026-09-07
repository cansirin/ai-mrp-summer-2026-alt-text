"""Run a vision-language model over the image manifest under one prompting condition.

Reads data/manifest.json and writes results/raw/<model stem>__<condition>.json, where
the model stem is the Hugging Face id with "/" replaced by "__". Existing output files
are reused: ids already present are skipped and new outputs are appended, so an
interrupted run can be restarted.
"""

import argparse
import json
import os
import time

import torch
from PIL import Image

SEED = 0

MODELS = {
    "blip": "Salesforce/blip-image-captioning-large",
    "qwen2vl-2b": "Qwen/Qwen2-VL-2B-Instruct",
    "qwen2vl-7b": "Qwen/Qwen2-VL-7B-Instruct",
}

# Conditions each model family can run.
MODEL_CONDITIONS = {
    "blip": ["caption"],
    "qwen2vl-2b": ["naive", "wcag", "wcag_context"],
    "qwen2vl-7b": ["naive", "wcag", "wcag_context"],
}

# BLIP is used unconditioned, as a pure captioner. The empty string records that.
CAPTION_PROMPT = ""

NAIVE_PROMPT = "Write alt text for this image."

WCAG_PROMPT = (
    "Write alt text for this image for a screen reader user, following WCAG. "
    "If the image is purely decorative, reply exactly: EMPTY. "
    "If it is a button or link, give the action it performs, not its appearance. "
    "If it contains text, transcribe the text. Be concise."
)

WCAG_CONTEXT_PROMPT = WCAG_PROMPT + (
    "\n\nThe image appears on a web page in the following context:\n"
    "{context}\n"
    "Use this context to decide the image's purpose on the page, and describe that "
    "purpose rather than the image's appearance."
)

PROMPTS = {
    "caption": CAPTION_PROMPT,
    "naive": NAIVE_PROMPT,
    "wcag": WCAG_PROMPT,
    "wcag_context": WCAG_CONTEXT_PROMPT,
}

MAX_NEW_TOKENS = 60
FLUSH_EVERY = 10


def pick_device():
    """Return "mps" when the Apple GPU backend is usable, otherwise "cpu"."""
    return "mps" if torch.backends.mps.is_available() else "cpu"


def format_context(item):
    """Render an item's context block as the text substituted into the context prompt."""
    ctx = item.get("context") or {}
    tag = ctx.get("tag", "") or "unknown"
    html = ctx.get("html", "") or ""
    nearby = ctx.get("nearby_text", "") or ""
    return (
        f"Element tag: {tag}\n"
        f"HTML: {html}\n"
        f"Nearby text: {nearby}"
    )


class BlipRunner:
    """Wraps BLIP captioning: one unconditioned caption per image."""

    def __init__(self, model_id, device):
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self.device = device
        self.processor = BlipProcessor.from_pretrained(model_id)
        self.model = BlipForConditionalGeneration.from_pretrained(
            model_id, dtype=torch.float16
        ).to(device)
        self.model.eval()

    def generate(self, image, item, condition):
        inputs = self.processor(image, return_tensors="pt").to(self.device, torch.float16)
        with torch.no_grad():
            ids = self.model.generate(
                **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False
            )
        return self.processor.decode(ids[0], skip_special_tokens=True).strip()


class QwenRunner:
    """Wraps Qwen2-VL chat generation for the three instruction conditions."""

    def __init__(self, model_id, device):
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.device = device
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_id, dtype=torch.float16
        ).to(device)
        self.model.eval()

    def generate(self, image, item, condition):
        prompt = PROMPTS[condition]
        if condition == "wcag_context":
            prompt = prompt.format(context=format_context(item))
        messages = [
            {
                "role": "user",
                "content": [{"type": "image"}, {"type": "text", "text": prompt}],
            }
        ]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(text=[text], images=[image], return_tensors="pt").to(
            self.device
        )
        with torch.no_grad():
            ids = self.model.generate(
                **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False
            )
        trimmed = ids[:, inputs["input_ids"].shape[1]:]
        return self.processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()


def build_runner(model_key, model_id, device):
    if model_key == "blip":
        return BlipRunner(model_id, device)
    return QwenRunner(model_id, device)


def load_existing(path):
    """Return the previously written result document, or None if there is none."""
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def write_results(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=2)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument(
        "--condition", required=True, choices=["caption", "naive", "wcag", "wcag_context"]
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after N items")
    parser.add_argument("--manifest", default="data/manifest.json")
    parser.add_argument("--out-dir", default="results/raw")
    args = parser.parse_args()

    allowed = MODEL_CONDITIONS[args.model]
    if args.condition not in allowed:
        parser.error(
            f"model {args.model} supports conditions: {', '.join(allowed)}"
        )

    torch.manual_seed(SEED)

    model_id = MODELS[args.model]
    stem = model_id.replace("/", "__")
    out_path = os.path.join(args.out_dir, f"{stem}__{args.condition}.json")

    with open(args.manifest) as fh:
        manifest = json.load(fh)
    items = manifest["items"]
    manifest_dir = os.path.dirname(os.path.abspath(args.manifest))

    doc = load_existing(out_path)
    if doc is None:
        doc = {
            "model": model_id,
            "condition": args.condition,
            "prompt": PROMPTS[args.condition],
            "device": None,
            "load_sec": None,
            "outputs": {},
        }
    done = set(doc["outputs"])

    pending = [it for it in items if it["id"] not in done]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"{model_id} / {args.condition}: {len(pending)} items to run, {len(done)} already done")
    if not pending:
        return

    device = pick_device()
    t0 = time.time()
    runner = build_runner(args.model, model_id, device)
    load_sec = round(time.time() - t0, 1)
    print(f"loaded on {device} in {load_sec}s")

    doc["device"] = device
    doc["load_sec"] = load_sec

    times = []
    for n, item in enumerate(pending, 1):
        path = item["file"]
        if not os.path.isabs(path):
            path = os.path.join(manifest_dir, path)
        image = Image.open(path).convert("RGB")
        t1 = time.time()
        alt = runner.generate(image, item, args.condition)
        sec = round(time.time() - t1, 2)
        times.append(sec)
        doc["outputs"][item["id"]] = {"alt": alt, "sec": sec}
        print(f"[{n}/{len(pending)}] {item['id']} {sec}s  {alt[:80]!r}")
        if n % FLUSH_EVERY == 0:
            write_results(out_path, doc)

    write_results(out_path, doc)
    mean = sum(times) / len(times)
    print(
        f"wrote {out_path}: {len(doc['outputs'])} outputs, "
        f"mean {mean:.2f}s/image over {len(times)} new items"
    )


if __name__ == "__main__":
    main()
