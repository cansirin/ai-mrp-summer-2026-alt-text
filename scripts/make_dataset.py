"""Build the benchmark image set and its manifest.

Every image is rendered from an HTML/CSS/SVG template with headless Chrome, so the
correct alt text for each image is known before the pixels exist. Running this file
wipes data/images and rewrites data/manifest.json from scratch. The random seed is
fixed, so two runs on the same machine produce the same set.

Usage:
    python3 scripts/make_dataset.py [--workers N]
"""

import argparse
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SEED = 20260906
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMAGES = DATA / "images"
MANIFEST = DATA / "manifest.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CATEGORIES = ["functional", "informative", "decorative", "image_of_text", "complex"]

rng = random.Random(SEED)

# ---------------------------------------------------------------- style banks

ACCENTS = [
    "#1a73e8", "#0f766e", "#b91c1c", "#7c3aed", "#c2410c",
    "#15803d", "#0369a1", "#be185d", "#334155", "#a16207",
    "#2563eb", "#059669", "#dc2626", "#9333ea", "#ea580c",
]

DARKS = ["#111827", "#1f2937", "#0f172a", "#292524", "#18181b"]

PAGE_BGS = ["#ffffff", "#fafafa", "#f5f7fa", "#fffdf7", "#f7f5ff", "#f4faf7", "#fdf6f6"]

SANS = [
    "system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif",
    "'Helvetica Neue', Helvetica, Arial, sans-serif",
    "Verdana, Geneva, sans-serif",
    "'Trebuchet MS', Tahoma, sans-serif",
    "Avenir, 'Avenir Next', sans-serif",
    "Futura, 'Century Gothic', sans-serif",
]

SERIF = [
    "Georgia, 'Times New Roman', serif",
    "Palatino, 'Palatino Linotype', serif",
    "Baskerville, Georgia, serif",
    "'Hoefler Text', Garamond, serif",
    "'Times New Roman', Times, serif",
]

MONO = ["Menlo, Monaco, 'Courier New', monospace", "'Courier New', Courier, monospace"]

STOPWORDS = {"by", "the", "a", "an", "of", "in", "per", "and", "to", "for", "on", "vs"}


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def tint(color, alpha):
    r, g, b = hex_to_rgb(color)
    return f"rgba({r},{g},{b},{alpha})"


def mix(color, other, amount):
    a = hex_to_rgb(color)
    b = hex_to_rgb(other)
    out = tuple(round(a[i] + (b[i] - a[i]) * amount) for i in range(3))
    return "#%02x%02x%02x" % out


def keywords(text, limit=3):
    words = [w.strip(string.punctuation).lower() for w in text.split()]
    words = [w for w in words if len(w) > 2 and w not in STOPWORDS and not w.isdigit()]
    seen = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return seen[:limit]


# ---------------------------------------------------------------- icon bank

ICON_PATHS = {
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',
    "close": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "menu": '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "cart": '<circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>',
    "play": '<polygon points="5 3 19 12 5 21 5 3"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    "back": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "next": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "print": '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "heart": '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "filter": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "mail": '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "chat": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "external": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "bookmark": '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "pause": '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>',
    "mute": '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>',
    "bell": '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    "zoom": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "map": '<polygon points="1 6 8 3 16 6 23 3 23 18 16 21 8 18 1 21 1 6"/><line x1="8" y1="3" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="21"/>',
}

FILLED_ICONS = {"play", "star", "heart", "filter", "pause", "mute", "bookmark"}


def icon(name, size, color, stroke=2.0):
    body = ICON_PATHS[name]
    if name in FILLED_ICONS:
        paint = f'fill="{color}" stroke="{color}" stroke-width="{stroke}"'
    else:
        paint = f'fill="none" stroke="{color}" stroke-width="{stroke}"'
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" {paint} '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


# ---------------------------------------------------------------- rendering

def page(width, height, css, body, bg="#ffffff"):
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><style>"
        f"html,body{{margin:0;padding:0;background:{bg};}}"
        "*{box-sizing:border-box;}"
        f"#c{{width:{width}px;height:{height}px;overflow:hidden;position:relative;"
        f"background:{bg};}}"
        f"{css}</style></head><body><div id=\"c\">{body}</div></body></html>"
    )


_slots = threading.local()


def shoot(spec, out_path, workdir, slot, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            _shoot_once(spec, out_path, workdir, slot)
            return
        except RuntimeError:
            if attempt == attempts:
                raise
            time.sleep(1.5 * attempt)


def _shoot_once(spec, out_path, workdir, slot):
    html = page(spec["w"], spec["h"], spec["css"], spec["body"], spec.get("bg", "#ffffff"))
    src = workdir / f"{out_path.stem}.html"
    src.write_text(html, encoding="utf-8")
    if out_path.exists():
        out_path.unlink()
    cmd = [
        CHROME, "--headless=old", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--virtual-time-budget=900",
        "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        f"--user-data-dir={workdir / ('profile_%d' % slot)}",
        f"--screenshot={out_path}",
        f"--window-size={spec['w']},{spec['h']}",
        src.as_uri(),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 75
    last = -1
    stable = 0
    try:
        while time.time() < deadline:
            if out_path.exists():
                size = out_path.stat().st_size
                if size > 0 and size == last:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
                last = size
            if proc.poll() is not None and out_path.exists():
                break
            time.sleep(0.06)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        src.unlink(missing_ok=True)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"screenshot failed for {out_path.name}")


def png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    width = int.from_bytes(head[16:20], "big")
    height = int.from_bytes(head[20:24], "big")
    return width, height


# ---------------------------------------------------------------- item helper

def make(cat, spec, expected, must, must_not, ctx_tag, ctx_html, nearby, notes):
    return {
        "category": cat,
        "spec": spec,
        "expected_alt": expected,
        "must_include": [m.lower() for m in must],
        "must_not_include": [m.lower() for m in must_not],
        "context": {"tag": ctx_tag, "html": ctx_html, "nearby_text": nearby},
        "notes": notes,
    }


# ---------------------------------------------------------------- functional

ICON_ACTIONS = {
    "search": ("Search", ["search"], ["magnifying", "glass", "lens", "icon"]),
    "trash": ("Delete", ["delete"], ["trash", "bin", "can", "icon"]),
    "close": ("Close", ["close"], ["cross", "icon"]),
    "menu": ("Open menu", ["menu"], ["hamburger", "three lines", "icon"]),
    "settings": ("Settings", ["settings"], ["gear", "cog", "wheel", "icon"]),
    "cart": ("View cart", ["cart"], ["trolley", "basket", "icon"]),
    "play": ("Play", ["play"], ["triangle", "icon"]),
    "download": ("Download", ["download"], ["arrow", "icon"]),
    "share": ("Share", ["share"], ["nodes", "dots", "icon"]),
    "edit": ("Edit", ["edit"], ["pencil", "pen", "icon"]),
    "back": ("Go back", ["back"], ["arrow", "icon"]),
    "next": ("Next", ["next"], ["arrow", "icon"]),
    "home": ("Home", ["home"], ["house", "roof", "icon"]),
    "print": ("Print", ["print"], ["printer", "machine", "icon"]),
    "user": ("Your account", ["account"], ["person", "silhouette", "avatar", "icon"]),
    "heart": ("Save to wishlist", ["wishlist"], ["heart", "icon"]),
    "star": ("Add to favorites", ["favorites"], ["star", "icon"]),
    "filter": ("Filter results", ["filter"], ["funnel", "icon"]),
    "upload": ("Upload a file", ["upload"], ["arrow", "icon"]),
    "refresh": ("Refresh", ["refresh"], ["circular", "icon"]),
    "mail": ("Email us", ["email"], ["envelope", "letter", "icon"]),
    "phone": ("Call us", ["call"], ["handset", "receiver", "telephone", "icon"]),
    "lock": ("Secure checkout", ["secure"], ["padlock", "icon"]),
    "calendar": ("Pick a date", ["date"], ["calendar", "grid", "icon"]),
    "chat": ("Open live chat", ["chat"], ["speech", "bubble", "icon"]),
    "help": ("Help", ["help"], ["question mark", "circle", "icon"]),
    "external": ("Open in a new tab", ["new tab"], ["square", "arrow", "icon"]),
    "plus": ("Add item", ["add"], ["plus", "cross", "icon"]),
    "bookmark": ("Bookmark this page", ["bookmark"], ["ribbon", "flag", "icon"]),
    "pause": ("Pause", ["pause"], ["bars", "icon"]),
    "mute": ("Mute", ["mute"], ["speaker", "icon"]),
    "bell": ("Notifications", ["notifications"], ["bell", "icon"]),
    "zoom": ("Zoom in", ["zoom"], ["magnifying", "glass", "icon"]),
    "copy": ("Copy", ["copy"], ["squares", "icon"]),
    "map": ("Open the map", ["map"], ["folded", "paper", "icon"]),
}

ICON_CONTEXT = {
    "search": ("button", '<form role="search" action="/search"><label for="q">Search products</label>'
                         '<input id="q" name="q" type="search"><button type="submit" class="icon-btn">'
                         '<img src="{src}"></button></form>', "Search products"),
    "trash": ("button", '<tr><td>Blue linen shirt</td><td>1</td><td><button type="button" '
                        'class="row-action" data-id="8841"><img src="{src}"></button></td></tr>',
              "Blue linen shirt, quantity 1"),
    "close": ("button", '<div class="modal"><h2>Newsletter</h2><button type="button" class="modal-close" '
                        'data-dismiss="modal"><img src="{src}"></button></div>', "Newsletter"),
    "menu": ("button", '<header class="site-header"><button type="button" class="nav-toggle" '
                       'aria-expanded="false" aria-controls="main-nav"><img src="{src}"></button></header>',
             "Kestrel Books"),
    "settings": ("a", '<nav class="sidebar"><a href="/account/settings"><img src="{src}"></a></nav>',
                 "Account"),
    "cart": ("a", '<header><a href="/cart" class="cart-link"><img src="{src}"><span class="count">3</span>'
                  '</a></header>', "3 items"),
    "play": ("button", '<div class="player"><button type="button" class="play"><img src="{src}"></button>'
                       '<span class="track">Track 4, Harbour Lights</span></div>', "Track 4, Harbour Lights"),
    "download": ("a", '<li class="file"><span>Quarterly report.pdf</span><a href="/files/q3.pdf" download>'
                      '<img src="{src}"></a></li>', "Quarterly report.pdf"),
    "share": ("button", '<article><h1>Sourdough in a home oven</h1><button type="button" class="share">'
                        '<img src="{src}"></button></article>', "Sourdough in a home oven"),
    "edit": ("button", '<li class="address"><span>14 Mill Lane</span><button type="button" class="edit" '
                       'data-id="addr-2"><img src="{src}"></button></li>', "14 Mill Lane"),
    "back": ("a", '<nav class="pager"><a href="/results?page=2"><img src="{src}"></a></nav>', "Page 3 of 9"),
    "next": ("a", '<nav class="pager"><a href="/results?page=4"><img src="{src}"></a></nav>', "Page 3 of 9"),
    "home": ("a", '<header><a href="/" class="home"><img src="{src}"></a></header>', "Kestrel Books"),
    "print": ("button", '<div class="toolbar"><button type="button" onclick="window.print()">'
                        '<img src="{src}"></button></div>', "Invoice 2291"),
    "user": ("a", '<header><a href="/account"><img src="{src}"></a></header>', "Signed in as Rana"),
    "heart": ("button", '<div class="product-card"><h3>Walnut desk lamp</h3><button type="button" '
                        'class="wishlist" data-sku="LMP-22"><img src="{src}"></button></div>',
              "Walnut desk lamp"),
    "star": ("button", '<li class="doc"><span>Notes from Tuesday</span><button type="button" class="fav">'
                       '<img src="{src}"></button></li>', "Notes from Tuesday"),
    "filter": ("button", '<div class="results-bar"><span>412 results</span><button type="button" '
                         'class="filters" aria-expanded="false"><img src="{src}"></button></div>',
               "412 results"),
    "upload": ("button", '<form action="/upload" method="post"><label for="f">Attach a document</label>'
                         '<button type="button" class="upload"><img src="{src}"></button></form>',
               "Attach a document"),
    "refresh": ("button", '<div class="feed-head"><span>Updated 4 minutes ago</span><button type="button" '
                          'class="reload"><img src="{src}"></button></div>', "Updated 4 minutes ago"),
    "mail": ("a", '<footer><a href="mailto:hello@kestrelbooks.test"><img src="{src}"></a></footer>',
             "Get in touch"),
    "phone": ("a", '<footer><a href="tel:+15550142200"><img src="{src}"></a></footer>',
              "Customer service"),
    "lock": ("button", '<form action="/checkout"><button type="submit" class="pay"><img src="{src}"></button>'
                       '</form>', "Total 84.00"),
    "calendar": ("button", '<div class="field"><label for="d">Departure</label><input id="d" name="d">'
                           '<button type="button" class="datepicker"><img src="{src}"></button></div>',
                 "Departure"),
    "chat": ("button", '<button type="button" class="chat-launcher" data-widget="support">'
                       '<img src="{src}"></button>', "Support"),
    "help": ("a", '<div class="field"><label for="cvv">Security code</label><input id="cvv">'
                  '<a href="/help/cvv"><img src="{src}"></a></div>', "Security code"),
    "external": ("a", '<p>Read the <a href="https://example.test/spec" target="_blank">full specification'
                      '<img src="{src}"></a></p>', "full specification"),
    "plus": ("button", '<div class="qty"><span>Quantity 2</span><button type="button" class="inc">'
                       '<img src="{src}"></button></div>', "Quantity 2"),
    "bookmark": ("button", '<article><h1>The tide tables</h1><button type="button" class="save">'
                           '<img src="{src}"></button></article>', "The tide tables"),
    "pause": ("button", '<div class="player"><button type="button" class="pause"><img src="{src}"></button>'
                        '</div>', "Now playing, Episode 12"),
    "mute": ("button", '<div class="player"><button type="button" class="volume"><img src="{src}"></button>'
                       '</div>', "Volume"),
    "bell": ("a", '<header><a href="/notifications"><img src="{src}"><span class="badge">5</span></a>'
                  '</header>', "5 unread"),
    "zoom": ("button", '<figure class="gallery"><img src="/photos/4.jpg"><button type="button" class="zoom">'
                       '<img src="{src}"></button></figure>', "Photo 4 of 9"),
    "copy": ("button", '<div class="code-block"><code>npm install kestrel</code><button type="button" '
                       'class="copy"><img src="{src}"></button></div>', "npm install kestrel"),
    "map": ("a", '<section class="store"><h3>Mill Lane branch</h3><a href="/stores/mill-lane/map">'
                 '<img src="{src}"></a></section>', "Mill Lane branch"),
}

BUTTON_STYLES = ["solid_pill", "solid_round", "circle", "outline", "ghost", "dark", "soft", "square_flat"]


def button_spec(icon_name, style, accent, bg, size, pad):
    box = size + pad * 2
    ic = round(size * 0.5)
    if style == "solid_pill":
        w, h = round(box * 1.5), box
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{round(box*1.15)}px;height:{round(box*0.72)}px;border-radius:999px;"
               f"background:{accent};display:flex;align-items:center;justify-content:center;}}")
        return dict(w=w, h=h, css=css, bg=bg,
                    body=f'<div class="b">{icon(icon_name, ic, "#ffffff", 2.1)}</div>')
    if style == "solid_round":
        w = h = box
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{round(box*0.72)}px;height:{round(box*0.72)}px;border-radius:10px;"
               f"background:{accent};display:flex;align-items:center;justify-content:center;}}")
        return dict(w=w, h=h, css=css, bg=bg,
                    body=f'<div class="b">{icon(icon_name, ic, "#ffffff", 2.1)}</div>')
    if style == "circle":
        w = h = box
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{round(box*0.74)}px;height:{round(box*0.74)}px;border-radius:50%;"
               f"background:{accent};display:flex;align-items:center;justify-content:center;}}")
        return dict(w=w, h=h, css=css, bg=bg,
                    body=f'<div class="b">{icon(icon_name, ic, "#ffffff", 2.1)}</div>')
    if style == "outline":
        w = h = box
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{round(box*0.72)}px;height:{round(box*0.72)}px;border-radius:8px;"
               f"border:1.5px solid {accent};background:#fff;display:flex;align-items:center;"
               f"justify-content:center;}}")
        return dict(w=w, h=h, css=css, bg=bg,
                    body=f'<div class="b">{icon(icon_name, ic, accent, 2.0)}</div>')
    if style == "ghost":
        w = h = box
        css = "#c{display:flex;align-items:center;justify-content:center;}"
        return dict(w=w, h=h, css=css, bg=bg,
                    body=icon(icon_name, round(size * 0.62), mix(accent, "#000000", 0.25), 2.0))
    if style == "dark":
        w, h = round(box * 1.4), box
        dark = rng.choice(DARKS)
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{round(box*1.05)}px;height:{round(box*0.7)}px;border-radius:6px;"
               f"background:{dark};display:flex;align-items:center;justify-content:center;}}")
        return dict(w=w, h=h, css=css, bg=bg,
                    body=f'<div class="b">{icon(icon_name, ic, "#ffffff", 2.0)}</div>')
    if style == "soft":
        w = h = box
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{round(box*0.76)}px;height:{round(box*0.76)}px;border-radius:14px;"
               f"background:{tint(accent, 0.14)};display:flex;align-items:center;justify-content:center;}}")
        return dict(w=w, h=h, css=css, bg=bg,
                    body=f'<div class="b">{icon(icon_name, ic, accent, 2.0)}</div>')
    w = h = box
    css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
           f".b{{width:{round(box*0.7)}px;height:{round(box*0.7)}px;background:{mix(accent,'#ffffff',0.86)};"
           f"display:flex;align-items:center;justify-content:center;}}")
    return dict(w=w, h=h, css=css, bg=bg,
                body=f'<div class="b">{icon(icon_name, ic, accent, 1.8)}</div>')


BRANDS = [
    ("Kestrel Books", SERIF), ("Northwind Tea", SANS), ("Marrow & Co", SERIF),
    ("Lumen Health", SANS), ("Tidewater Bank", SERIF), ("Foxglove Studio", SANS),
    ("Copperline", SANS), ("Halcyon Travel", SERIF), ("Bramble Grocers", SANS),
    ("Quill & Sable", SERIF),
]


def gen_functional():
    items = []
    names = list(ICON_ACTIONS)
    rng.shuffle(names)
    for i, name in enumerate(names):
        action, must, must_not = ICON_ACTIONS[name]
        style = BUTTON_STYLES[i % len(BUTTON_STYLES)]
        accent = rng.choice(ACCENTS)
        bg = rng.choice(PAGE_BGS)
        size = rng.choice([44, 52, 60, 68, 76])
        pad = rng.choice([14, 20, 26, 32])
        spec = button_spec(name, style, accent, bg, size, pad)
        tag, html, nearby = ICON_CONTEXT[name]
        items.append(make("functional", spec, action, must, must_not, tag, html, nearby,
                          f"icon-only control, icon {name}, style {style}, accent {accent}"))

    # a second pass over a subset with different styling, so the same action appears twice
    for name in rng.sample(names, 4):
        action, must, must_not = ICON_ACTIONS[name]
        style = rng.choice(BUTTON_STYLES)
        accent = rng.choice(ACCENTS)
        spec = button_spec(name, style, accent, rng.choice(PAGE_BGS),
                           rng.choice([40, 48, 56, 64, 72, 84]), rng.choice([10, 16, 22, 30]))
        tag, html, nearby = ICON_CONTEXT[name]
        items.append(make("functional", spec, action, must, must_not, tag, html, nearby,
                          f"icon-only control, icon {name}, style {style}, accent {accent}"))

    # icon plus label, the whole control is captured
    labelled = [
        ("cart", "Add to cart", ["add", "cart"], "button",
         '<form action="/cart/add"><input type="hidden" name="sku" value="LMP-22">'
         '<button type="submit" class="cta"><img src="{src}"></button></form>', "Walnut desk lamp, 64.00"),
        ("download", "Download the report", ["download", "report"], "a",
         '<section><h3>Annual report 2025</h3><a class="cta" href="/files/annual.pdf" download>'
         '<img src="{src}"></a></section>', "Annual report 2025"),
        ("plus", "Add a new list", ["add", "list"], "button",
         '<div class="lists"><button type="button" class="cta"><img src="{src}"></button></div>', "Your lists"),
        ("trash", "Delete account", ["delete", "account"], "button",
         '<section class="danger"><h3>Danger zone</h3><button type="button" class="cta danger">'
         '<img src="{src}"></button></section>', "Danger zone"),
        ("mail", "Send message", ["send", "message"], "button",
         '<form action="/contact" method="post"><label for="m">Message</label><textarea id="m"></textarea>'
         '<button type="submit" class="cta"><img src="{src}"></button></form>', "Message"),
        ("calendar", "Book a viewing", ["book", "viewing"], "button",
         '<aside class="listing"><h3>2 bed flat, Mill Lane</h3><button type="button" class="cta">'
         '<img src="{src}"></button></aside>', "2 bed flat, Mill Lane"),
        ("upload", "Upload photos", ["upload", "photos"], "button",
         '<form action="/photos"><button type="button" class="cta"><img src="{src}"></button></form>',
         "Add up to 10 photos"),
        ("refresh", "Try again", ["try again"], "button",
         '<div class="error"><p>We could not load your orders.</p><button type="button" class="cta">'
         '<img src="{src}"></button></div>', "We could not load your orders."),
        ("print", "Print this invoice", ["print", "invoice"], "button",
         '<div class="toolbar"><button type="button" class="cta"><img src="{src}"></button></div>',
         "Invoice 2291"),
        ("lock", "Continue to payment", ["payment"], "button",
         '<form action="/checkout/pay"><button type="submit" class="cta"><img src="{src}"></button></form>',
         "Step 2 of 3"),
    ]
    for icon_name, label, must, tag, html, nearby in labelled:
        accent = rng.choice(ACCENTS)
        font = rng.choice(SANS)
        fs = rng.choice([15, 16, 17, 18])
        pad = rng.choice([14, 18, 22])
        w = 60 + int(len(label) * fs * 0.62) + pad * 2
        h = fs * 2 + pad * 2 + 16
        radius = rng.choice([6, 8, 999])
        dark_text = rng.random() < 0.25
        fg = "#111827" if dark_text else "#ffffff"
        back = mix(accent, "#ffffff", 0.85) if dark_text else accent
        css = (f"#c{{display:flex;align-items:center;justify-content:center;font-family:{font};}}"
               f".b{{display:inline-flex;align-items:center;gap:10px;padding:{pad//2+6}px {pad+8}px;"
               f"border-radius:{radius}px;background:{back};color:{fg};font-weight:600;font-size:{fs}px;}}")
        spec = dict(w=w, h=h, css=css, bg=rng.choice(PAGE_BGS),
                    body=f'<div class="b">{icon(icon_name, fs + 4, fg, 2.0)}<span>{label}</span></div>')
        items.append(make("functional", spec, label, must, ["icon"], tag, html, nearby,
                          f"icon plus label control, icon {icon_name}"))

    # linked wordmark logos in a header
    for brand, fonts in rng.sample(BRANDS, 8):
        font = rng.choice(fonts)
        accent = rng.choice(ACCENTS)
        fs = rng.choice([22, 26, 30, 34])
        w = int(len(brand) * fs * 0.62) + 80
        h = fs * 2 + 46
        weight = rng.choice([600, 700])
        spacing = rng.choice(["0", "0.5px", "1px", "-0.5px"])
        mark = rng.random() < 0.5
        dot = (f'<span style="display:inline-block;width:{fs}px;height:{fs}px;border-radius:'
               f'{rng.choice([4, 999])}px;background:{accent};margin-right:10px;vertical-align:-2px">'
               f'</span>') if mark else ""
        css = (f"#c{{display:flex;align-items:center;justify-content:center;font-family:{font};}}"
               f".w{{font-size:{fs}px;font-weight:{weight};letter-spacing:{spacing};color:"
               f"{mix(accent, '#000000', 0.2)};white-space:nowrap;}}")
        spec = dict(w=w, h=h, css=css, bg=rng.choice(PAGE_BGS),
                    body=f'<div class="w">{dot}{brand}</div>')
        first = brand.split()[0].lower()
        items.append(make("functional", spec, f"{brand} home", [first, "home"],
                          ["logo", "wordmark", "text", "icon"], "a",
                          '<header class="site-header"><a href="/" class="brand"><img src="{src}"></a>'
                          '<nav><a href="/shop">Shop</a><a href="/about">About</a></nav></header>',
                          "Shop About Basket",
                          f"linked wordmark in a header, brand {brand}"))

    # third party sign in and pay controls
    third_party = [
        ("Nimbus", "#2563eb", "Sign in with Nimbus", ["sign in", "nimbus"]),
        ("Orbit", "#111827", "Sign in with Orbit", ["sign in", "orbit"]),
        ("Kite", "#0f766e", "Sign in with Kite", ["sign in", "kite"]),
        ("Vertex", "#c2410c", "Sign in with Vertex", ["sign in", "vertex"]),
        ("PayFast", "#f0b429", "Pay with PayFast", ["pay", "payfast"]),
        ("SwiftPay", "#1f2937", "Pay with SwiftPay", ["pay", "swiftpay"]),
        ("Mesa Wallet", "#7c3aed", "Pay with Mesa Wallet", ["pay", "mesa"]),
        ("Harbour Pay", "#0369a1", "Pay with Harbour Pay", ["pay", "harbour"]),
    ]
    for brandname, color, action, must in third_party:
        pay = action.startswith("Pay")
        font = rng.choice(SANS)
        fs = rng.choice([16, 18, 20])
        label = brandname if pay else f"Continue with {brandname}"
        w = int(len(label) * fs * 0.62) + 130
        h = fs * 2 + 52
        light = color in ("#f0b429",)
        fg = "#1f2937" if light else "#ffffff"
        letter = brandname[0]
        badge = (f'<span style="display:inline-flex;width:{fs+8}px;height:{fs+8}px;border-radius:50%;'
                 f'background:{fg};color:{color};align-items:center;justify-content:center;'
                 f'font-weight:700;font-size:{fs-2}px;margin-right:10px">{letter}</span>')
        css = (f"#c{{display:flex;align-items:center;justify-content:center;font-family:{font};}}"
               f".b{{display:inline-flex;align-items:center;padding:12px 24px;border-radius:"
               f"{rng.choice([6, 999])}px;background:{color};color:{fg};font-weight:600;font-size:{fs}px;"
               f"white-space:nowrap;}}")
        spec = dict(w=w, h=h, css=css, bg=rng.choice(PAGE_BGS), body=f'<div class="b">{badge}{label}</div>')
        html = ('<form action="/checkout/pay" method="post"><button type="submit" class="pay-btn">'
                '<img src="{src}"></button></form>') if pay else (
            '<div class="sso"><button type="button" class="sso-btn"><img src="{src}"></button></div>')
        nearby = "Total 84.00, secure checkout" if pay else "Or sign in with email"
        items.append(make("functional", spec, action, must, ["logo", "icon", "button image"],
                          "button", html, nearby, f"third party control, {brandname}"))
    return items


# ---------------------------------------------------------------- informative

def weather_svg(kind, size, accent):
    s = size
    sun = f'<circle cx="{s*0.5}" cy="{s*0.45}" r="{s*0.18}" fill="#f5a623"/>'
    rays = "".join(
        f'<line x1="{s*0.5 + s*0.28*_c(a)}" y1="{s*0.45 + s*0.28*_s(a)}" '
        f'x2="{s*0.5 + s*0.38*_c(a)}" y2="{s*0.45 + s*0.38*_s(a)}" stroke="#f5a623" '
        f'stroke-width="{s*0.045}" stroke-linecap="round"/>'
        for a in range(0, 360, 45))
    cloud = (f'<g fill="#9aa5b1"><circle cx="{s*0.38}" cy="{s*0.55}" r="{s*0.14}"/>'
             f'<circle cx="{s*0.54}" cy="{s*0.5}" r="{s*0.18}"/>'
             f'<circle cx="{s*0.68}" cy="{s*0.58}" r="{s*0.13}"/>'
             f'<rect x="{s*0.36}" y="{s*0.58}" width="{s*0.34}" height="{s*0.12}" rx="{s*0.06}"/></g>')
    drops = "".join(f'<line x1="{s*(0.4+0.1*i)}" y1="{s*0.74}" x2="{s*(0.37+0.1*i)}" y2="{s*0.88}" '
                    f'stroke="#3b82f6" stroke-width="{s*0.035}" stroke-linecap="round"/>' for i in range(4))
    flakes = "".join(f'<circle cx="{s*(0.4+0.1*i)}" cy="{s*(0.78+0.04*(i%2))}" r="{s*0.028}" '
                     f'fill="#60a5fa"/>' for i in range(4))
    bolt = (f'<polygon points="{s*0.52},{s*0.7} {s*0.44},{s*0.86} {s*0.5},{s*0.86} {s*0.44},{s*0.98} '
            f'{s*0.6},{s*0.8} {s*0.52},{s*0.8}" fill="#f59e0b"/>')
    wind = "".join(f'<path d="M{s*0.2} {s*(0.4+0.14*i)} h{s*0.4} a{s*0.07} {s*0.07} 0 1 0 -{s*0.07} '
                   f'{s*0.07}" fill="none" stroke="#64748b" stroke-width="{s*0.045}" '
                   f'stroke-linecap="round"/>' for i in range(3))
    fog = "".join(f'<line x1="{s*0.22}" y1="{s*(0.72+0.09*i)}" x2="{s*0.78}" y2="{s*(0.72+0.09*i)}" '
                  f'stroke="#94a3b8" stroke-width="{s*0.05}" stroke-linecap="round"/>' for i in range(3))
    inner = {
        "sunny": sun + rays,
        "cloudy": cloud,
        "rain": cloud + drops,
        "snow": cloud + flakes,
        "storm": cloud + bolt,
        "partly": f'<circle cx="{s*0.62}" cy="{s*0.34}" r="{s*0.14}" fill="#f5a623"/>' + cloud,
        "wind": wind,
        "fog": cloud + fog,
    }[kind]
    return f'<svg width="{s}" height="{s}" viewBox="0 0 {s} {s}">{inner}</svg>'


def _c(deg):
    import math
    return math.cos(math.radians(deg))


def _s(deg):
    import math
    return math.sin(math.radians(deg))


def star_row(count, filled, size, color, empty="#d4d4d8"):
    out = []
    for i in range(count):
        out.append(icon("star", size, color if i < filled else empty, 1.5))
    return "".join(out)


PRODUCTS = {
    "mug": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="22" y="30" width="44" height="46" rx="6" fill="{col}"/>'
        f'<path d="M66 40 h10 a12 12 0 0 1 0 24 h-10" fill="none" stroke="{col}" stroke-width="7"/>'
        f'<ellipse cx="44" cy="30" rx="22" ry="6" fill="{mix(col, "#ffffff", 0.35)}"/></svg>'),
    "box": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="18" y="34" width="64" height="46" fill="{col}"/>'
        f'<polygon points="18,34 50,18 82,34 50,48" fill="{mix(col, "#ffffff", 0.28)}"/>'
        f'<rect x="46" y="34" width="8" height="46" fill="{mix(col, "#000000", 0.25)}"/></svg>'),
    "book": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="26" y="18" width="50" height="64" rx="3" fill="{col}"/>'
        f'<rect x="26" y="18" width="10" height="64" fill="{mix(col, "#000000", 0.3)}"/>'
        f'<rect x="44" y="34" width="24" height="4" fill="#ffffff" opacity="0.8"/>'
        f'<rect x="44" y="44" width="18" height="4" fill="#ffffff" opacity="0.8"/></svg>'),
    "bottle": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="42" y="12" width="16" height="14" rx="3" fill="{mix(col, "#000000", 0.3)}"/>'
        f'<path d="M38 26 h24 a10 10 0 0 1 10 10 v42 a6 6 0 0 1-6 6 h-32 a6 6 0 0 1-6-6 v-42 '
        f'a10 10 0 0 1 10-10z" fill="{col}"/>'
        f'<rect x="30" y="46" width="40" height="14" fill="#ffffff" opacity="0.85"/></svg>'),
    "shirt": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<polygon points="34,22 44,18 56,18 66,22 82,32 74,44 68,40 68,82 32,82 32,40 26,44 18,32" '
        f'fill="{col}"/></svg>'),
    "lamp": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<polygon points="34,20 66,20 78,46 22,46" fill="{col}"/>'
        f'<rect x="48" y="46" width="4" height="34" fill="#6b7280"/>'
        f'<ellipse cx="50" cy="82" rx="20" ry="5" fill="#6b7280"/></svg>'),
    "plant": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<ellipse cx="50" cy="42" rx="10" ry="22" fill="{col}"/>'
        f'<ellipse cx="34" cy="50" rx="8" ry="18" transform="rotate(-30 34 50)" fill="{col}"/>'
        f'<ellipse cx="66" cy="50" rx="8" ry="18" transform="rotate(30 66 50)" fill="{col}"/>'
        f'<polygon points="34,68 66,68 60,88 40,88" fill="#b45309"/></svg>'),
    "phone": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="34" y="12" width="32" height="76" rx="7" fill="{col}"/>'
        f'<rect x="38" y="20" width="24" height="56" fill="#ffffff" opacity="0.9"/>'
        f'<circle cx="50" cy="82" r="3" fill="#ffffff" opacity="0.9"/></svg>'),
    "chair": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="30" y="16" width="40" height="34" rx="6" fill="{col}"/>'
        f'<rect x="26" y="52" width="48" height="10" rx="4" fill="{mix(col, "#000000", 0.2)}"/>'
        f'<rect x="30" y="62" width="6" height="24" fill="#6b7280"/>'
        f'<rect x="64" y="62" width="6" height="24" fill="#6b7280"/></svg>'),
    "camera": lambda s, col: (
        f'<svg width="{s}" height="{s}" viewBox="0 0 100 100">'
        f'<rect x="16" y="30" width="68" height="44" rx="7" fill="{col}"/>'
        f'<rect x="38" y="22" width="24" height="10" rx="3" fill="{mix(col, "#000000", 0.3)}"/>'
        f'<circle cx="50" cy="52" r="15" fill="#e5e7eb"/><circle cx="50" cy="52" r="8" fill="#374151"/>'
        f'</svg>'),
}

COLOR_WORDS = [("red", "#dc2626"), ("blue", "#2563eb"), ("green", "#16a34a"),
               ("yellow", "#eab308"), ("purple", "#7c3aed"), ("orange", "#ea580c"),
               ("teal", "#0d9488"), ("pink", "#db2777")]

FLAGS = [
    ("France", "linear-gradient(90deg,#0055A4 0 33.33%,#ffffff 33.33% 66.66%,#EF4135 66.66%)"),
    ("Italy", "linear-gradient(90deg,#008C45 0 33.33%,#ffffff 33.33% 66.66%,#CD212A 66.66%)"),
    ("Germany", "linear-gradient(180deg,#000000 0 33.33%,#DD0000 33.33% 66.66%,#FFCE00 66.66%)"),
    ("Netherlands", "linear-gradient(180deg,#AE1C28 0 33.33%,#ffffff 33.33% 66.66%,#21468B 66.66%)"),
    ("Ireland", "linear-gradient(90deg,#169B62 0 33.33%,#ffffff 33.33% 66.66%,#FF883E 66.66%)"),
    ("Belgium", "linear-gradient(90deg,#000000 0 33.33%,#FDDA24 33.33% 66.66%,#EF3340 66.66%)"),
    ("Poland", "linear-gradient(180deg,#ffffff 0 50%,#DC143C 50%)"),
    ("Ukraine", "linear-gradient(180deg,#0057B7 0 50%,#FFDD00 50%)"),
    ("Austria", "linear-gradient(180deg,#ED2939 0 33.33%,#ffffff 33.33% 66.66%,#ED2939 66.66%)"),
    ("Spain", "linear-gradient(180deg,#AA151B 0 25%,#F1BF00 25% 75%,#AA151B 75%)"),
]


def gen_informative():
    items = []

    weather = [("sunny", "Sunny"), ("cloudy", "Cloudy"), ("rain", "Rain"), ("snow", "Snow"),
               ("storm", "Thunderstorms"), ("partly", "Partly cloudy"), ("wind", "Windy"),
               ("fog", "Fog")]
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for kind, label in weather:
        size = rng.choice([80, 96, 110, 128])
        pad = rng.choice([16, 24, 32])
        spec = dict(w=size + pad * 2, h=size + pad * 2, bg=rng.choice(PAGE_BGS),
                    css="#c{display:flex;align-items:center;justify-content:center;}",
                    body=weather_svg(kind, size, "#f5a623"))
        day = rng.choice(days)
        temp = rng.randint(2, 29)
        items.append(make("informative", spec, label, [label.split()[0].lower()], [],
                          "img",
                          '<li class="forecast-day"><span class="day">%s</span>'
                          '<img src="{src}" class="wx"><span class="temp">%d degrees</span></li>'
                          % (day, temp),
                          f"{day}, {temp} degrees",
                          f"weather glyph, {kind}"))

    for filled in [5, 4, 3, 2, 1, 4]:
        size = rng.choice([22, 26, 30, 34])
        color = rng.choice(["#f59e0b", "#eab308", "#f97316", "#111827"])
        pad = rng.choice([12, 18, 24])
        w = size * 5 + 4 * 6 + pad * 2
        spec = dict(w=w, h=size + pad * 2, bg=rng.choice(PAGE_BGS),
                    css="#c{display:flex;align-items:center;justify-content:center;gap:6px;}",
                    body=star_row(5, filled, size, color))
        product = rng.choice(["Walnut desk lamp", "Canvas weekend bag", "Ceramic pour over set",
                              "Merino socks", "Cast iron pan", "Noise cancelling headphones"])
        n = rng.randint(12, 480)
        items.append(make("informative", spec, f"{filled} out of 5 stars",
                          [str(filled), "5", "star"], ["yellow", "shape"], "img",
                          '<div class="rating"><img src="{src}"><span class="count">%d reviews</span>'
                          '</div>' % n,
                          f"{product}, {n} reviews", f"rating widget, {filled} of 5"))

    for pct in [25, 40, 60, 75, 90]:
        size = rng.choice([100, 120, 140])
        accent = rng.choice(ACCENTS)
        pad = rng.choice([14, 22])
        r = size * 0.38
        import math
        circ = 2 * math.pi * r
        dash = circ * pct / 100
        body = (f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
                f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#e5e7eb" '
                f'stroke-width="{size*0.1}"/>'
                f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{accent}" '
                f'stroke-width="{size*0.1}" stroke-linecap="round" '
                f'stroke-dasharray="{dash:.1f} {circ-dash:.1f}" transform="rotate(-90 {size/2} {size/2})"/>'
                f'<text x="{size/2}" y="{size/2+size*0.07}" text-anchor="middle" '
                f'font-family="system-ui, sans-serif" font-size="{size*0.2}" font-weight="700" '
                f'fill="#111827">{pct}%</text></svg>')
        spec = dict(w=size + pad * 2, h=size + pad * 2, bg=rng.choice(PAGE_BGS),
                    css="#c{display:flex;align-items:center;justify-content:center;}", body=body)
        task = rng.choice(["Profile setup", "Course progress", "Upload", "Onboarding checklist",
                           "Backup"])
        items.append(make("informative", spec, f"{pct} percent complete", [str(pct), "complete"], [],
                          "img",
                          '<div class="progress"><h4>%s</h4><img src="{src}"></div>' % task,
                          task, f"progress ring, {pct} percent"))

    badges = [
        ("out_of_stock", "Out of stock", ["out of stock"], "#9ca3af"),
        ("verified", "Verified account", ["verified"], "#16a34a"),
        ("failed", "Payment failed", ["payment", "failed"], "#dc2626"),
        ("pending", "Awaiting approval", ["awaiting", "approval"], "#d97706"),
        ("delivered", "Delivered", ["delivered"], "#0f766e"),
        ("secure", "Secure connection", ["secure"], "#15803d"),
    ]
    badge_shapes = {
        "out_of_stock": '<circle cx="32" cy="32" r="24" fill="none" stroke="{c}" stroke-width="5"/>'
                        '<line x1="16" y1="48" x2="48" y2="16" stroke="{c}" stroke-width="5"/>',
        "verified": '<circle cx="32" cy="32" r="26" fill="{c}"/><polyline points="20,33 29,42 45,24" '
                    'fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" '
                    'stroke-linejoin="round"/>',
        "failed": '<circle cx="32" cy="32" r="26" fill="{c}"/><line x1="23" y1="23" x2="41" y2="41" '
                  'stroke="#fff" stroke-width="5" stroke-linecap="round"/><line x1="41" y1="23" x2="23" '
                  'y2="41" stroke="#fff" stroke-width="5" stroke-linecap="round"/>',
        "pending": '<circle cx="32" cy="32" r="26" fill="none" stroke="{c}" stroke-width="5"/>'
                   '<polyline points="32,16 32,32 43,39" fill="none" stroke="{c}" stroke-width="5" '
                   'stroke-linecap="round"/>',
        "delivered": '<rect x="10" y="24" width="30" height="24" fill="{c}"/><polygon points="40,30 '
                     '50,30 56,38 56,48 40,48" fill="{c}" opacity="0.7"/><circle cx="20" cy="50" r="5" '
                     'fill="#374151"/><circle cx="47" cy="50" r="5" fill="#374151"/>',
        "secure": '<rect x="14" y="28" width="36" height="26" rx="5" fill="{c}"/><path d="M22 28 v-6 '
                  'a10 10 0 0 1 20 0 v6" fill="none" stroke="{c}" stroke-width="5"/>',
    }
    for key, label, must, color in badges:
        size = rng.choice([64, 80, 96])
        pad = rng.choice([14, 20, 28])
        shape = badge_shapes[key].replace("{c}", color)
        spec = dict(w=size + pad * 2, h=size + pad * 2, bg=rng.choice(PAGE_BGS),
                    css="#c{display:flex;align-items:center;justify-content:center;}",
                    body=f'<svg width="{size}" height="{size}" viewBox="0 0 64 64">{shape}</svg>')
        holder = rng.choice(["Order 44120", "Walnut desk lamp", "Rana Ahmed", "Invoice 2291"])
        items.append(make("informative", spec, label, must, ["circle", "shape", "graphic"], "img",
                          '<div class="status"><span>%s</span><img src="{src}"></div>' % holder,
                          holder, f"status badge, {key}"))

    people = [("JD", "Jamie Doyle"), ("RA", "Rana Ahmed"), ("MK", "Mira Kaya"),
              ("TO", "Tom Okafor"), ("LS", "Lena Sorensen")]
    for initials, full in people:
        size = rng.choice([72, 88, 104])
        color = rng.choice(ACCENTS)
        pad = rng.choice([12, 18])
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".a{{width:{size}px;height:{size}px;border-radius:50%;background:{color};color:#fff;"
               f"display:flex;align-items:center;justify-content:center;font-family:{rng.choice(SANS)};"
               f"font-size:{round(size*0.4)}px;font-weight:600;letter-spacing:1px;}}")
        spec = dict(w=size + pad * 2, h=size + pad * 2, bg=rng.choice(PAGE_BGS), css=css,
                    body=f'<div class="a">{initials}</div>')
        items.append(make("informative", spec, f"{full}, profile picture",
                          [full.split()[0].lower()], ["circle", "colored"], "img",
                          '<li class="member"><img src="{src}"><span class="name">%s</span>'
                          '<span class="role">Editor</span></li>' % full,
                          f"{full}, Editor", f"initials avatar for {full}"))

    for country, gradient in rng.sample(FLAGS, 8):
        w = rng.choice([90, 110, 130])
        h = round(w * 0.66)
        pad = rng.choice([12, 18, 24])
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".f{{width:{w}px;height:{h}px;background:{gradient};border:1px solid #d4d4d8;}}")
        spec = dict(w=w + pad * 2, h=h + pad * 2, bg=rng.choice(PAGE_BGS), css=css,
                    body='<div class="f"></div>')
        items.append(make("informative", spec, f"Flag of {country}", [country.lower(), "flag"], [],
                          "img",
                          '<li class="lang"><img src="{src}"><a href="/%s">%s</a></li>'
                          % (country.lower()[:2], country),
                          f"Choose your country: {country}", f"flag of {country}"))

    prod_names = {"mug": "mug", "box": "cardboard box", "book": "hardback book",
                  "bottle": "water bottle", "shirt": "t-shirt", "lamp": "table lamp",
                  "plant": "potted plant", "phone": "smartphone", "chair": "armchair",
                  "camera": "camera"}
    for key, draw in PRODUCTS.items():
        word, col = rng.choice(COLOR_WORDS)
        size = rng.choice([110, 130, 150])
        pad = rng.choice([16, 24, 32])
        name = prod_names[key]
        spec = dict(w=size + pad * 2, h=size + pad * 2, bg=rng.choice(["#ffffff", "#fafafa", "#f8fafc"]),
                    css="#c{display:flex;align-items:center;justify-content:center;}",
                    body=draw(size, col))
        price = f"{rng.randint(9, 89)}.00"
        items.append(make("informative", spec, f"A {word} {name}", [word, name.split()[-1]], [],
                          "img",
                          '<figure class="product"><img src="{src}"><figcaption>%s, %s</figcaption>'
                          '</figure>' % (name.capitalize(), price),
                          f"{name.capitalize()}, {price}", f"product rendering, {word} {name}"))

    routes = [("the office", "the station"), ("Mill Lane", "the harbour"),
              ("the hotel", "the museum"), ("home", "the airport"), ("the depot", "the warehouse")]
    for start, end in routes:
        w = rng.choice([220, 260, 300])
        h = round(w * 0.68)
        pad = 14
        accent = rng.choice(ACCENTS)
        grid = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}" stroke="#e5e7eb" stroke-width="1"/>'
                       for x in range(0, w, 28))
        grid += "".join(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}" stroke="#e5e7eb" stroke-width="1"/>'
                        for y in range(0, h, 28))
        x1, y1 = round(w * 0.2), round(h * 0.72)
        x2, y2 = round(w * 0.78), round(h * 0.26)
        pin = ('<g transform="translate({x},{y})"><path d="M0 0 c-9-12-14-17-14-24 a14 14 0 1 1 28 0 '
               'c0 7-5 12-14 24z" fill="{c}"/><circle cx="0" cy="-24" r="5" fill="#fff"/></g>')
        body = (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#f8fafc"/>{grid}'
                f'<path d="M{x1} {y1} L{round(w*0.42)} {round(h*0.62)} L{round(w*0.5)} {round(h*0.35)} '
                f'L{x2} {y2}" fill="none" stroke="{accent}" stroke-width="4" stroke-dasharray="8 6" '
                f'stroke-linecap="round"/>'
                + pin.format(x=x1, y=y1, c="#dc2626") + pin.format(x=x2, y=y2, c=accent) + '</svg>')
        spec = dict(w=w + pad * 2, h=h + pad * 2, bg="#ffffff",
                    css="#c{display:flex;align-items:center;justify-content:center;}", body=body)
        items.append(make("informative", spec, f"Map showing the route from {start} to {end}",
                          ["map", "route"], [], "img",
                          '<figure class="directions"><img src="{src}"><figcaption>Walking route, '
                          '12 minutes</figcaption></figure>',
                          "Walking route, 12 minutes", f"map with route, {start} to {end}"))

    scenes = [
        ("house_sun", "A house at sunrise", ["house", "sun"]),
        ("tree_moon", "A tree under a full moon", ["tree", "moon"]),
        ("mountain", "Mountains at sunset", ["mountain", "sun"]),
        ("boat", "A sailing boat on the sea", ["boat", "sea"]),
        ("skyline", "A city skyline at night", ["city", "night"]),
        ("campfire", "A campfire under the stars", ["campfire", "stars"]),
        ("bridge", "A bridge over a river", ["bridge", "river"]),
    ]
    for key, alt, must in scenes:
        w = rng.choice([200, 240, 280])
        h = round(w * 0.7)
        body = scene_svg(key, w, h)
        spec = dict(w=w, h=h, bg="#ffffff", css="#c{display:block;}", body=body)
        items.append(make("informative", spec, alt, must, [], "img",
                          '<figure class="illustration"><img src="{src}"><figcaption>%s</figcaption>'
                          '</figure>' % alt,
                          alt, f"composed scene, {key}"))
    return items


def scene_svg(key, w, h):
    if key == "house_sun":
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#ffe7c2"/>'
                f'<circle cx="{w*0.76}" cy="{h*0.28}" r="{h*0.13}" fill="#f97316"/>'
                f'<rect x="0" y="{h*0.72}" width="{w}" height="{h*0.28}" fill="#86a06a"/>'
                f'<rect x="{w*0.24}" y="{h*0.45}" width="{w*0.3}" height="{h*0.3}" fill="#f5f0e6"/>'
                f'<polygon points="{w*0.2},{h*0.45} {w*0.39},{h*0.28} {w*0.58},{h*0.45}" fill="#b45309"/>'
                f'<rect x="{w*0.36}" y="{h*0.58}" width="{w*0.07}" height="{h*0.17}" fill="#7c3f13"/>'
                f'</svg>')
    if key == "tree_moon":
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#111c3a"/>'
                f'<circle cx="{w*0.74}" cy="{h*0.26}" r="{h*0.12}" fill="#f8f4d8"/>'
                f'<rect x="0" y="{h*0.8}" width="{w}" height="{h*0.2}" fill="#1c2b1a"/>'
                f'<rect x="{w*0.32}" y="{h*0.52}" width="{w*0.05}" height="{h*0.3}" fill="#4b3a25"/>'
                f'<circle cx="{w*0.345}" cy="{h*0.44}" r="{h*0.17}" fill="#2f5d3a"/>'
                f'<circle cx="{w*0.27}" cy="{h*0.52}" r="{h*0.11}" fill="#356a42"/>'
                f'<circle cx="{w*0.42}" cy="{h*0.52}" r="{h*0.11}" fill="#356a42"/></svg>')
    if key == "mountain":
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#fcd9a8"/>'
                f'<circle cx="{w*0.5}" cy="{h*0.5}" r="{h*0.16}" fill="#ef6c33"/>'
                f'<polygon points="0,{h} {w*0.34},{h*0.3} {w*0.66},{h}" fill="#5b6470"/>'
                f'<polygon points="{w*0.34},{h*0.3} {w*0.42},{h*0.42} {w*0.26},{h*0.42}" fill="#eef2f6"/>'
                f'<polygon points="{w*0.42},{h} {w*0.74},{h*0.42} {w},{h}" fill="#727d8a"/></svg>')
    if key == "boat":
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#cfe8f7"/>'
                f'<rect x="0" y="{h*0.66}" width="{w}" height="{h*0.34}" fill="#2f80c2"/>'
                f'<polygon points="{w*0.5},{h*0.2} {w*0.5},{h*0.62} {w*0.28},{h*0.62}" fill="#f8fafc"/>'
                f'<polygon points="{w*0.53},{h*0.28} {w*0.53},{h*0.62} {w*0.72},{h*0.62}" fill="#e2e8f0"/>'
                f'<polygon points="{w*0.22},{h*0.64} {w*0.78},{h*0.64} {w*0.66},{h*0.76} {w*0.34},{h*0.76}"'
                f' fill="#7c3f13"/></svg>')
    if key == "skyline":
        bars = ""
        x = 0.06
        rng2 = random.Random(11)
        while x < 0.94:
            bw = rng2.uniform(0.06, 0.11)
            bh = rng2.uniform(0.22, 0.55)
            bars += (f'<rect x="{w*x}" y="{h*(0.85-bh)}" width="{w*bw*0.9}" height="{h*bh}" '
                     f'fill="#2b3550"/>')
            for wy in range(3):
                bars += (f'<rect x="{w*(x+0.02)}" y="{h*(0.82-bh+0.07*wy)}" width="{w*0.02}" '
                         f'height="{h*0.03}" fill="#ffd88a"/>')
            x += bw
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#0f1730"/>'
                f'<circle cx="{w*0.16}" cy="{h*0.2}" r="{h*0.08}" fill="#f8f4d8"/>{bars}'
                f'<rect x="0" y="{h*0.85}" width="{w}" height="{h*0.15}" fill="#070c1c"/></svg>')
    if key == "campfire":
        stars = "".join(f'<circle cx="{w*random.Random(i).uniform(0.05,0.95)}" '
                        f'cy="{h*random.Random(i+50).uniform(0.05,0.5)}" r="1.8" fill="#fff"/>'
                        for i in range(18))
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<rect width="{w}" height="{h}" fill="#0b1226"/>{stars}'
                f'<rect x="0" y="{h*0.82}" width="{w}" height="{h*0.18}" fill="#1b2030"/>'
                f'<polygon points="{w*0.5},{h*0.48} {w*0.6},{h*0.82} {w*0.4},{h*0.82}" fill="#f97316"/>'
                f'<polygon points="{w*0.5},{h*0.62} {w*0.56},{h*0.82} {w*0.44},{h*0.82}" fill="#fbbf24"/>'
                f'<rect x="{w*0.34}" y="{h*0.82}" width="{w*0.32}" height="{h*0.035}" fill="#7c3f13" '
                f'transform="rotate(-8 {w*0.5} {h*0.83})"/></svg>')
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="#dfeff7"/>'
            f'<rect x="0" y="{h*0.62}" width="{w}" height="{h*0.38}" fill="#4a90c2"/>'
            f'<rect x="{w*0.05}" y="{h*0.44}" width="{w*0.9}" height="{h*0.06}" fill="#6b7280"/>'
            f'<path d="M{w*0.1} {h*0.5} q{w*0.15} {h*0.22} {w*0.3} 0" fill="none" stroke="#6b7280" '
            f'stroke-width="5"/>'
            f'<path d="M{w*0.45} {h*0.5} q{w*0.15} {h*0.22} {w*0.3} 0" fill="none" stroke="#6b7280" '
            f'stroke-width="5"/>'
            f'<rect x="{w*0.08}" y="{h*0.3} " width="{w*0.03}" height="{h*0.16}" fill="#6b7280"/>'
            f'<rect x="{w*0.88}" y="{h*0.3}" width="{w*0.03}" height="{h*0.16}" fill="#6b7280"/></svg>')


# ---------------------------------------------------------------- decorative

DECOR_CONTEXTS = [
    ("div", '<section><p>...end of the introduction.</p></section><div class="divider">'
            '<img src="{src}"></div><section><h2>How we work</h2>', "How we work"),
    ("div", '<article><p>...and that was the first year.</p><div class="ornament">'
            '<img src="{src}"></div><p>The second year began quietly.</p></article>',
     "The second year began quietly."),
    ("span", '<h2 class="section-title">Our team<span class="flourish"><img src="{src}"></span></h2>',
     "Our team"),
    ("div", '<div class="hero-backdrop"><img src="{src}"><h1>Built for small kitchens</h1></div>',
     "Built for small kitchens"),
    ("div", '<footer><div class="footer-pattern"><img src="{src}"></div><p>Copyright 2026 '
            'Kestrel Books</p></footer>', "Copyright 2026 Kestrel Books"),
    ("li", '<li class="feature"><img src="{src}" class="bullet"><span>Free returns for 30 days</span>'
           '</li>', "Free returns for 30 days"),
    ("div", '<div class="card"><img src="{src}" class="card-corner"><h3>Weekly digest</h3>'
            '<p>One email, every Friday.</p></div>', "Weekly digest"),
    ("div", '<section class="pricing"></section><div class="separator"><img src="{src}"></div>'
            '<section class="faq"><h2>Questions</h2></section>', "Questions"),
]


def gen_decorative():
    items = []

    def add(spec, note):
        tag, html, nearby = rng.choice(DECOR_CONTEXTS)
        items.append(make("decorative", spec, "", [], [], tag, html, nearby, note))

    # rules and dividers
    for i in range(11):
        w = rng.choice([240, 300, 360, 420])
        h = rng.choice([28, 36, 44])
        color = rng.choice(["#94a3b8", "#cbd5e1", "#d6bfa5", "#c4b5fd", "#9ca3af", "#e5b299"])
        kind = i % 5
        mid = h / 2
        if kind == 0:
            body = (f'<svg width="{w}" height="{h}"><line x1="10" y1="{mid}" x2="{w*0.42}" y2="{mid}" '
                    f'stroke="{color}" stroke-width="1.5"/><circle cx="{w/2}" cy="{mid}" r="4" '
                    f'fill="{color}"/><line x1="{w*0.58}" y1="{mid}" x2="{w-10}" y2="{mid}" '
                    f'stroke="{color}" stroke-width="1.5"/></svg>')
        elif kind == 1:
            body = (f'<svg width="{w}" height="{h}"><line x1="10" y1="{mid}" x2="{w*0.44}" y2="{mid}" '
                    f'stroke="{color}" stroke-width="1.5"/><rect x="{w/2-5}" y="{mid-5}" width="10" '
                    f'height="10" transform="rotate(45 {w/2} {mid})" fill="{color}"/>'
                    f'<line x1="{w*0.56}" y1="{mid}" x2="{w-10}" y2="{mid}" stroke="{color}" '
                    f'stroke-width="1.5"/></svg>')
        elif kind == 2:
            body = (f'<svg width="{w}" height="{h}"><line x1="10" y1="{mid-3}" x2="{w-10}" y2="{mid-3}" '
                    f'stroke="{color}" stroke-width="2"/><line x1="30" y1="{mid+3}" x2="{w-30}" '
                    f'y2="{mid+3}" stroke="{color}" stroke-width="1"/></svg>')
        elif kind == 3:
            body = (f'<svg width="{w}" height="{h}"><line x1="10" y1="{mid}" x2="{w-10}" y2="{mid}" '
                    f'stroke="{color}" stroke-width="2" stroke-dasharray="'
                    f'{rng.choice(["6 6", "2 8", "12 5", "1 5"])}" stroke-linecap="round"/></svg>')
        else:
            body = (f'<div style="width:{w-20}px;height:2px;margin:{mid-1}px 10px;background:'
                    f'linear-gradient(90deg,transparent,{color},transparent)"></div>')
        add(dict(w=w, h=h, bg=rng.choice(PAGE_BGS),
                 css="#c{display:flex;align-items:center;justify-content:center;}", body=body),
            f"divider rule, variant {kind}")

    # swashes and flourishes
    for i in range(9):
        w = rng.choice([200, 250, 300])
        h = rng.choice([60, 80, 100])
        color = rng.choice(["#a16207", "#7c3aed", "#0f766e", "#b91c1c", "#334155", "#be185d"])
        sw = rng.choice([1.5, 2, 2.5, 3])
        curls = "".join(
            f'<path d="M{w*0.1} {h*0.5} q{w*0.2} -{h*(0.3+0.1*j)} {w*0.4} 0 q{w*0.2} '
            f'{h*(0.3+0.1*j)} {w*0.4} 0" fill="none" stroke="{color}" stroke-width="{sw}" '
            f'opacity="{0.9 - 0.25*j}"/>' for j in range(i % 3 + 1))
        dots = "".join(f'<circle cx="{w*(0.1+0.8*k)}" cy="{h*0.5}" r="{sw*1.4}" fill="{color}"/>'
                       for k in (0, 1))
        add(dict(w=w, h=h, bg=rng.choice(PAGE_BGS),
                 css="#c{display:flex;align-items:center;justify-content:center;}",
                 body=f'<svg width="{w}" height="{h}">{curls}{dots}</svg>'),
            f"flourish swash, {i}")

    # gradient blobs
    for i in range(9):
        size = rng.choice([140, 180, 220, 260])
        c1 = rng.choice(ACCENTS)
        c2 = rng.choice(ACCENTS)
        shape = rng.choice(["50% 50% 50% 50% / 60% 60% 40% 40%",
                            "40% 60% 65% 35% / 55% 40% 60% 45%",
                            "70% 30% 30% 70% / 60% 40% 60% 40%", "50%"])
        angle = rng.choice([25, 60, 120, 210, 315])
        css = (f"#c{{display:flex;align-items:center;justify-content:center;}}"
               f".b{{width:{size}px;height:{round(size*rng.uniform(0.7,1.0))}px;border-radius:{shape};"
               f"background:linear-gradient({angle}deg,{tint(c1,0.85)},{tint(c2,0.35)});"
               f"filter:blur({rng.choice([0, 0, 3, 8])}px);}}")
        add(dict(w=size + 30, h=size + 30, bg=rng.choice(PAGE_BGS), css=css, body='<div class="b"></div>'),
            f"gradient blob, {i}")

    # corner ornaments
    for i in range(6):
        size = rng.choice([90, 110, 130])
        color = rng.choice(["#a16207", "#334155", "#0f766e", "#b45309"])
        sw = rng.choice([2, 3, 4])
        body = (f'<svg width="{size}" height="{size}">'
                f'<path d="M8 {size-8} L8 30 q0 -22 22 -22 L{size-8} 8" fill="none" stroke="{color}" '
                f'stroke-width="{sw}"/>'
                f'<path d="M20 {size-8} L20 38 q0 -18 18 -18 L{size-8} 20" fill="none" stroke="{color}" '
                f'stroke-width="{sw*0.6}" opacity="0.6"/>'
                f'<circle cx="30" cy="30" r="{sw*1.6}" fill="{color}"/></svg>')
        add(dict(w=size + 20, h=size + 20, bg=rng.choice(PAGE_BGS),
                 css="#c{display:flex;align-items:center;justify-content:center;}", body=body),
            f"corner ornament, {i}")

    # dot and hatch patterns
    for i in range(8):
        w = rng.choice([180, 220, 280])
        h = rng.choice([60, 90, 120])
        color = rng.choice(["#cbd5e1", "#e5e7eb", "#d6bfa5", "#c7d2fe", "#bbf7d0"])
        step = rng.choice([10, 14, 18])
        if i % 2 == 0:
            body = ("".join(f'<circle cx="{x}" cy="{y}" r="{rng.choice([1.5, 2, 2.5])}" fill="{color}"/>'
                            for x in range(8, w - 4, step) for y in range(8, h - 4, step)))
        else:
            body = ("".join(f'<line x1="{x}" y1="0" x2="{x - h}" y2="{h}" stroke="{color}" '
                            f'stroke-width="{rng.choice([2, 3, 4])}"/>' for x in range(0, w + h, step + 6)))
        add(dict(w=w, h=h, bg=rng.choice(PAGE_BGS), css="#c{display:block;}",
                 body=f'<svg width="{w}" height="{h}">{body}</svg>'),
            f"pattern fill, {i}")

    # section separators, waves and zigzags
    for i in range(8):
        w = rng.choice([320, 400, 480])
        h = rng.choice([40, 56, 72])
        color = rng.choice(["#dbeafe", "#e0f2fe", "#fee2e2", "#ede9fe", "#dcfce7", "#f1f5f9"])
        if i % 2 == 0:
            body = (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><path d="M0 {h*0.6} '
                    f'q{w*0.12} -{h*0.5} {w*0.25} 0 t{w*0.25} 0 t{w*0.25} 0 t{w*0.25} 0 V{h} H0 Z" '
                    f'fill="{color}"/></svg>')
        else:
            pts = " ".join(f"{x},{h*0.3 if (x // (w // 8)) % 2 == 0 else h*0.7}"
                           for x in range(0, w + 1, max(1, w // 8)))
            body = (f'<svg width="{w}" height="{h}"><polyline points="{pts}" fill="none" '
                    f'stroke="{mix(color, "#000000", 0.25)}" stroke-width="{rng.choice([3, 4, 6])}" '
                    f'stroke-linejoin="round"/></svg>')
        add(dict(w=w, h=h, bg=rng.choice(PAGE_BGS), css="#c{display:block;}", body=body),
            f"section separator, {i}")

    # bullet graphics and spacers
    for i in range(8):
        size = rng.choice([28, 36, 44, 52])
        color = rng.choice(ACCENTS)
        kind = i % 4
        if kind == 0:
            inner = f'<circle cx="{size/2}" cy="{size/2}" r="{size*0.3}" fill="{color}"/>'
        elif kind == 1:
            inner = (f'<rect x="{size*0.2}" y="{size*0.2}" width="{size*0.6}" height="{size*0.6}" '
                     f'transform="rotate(45 {size/2} {size/2})" fill="{color}"/>')
        elif kind == 2:
            inner = (f'<circle cx="{size/2}" cy="{size/2}" r="{size*0.32}" fill="none" stroke="{color}" '
                     f'stroke-width="{size*0.1}"/>')
        else:
            inner = (f'<polygon points="{size*0.25},{size*0.2} {size*0.78},{size*0.5} {size*0.25},'
                     f'{size*0.8}" fill="{color}"/>')
        pad = rng.choice([18, 24, 30])
        add(dict(w=size + pad * 2, h=size + pad * 2, bg=rng.choice(PAGE_BGS),
                 css="#c{display:flex;align-items:center;justify-content:center;}",
                 body=f'<svg width="{size}" height="{size}">{inner}</svg>'),
            f"stylistic bullet, {kind}")
    return items


# ---------------------------------------------------------------- image of text

WORDMARKS = [
    "Kestrel Books", "Northwind Tea", "Marrow & Co", "Lumen Health", "Tidewater Bank",
    "Foxglove Studio", "Copperline", "Halcyon Travel", "Bramble Grocers", "Quill & Sable",
]

PROMOS = [
    "50% OFF this weekend", "Free shipping over 50", "Buy one get one free",
    "Summer sale starts Friday", "New arrivals every Thursday", "Members save 20% today",
    "Last 3 days of the winter sale", "Order by 6pm for next day delivery",
]

QUOTES = [
    ("The best time to plant a tree was twenty years ago.", "Old proverb"),
    ("We shape our buildings, and afterwards our buildings shape us.", "W. Churchill"),
    ("Simplicity is a great virtue but it requires hard work.", "E. Dijkstra"),
    ("A change of perspective is worth 80 IQ points.", "A. Kay"),
    ("Everything should be made as simple as possible.", "A. Einstein"),
    ("The details are not the details, they make the design.", "C. Eames"),
]

HEADINGS = [
    "How our returns work", "Meet the founders", "Frequently asked questions",
    "What is in the box", "Our 2026 impact report", "Delivery and collection",
]

ADDRESSES = [
    ["Kestrel Books", "14 Mill Lane", "Bristol BS1 4TR"],
    ["Northwind Tea", "Unit 7, Harbour Road", "Leith EH6 6QQ"],
    ["Lumen Health", "220 Ashfield Street", "Manchester M14 5PP"],
    ["Foxglove Studio", "3rd floor, 8 Peach Yard", "London E2 8AA"],
    ["Bramble Grocers", "44 Market Square", "York YO1 8SN"],
]

PHONES = ["0117 496 2210", "+44 20 7946 0912", "(555) 014-2200", "0800 555 0199"]

CAPTCHA_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def gen_image_of_text():
    items = []

    for brand in WORDMARKS:
        fonts = SERIF if rng.random() < 0.5 else SANS
        font = rng.choice(fonts)
        fs = rng.choice([30, 36, 42, 48])
        color = rng.choice(DARKS + ACCENTS)
        weight = rng.choice([500, 600, 700])
        spacing = rng.choice(["0", "1px", "2px", "-1px"])
        transform = rng.choice(["none", "none", "uppercase"])
        text = brand.upper() if transform == "uppercase" else brand
        w = int(len(text) * fs * 0.66) + 60
        h = fs * 2 + 30
        css = (f"#c{{display:flex;align-items:center;justify-content:center;font-family:{font};}}"
               f".t{{font-size:{fs}px;font-weight:{weight};letter-spacing:{spacing};color:{color};"
               f"white-space:nowrap;}}")
        spec = dict(w=w, h=h, bg=rng.choice(PAGE_BGS), css=css, body=f'<div class="t">{text}</div>')
        items.append(make("image_of_text", spec, brand, keywords(brand, 2), [],
                          "img",
                          '<div class="partner-logos"><img src="{src}"><img src="/img/partner-2.png">'
                          '</div>', "Trusted by", f"wordmark, {brand}"))

    for promo in PROMOS:
        font = rng.choice(SANS)
        fs = rng.choice([26, 32, 38])
        c1 = rng.choice(ACCENTS)
        c2 = rng.choice(ACCENTS)
        w = min(760, int(len(promo) * fs * 0.44) + 90)
        h = fs * 3 + 26
        css = (f"#c{{display:flex;align-items:center;justify-content:center;text-align:center;"
               f"font-family:{font};background:linear-gradient({rng.choice([90, 135, 180])}deg,"
               f"{c1},{c2});}}"
               f".t{{color:#fff;font-size:{fs}px;font-weight:800;line-height:1.25;padding:0 24px;"
               f"letter-spacing:{rng.choice(['0', '0.5px'])};}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css, body=f'<div class="t">{promo}</div>')
        items.append(make("image_of_text", spec, promo, keywords(promo, 3), [],
                          "img", '<a href="/sale" class="promo-banner"><img src="{src}"></a>',
                          "Shop the sale", f"promo banner, {promo}"))

    for quote, who in QUOTES:
        font = rng.choice(SERIF)
        fs = rng.choice([20, 24, 28])
        w = rng.choice([420, 480, 540])
        h = rng.choice([180, 210, 240])
        color = rng.choice(DARKS)
        bg = rng.choice(["#fffaf0", "#f8fafc", "#f5f3ff", "#ffffff", "#f0fdf4"])
        css = (f"#c{{display:flex;flex-direction:column;align-items:center;justify-content:center;"
               f"font-family:{font};padding:26px;text-align:center;}}"
               f".q{{font-size:{fs}px;line-height:1.45;color:{color};font-style:italic;}}"
               f".w{{margin-top:16px;font-size:{fs-6}px;color:#6b7280;}}")
        spec = dict(w=w, h=h, bg=bg, css=css,
                    body=f'<div class="q">&ldquo;{quote}&rdquo;</div><div class="w">{who}</div>')
        text = f"{quote} {who}"
        items.append(make("image_of_text", spec, text, keywords(quote, 3), [],
                          "figure",
                          '<figure class="pull-quote"><img src="{src}"></figure>',
                          "From the interview", f"quote card, {who}"))

    for heading in HEADINGS:
        font = rng.choice(SANS + SERIF)
        fs = rng.choice([30, 36, 44])
        color = rng.choice(DARKS + ACCENTS)
        w = min(720, int(len(heading) * fs * 0.55) + 60)
        h = fs * 2 + 24
        css = (f"#c{{display:flex;align-items:center;justify-content:flex-start;font-family:{font};"
               f"padding-left:24px;}}"
               f".t{{font-size:{fs}px;font-weight:700;color:{color};white-space:nowrap;}}")
        spec = dict(w=w, h=h, bg=rng.choice(PAGE_BGS), css=css, body=f'<div class="t">{heading}</div>')
        items.append(make("image_of_text", spec, heading, keywords(heading, 3), [],
                          "img", '<section><img src="{src}" class="heading-image"><p>We keep it '
                                 'simple.</p></section>', "We keep it simple.",
                          f"heading rendered as an image, {heading}"))

    for i in range(6):
        length = rng.choice([5, 6])
        text = "".join(rng.choice(CAPTCHA_ALPHABET) for _ in range(length))
        fs = rng.choice([32, 38, 44])
        w = length * fs + 60
        h = fs * 2 + 30
        chars = ""
        for ch in text:
            rot = rng.uniform(-24, 24)
            dy = rng.uniform(-6, 6)
            chars += (f'<span style="display:inline-block;transform:rotate({rot:.1f}deg) '
                      f'translateY({dy:.1f}px);font-size:{fs + rng.randint(-4, 4)}px;'
                      f'color:{rng.choice(DARKS)};margin:0 {rng.randint(1, 5)}px">{ch}</span>')
        noise = "".join(f'<line x1="{rng.randint(0, w)}" y1="{rng.randint(0, h)}" '
                        f'x2="{rng.randint(0, w)}" y2="{rng.randint(0, h)}" stroke="#9ca3af" '
                        f'stroke-width="1"/>' for _ in range(6))
        css = (f"#c{{display:flex;align-items:center;justify-content:center;font-family:"
               f"{rng.choice(SERIF + MONO)};position:relative;}}"
               f"svg{{position:absolute;inset:0;}}"
               f".t{{position:relative;z-index:2;letter-spacing:2px;}}")
        spec = dict(w=w, h=h, bg=rng.choice(["#f3f4f6", "#eef2ff", "#fef3c7"]), css=css,
                    body=f'<svg width="{w}" height="{h}">{noise}</svg><div class="t">{chars}</div>')
        items.append(make("image_of_text", spec, text, [text], [],
                          "img",
                          '<div class="captcha"><label for="cap">Type the characters you see</label>'
                          '<img src="{src}"><input id="cap" name="cap"></div>',
                          "Type the characters you see", "distorted character string"))

    for lines in ADDRESSES:
        font = rng.choice(SANS + SERIF)
        fs = rng.choice([17, 20, 23])
        w = max(len(l) for l in lines) * fs * 0.6 + 60
        h = fs * len(lines) * 1.7 + 40
        css = (f"#c{{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;"
               f"font-family:{font};padding:20px;gap:{round(fs*0.35)}px;}}"
               f".l{{font-size:{fs}px;color:{rng.choice(DARKS)};}}"
               f".l:first-child{{font-weight:700;}}")
        body = "".join(f'<div class="l">{l}</div>' for l in lines)
        spec = dict(w=round(w), h=round(h), bg=rng.choice(PAGE_BGS), css=css, body=body)
        text = ", ".join(lines)
        items.append(make("image_of_text", spec, text, keywords(" ".join(lines[1:]), 2), [],
                          "img",
                          '<address><img src="{src}"></address><p>Open Monday to Saturday.</p>',
                          "Open Monday to Saturday.", "address block rendered as an image"))

    for phone in PHONES:
        font = rng.choice(SANS + MONO)
        fs = rng.choice([26, 32, 38])
        accent = rng.choice(ACCENTS)
        w = int(len(phone) * fs * 0.62) + 100
        h = fs * 2 + 30
        css = (f"#c{{display:flex;align-items:center;justify-content:center;gap:12px;"
               f"font-family:{font};}}"
               f".t{{font-size:{fs}px;font-weight:700;color:{accent};white-space:nowrap;}}")
        spec = dict(w=w, h=h, bg=rng.choice(PAGE_BGS), css=css,
                    body=f'{icon("phone", fs, accent, 2)}<div class="t">{phone}</div>')
        items.append(make("image_of_text", spec, phone, [phone.lower()], [],
                          "img", '<div class="contact-strip"><img src="{src}"></div>',
                          "Call us, 9am to 5pm", f"phone number as an image, {phone}"))

    stylised = [
        "Doors open at 7", "Thank you for 10 years", "Now hiring bakers",
        "Closed for refurbishment", "Winter menu is here", "Join the waiting list",
    ]
    for text in stylised:
        font = rng.choice(SERIF + SANS)
        fs = rng.choice([28, 34, 40])
        c1, c2 = rng.sample(ACCENTS, 2)
        w = min(700, int(len(text) * fs * 0.58) + 80)
        h = fs * 3
        css = (f"#c{{display:flex;align-items:center;justify-content:center;font-family:{font};"
               f"background:linear-gradient({rng.choice([45, 135, 225])}deg,{mix(c1, '#ffffff', 0.7)},"
               f"{mix(c2, '#ffffff', 0.5)});}}"
               f".t{{font-size:{fs}px;font-weight:700;color:{mix(c1, '#000000', 0.35)};"
               f"letter-spacing:{rng.choice(['0.5px', '1px', '2px'])};white-space:nowrap;}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css, body=f'<div class="t">{text}</div>')
        items.append(make("image_of_text", spec, text, keywords(text, 3), [], "img",
                          '<div class="notice"><img src="{src}"></div>', "Latest news",
                          f"stylised text on a gradient, {text}"))

    events = [
        ("Repair cafe", "Saturday 14 March, 10am"), ("Book club", "Thursday 2 April, 7pm"),
        ("Winter market", "Sunday 8 December, 11am"), ("Open studio", "Friday 20 June, 6pm"),
        ("Coffee tasting", "Tuesday 5 May, 5pm"),
    ]
    for title, when in events:
        font = rng.choice(SANS)
        w = rng.choice([320, 380, 440])
        h = rng.choice([150, 180])
        accent = rng.choice(ACCENTS)
        css = (f"#c{{display:flex;flex-direction:column;align-items:center;justify-content:center;"
               f"font-family:{font};gap:10px;border:3px solid {accent};}}"
               f".a{{font-size:{rng.choice([28, 32])}px;font-weight:800;color:{accent};}}"
               f".b{{font-size:{rng.choice([16, 18])}px;color:#374151;}}")
        spec = dict(w=w, h=h, bg=rng.choice(["#ffffff", "#fffdf7", "#f8fafc"]), css=css,
                    body=f'<div class="a">{title}</div><div class="b">{when}</div>')
        text = f"{title}. {when}"
        items.append(make("image_of_text", spec, text, keywords(title, 2), [], "a",
                          '<a href="/events/repair-cafe"><img src="{src}"></a>', "Upcoming events",
                          f"event card, {title}"))
    return items


# ---------------------------------------------------------------- complex

CHART_DATA = [
    ("Total sales by quarter", [("Q1", 48), ("Q2", 62), ("Q3", 71), ("Q4", 55)], "thousand pounds"),
    ("Support tickets by channel", [("Email", 82), ("Chat", 47), ("Phone", 31)], "tickets"),
    ("Weekly signups", [("Mon", 24), ("Tue", 38), ("Wed", 45), ("Thu", 33), ("Fri", 52)], "signups"),
    ("Energy use by floor", [("Ground", 64), ("First", 39), ("Second", 27), ("Third", 18)], "kWh"),
    ("Books borrowed by genre", [("Fiction", 76), ("History", 41), ("Poetry", 22), ("Science", 35)],
     "loans"),
    ("Average delivery time", [("North", 32), ("South", 44), ("East", 27), ("West", 51)], "hours"),
    ("Site visits by device", [("Mobile", 68), ("Desktop", 25), ("Tablet", 12)], "percent"),
    ("Rainfall by month", [("Jan", 88), ("Feb", 61), ("Mar", 47), ("Apr", 35), ("May", 29)],
     "millimetres"),
    ("Volunteers by branch", [("Leith", 19), ("Mill Lane", 44), ("Harbour", 26)], "people"),
    ("Errors per release", [("v1.2", 57), ("v1.3", 39), ("v1.4", 21), ("v1.5", 14)], "errors"),
    ("Members by plan", [("Free", 54), ("Standard", 31), ("Premium", 15)], "percent"),
    ("Cups served per day", [("Mon", 91), ("Tue", 78), ("Wed", 84), ("Thu", 96), ("Fri", 120)],
     "cups"),
    ("Repairs completed", [("Bikes", 63), ("Laptops", 28), ("Kettles", 17), ("Radios", 11)],
     "items"),
    ("Newsletter opens", [("Week 1", 42), ("Week 2", 55), ("Week 3", 61), ("Week 4", 49)], "percent"),
    ("Stock by warehouse", [("Bristol", 73), ("Leeds", 46), ("Cardiff", 38), ("Derby", 25)], "pallets"),
    ("Course completion", [("Design", 88), ("Coding", 64), ("Writing", 52)], "percent"),
]

CHART_CONTEXTS = [
    ("figure", '<figure class="chart"><img src="{src}"><figcaption>{title}</figcaption></figure>',
     "{title}"),
    ("img", '<section class="report"><h2>{title}</h2><img src="{src}"><p>Source: internal '
            'dashboard.</p></section>', "{title}"),
    ("img", '<div class="card metric"><h3>{title}</h3><img src="{src}"><a href="/reports/full">'
            'See the full report</a></div>', "{title}, see the full report"),
]


def chart_context(title):
    tag, html, nearby = rng.choice(CHART_CONTEXTS)
    return tag, html.replace("{title}", title), nearby.replace("{title}", title)


def complex_item(title, kind, pairs, unit, spec):
    values = [str(v) for _, v in pairs]
    labels = [k for k, _ in pairs]
    parts = ", ".join(f"{k} {v}" for k, v in pairs)
    expected = f"{kind} titled {title}. {parts}."
    must = keywords(title, 3) + values
    tag, html, nearby = chart_context(title)
    return make("complex", spec, expected, must, [], tag, html, nearby,
                f"{kind}, values {'/'.join(values)}")


def gen_complex():
    items = []
    data = CHART_DATA

    def bar_chart(title, pairs, unit, horizontal=False):
        font = rng.choice(SANS)
        accent = rng.choice(ACCENTS)
        multi = rng.random() < 0.4
        colors = [rng.choice(ACCENTS) for _ in pairs] if multi else [accent] * len(pairs)
        top = max(v for _, v in pairs)
        if horizontal:
            w = rng.choice([420, 480, 540])
            h = 90 + len(pairs) * rng.choice([38, 44, 50])
            rows = "".join(
                f'<div class="row"><span class="lab">{k}</span>'
                f'<span class="bar" style="width:{round(v/top*100*0.72)}%;background:{colors[i]}">'
                f'</span><span class="val">{v}</span></div>'
                for i, (k, v) in enumerate(pairs))
            css = (f"#c{{font-family:{font};padding:18px 22px;}}"
                   f"h3{{margin:0 0 14px;font-size:{rng.choice([17, 19])}px;color:#111827;}}"
                   f".row{{display:flex;align-items:center;gap:10px;margin-bottom:10px;font-size:13px;}}"
                   f".lab{{width:76px;color:#374151;text-align:right;}}"
                   f".bar{{height:16px;border-radius:3px;}}"
                   f".val{{color:#111827;font-weight:600;}}")
            body = f"<h3>{title}</h3>{rows}"
            return dict(w=w, h=h, bg="#ffffff", css=css, body=body), "Horizontal bar chart"
        w = rng.choice([380, 440, 500])
        h = rng.choice([260, 300, 340])
        bars = "".join(
            f'<div class="col"><span class="v">{v}</span>'
            f'<span class="b" style="height:{round(v/top*100)}%;background:{colors[i]}"></span>'
            f'<span class="l">{k}</span></div>' for i, (k, v) in enumerate(pairs))
        css = (f"#c{{font-family:{font};padding:18px 20px;display:flex;flex-direction:column;}}"
               f"h3{{margin:0 0 6px;font-size:{rng.choice([17, 19, 21])}px;color:#111827;}}"
               f".u{{font-size:12px;color:#6b7280;margin-bottom:12px;}}"
               f".plot{{flex:1;display:flex;align-items:flex-end;gap:{rng.choice([14, 20, 26])}px;"
               f"border-bottom:2px solid #111827;padding:0 6px;}}"
               f".col{{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;"
               f"align-items:center;}}"
               f".b{{width:100%;border-radius:{rng.choice([0, 3, 6])}px {rng.choice([0, 3, 6])}px 0 0;}}"
               f".v{{font-size:12px;font-weight:700;color:#111827;margin-bottom:4px;}}"
               f".l{{font-size:12px;color:#374151;position:absolute;}}"
               f".col .l{{position:static;margin-top:6px;}}")
        body = f'<h3>{title}</h3><div class="u">{unit}</div><div class="plot">{bars}</div>'
        return dict(w=w, h=h, bg="#ffffff", css=css, body=body), "Bar chart"

    for title, pairs, unit in data[:10]:
        spec, kind = bar_chart(title, pairs, unit)
        items.append(complex_item(title, kind, pairs, unit, spec))
    for title, pairs, unit in data[3:9]:
        spec, kind = bar_chart(title, pairs, unit, horizontal=True)
        items.append(complex_item(title, kind, pairs, unit, spec))

    # line charts
    for title, pairs, unit in data[:6]:
        w = rng.choice([420, 480, 520])
        h = rng.choice([260, 300])
        accent = rng.choice(ACCENTS)
        font = rng.choice(SANS)
        pad_l, pad_r, pad_t, pad_b = 46, 22, 54, 40
        top = max(v for _, v in pairs) * 1.2
        n = len(pairs)
        pts = []
        for i, (_, v) in enumerate(pairs):
            x = pad_l + (w - pad_l - pad_r) * (i / max(1, n - 1))
            y = h - pad_b - (h - pad_t - pad_b) * (v / top)
            pts.append((x, y))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{accent}"/>'
                       f'<text x="{x:.1f}" y="{y-11:.1f}" text-anchor="middle" font-size="12" '
                       f'font-weight="700" fill="#111827">{v}</text>'
                       for (x, y), (_, v) in zip(pts, pairs))
        xlab = "".join(f'<text x="{x:.1f}" y="{h-pad_b+18}" text-anchor="middle" font-size="12" '
                       f'fill="#374151">{k}</text>' for (x, _), (k, _) in zip(pts, pairs))
        grid = "".join(f'<line x1="{pad_l}" y1="{y}" x2="{w-pad_r}" y2="{y}" stroke="#e5e7eb"/>'
                       for y in range(pad_t, h - pad_b, 34))
        body = (f'<svg width="{w}" height="{h}" font-family="{font}">'
                f'<text x="20" y="28" font-size="17" font-weight="700" fill="#111827">{title}</text>'
                f'<text x="20" y="46" font-size="12" fill="#6b7280">{unit}</text>{grid}'
                f'<line x1="{pad_l}" y1="{h-pad_b}" x2="{w-pad_r}" y2="{h-pad_b}" stroke="#111827" '
                f'stroke-width="2"/>'
                f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{h-pad_b}" stroke="#111827" '
                f'stroke-width="2"/>'
                f'<polyline points="{poly}" fill="none" stroke="{accent}" stroke-width="3" '
                f'stroke-linejoin="round"/>{dots}{xlab}</svg>')
        spec = dict(w=w, h=h, bg="#ffffff", css="#c{display:block;}", body=body)
        items.append(complex_item(title, "Line chart", pairs, unit, spec))

    # pie charts, values normalised to percentages
    for title, pairs, unit in data[6:14]:
        total = sum(v for _, v in pairs)
        pct = [round(v / total * 100) for _, v in pairs]
        drift = 100 - sum(pct)
        pct[0] += drift
        shown = list(zip([k for k, _ in pairs], pct))
        colors = rng.sample(ACCENTS, len(shown))
        stops = []
        acc = 0
        for (k, p), col in zip(shown, colors):
            stops.append(f"{col} {acc}% {acc + p}%")
            acc += p
        size = rng.choice([160, 190, 220])
        font = rng.choice(SANS)
        legend = "".join(f'<li><span style="background:{col}"></span>{k} {p}%</li>'
                         for (k, p), col in zip(shown, colors))
        w = size + 200
        h = max(size + 80, 90 + len(shown) * 26)
        css = (f"#c{{font-family:{font};padding:18px;}}"
               f"h3{{margin:0 0 12px;font-size:17px;color:#111827;}}"
               f".row{{display:flex;align-items:center;gap:20px;}}"
               f".pie{{width:{size}px;height:{size}px;border-radius:50%;background:conic-gradient("
               f"{','.join(stops)});}}"
               f"ul{{list-style:none;margin:0;padding:0;font-size:13px;color:#374151;}}"
               f"li{{display:flex;align-items:center;gap:8px;margin-bottom:8px;}}"
               f"li span{{width:12px;height:12px;border-radius:2px;display:inline-block;}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css,
                    body=f'<h3>{title}</h3><div class="row"><div class="pie"></div><ul>{legend}</ul>'
                         f'</div>')
        items.append(complex_item(title, "Pie chart", shown, "percent", spec))

    # stacked bars
    for title, pairs, unit in data[9:15]:
        font = rng.choice(SANS)
        segs = ["Online", "In store", "Phone"]
        colors = rng.sample(ACCENTS, 3)
        w = rng.choice([420, 480])
        h = rng.choice([280, 320])
        top = max(v for _, v in pairs)
        plot_h = h - 150
        cols = ""
        for k, v in pairs:
            a = round(v * 0.5)
            b = round(v * 0.3)
            c = v - a - b
            bar_h = round(v / top * plot_h)
            seg_h = [round(part / v * bar_h) for part in (a, b, c)]
            seg_h[0] = bar_h - seg_h[1] - seg_h[2]
            parts = "".join(
                f'<span style="height:{ph}px;background:{col}"></span>'
                for ph, col in zip(seg_h, colors))
            cols += (f'<div class="col"><span class="v">{v}</span><div class="stack" '
                     f'style="height:{bar_h}px">{parts}</div><span class="l">{k}</span></div>')
        legend = "".join(f'<li><span style="background:{col}"></span>{s}</li>'
                         for s, col in zip(segs, colors))
        css = (f"#c{{font-family:{font};padding:18px;display:flex;flex-direction:column;}}"
               f"h3{{margin:0 0 10px;font-size:17px;color:#111827;}}"
               f".plot{{flex:1;display:flex;align-items:flex-end;gap:18px;border-bottom:2px solid "
               f"#111827;}}"
               f".col{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;"
               f"align-items:center;}}"
               f".stack{{width:100%;display:flex;flex-direction:column;}}"
               f".stack span{{width:100%;display:block;}}"
               f".v{{font-size:12px;font-weight:700;margin-bottom:4px;}}"
               f".l{{font-size:12px;color:#374151;margin-top:6px;}}"
               f"ul{{list-style:none;display:flex;gap:16px;padding:0;margin:12px 0 0;font-size:12px;"
               f"color:#374151;}}"
               f"li{{display:flex;align-items:center;gap:6px;}}"
               f"li span{{width:10px;height:10px;display:inline-block;border-radius:2px;}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css,
                    body=f'<h3>{title}</h3><div class="plot">{cols}</div><ul>{legend}</ul>')
        items.append(complex_item(title, "Stacked bar chart", pairs, unit, spec))

    # data tables
    for title, pairs, unit in data[2:8]:
        font = rng.choice(SANS + SERIF)
        accent = rng.choice(ACCENTS)
        rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)
        w = rng.choice([320, 380, 420])
        h = 110 + len(pairs) * 34
        css = (f"#c{{font-family:{font};padding:18px;}}"
               f"h3{{margin:0 0 12px;font-size:16px;color:#111827;}}"
               f"table{{border-collapse:collapse;width:100%;font-size:14px;}}"
               f"th{{background:{accent};color:#fff;text-align:left;padding:8px 10px;}}"
               f"td{{border-bottom:1px solid #e5e7eb;padding:8px 10px;color:#1f2937;}}"
               f"tr:nth-child(even) td{{background:{tint(accent, 0.06)};}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css,
                    body=f'<h3>{title}</h3><table><tr><th>Name</th><th>{unit.capitalize()}</th></tr>'
                         f'{rows}</table>')
        items.append(complex_item(title, "Table", pairs, unit, spec))

    # flow diagrams
    flows = [
        ("How a return works", ["Request", "Print label", "Post it", "Refund"]),
        ("Article workflow", ["Draft", "Review", "Edit", "Publish"]),
        ("Support escalation", ["Ticket", "Triage", "Specialist"]),
        ("Order pipeline", ["Placed", "Picked", "Packed", "Shipped"]),
        ("Account setup", ["Sign up", "Verify email", "Add details"]),
        ("Repair intake", ["Book slot", "Assess", "Quote", "Fix"]),
    ]
    for title, steps in flows:
        font = rng.choice(SANS)
        accent = rng.choice(ACCENTS)
        boxw = rng.choice([98, 112, 124])
        gap = 34
        w = 40 + len(steps) * boxw + (len(steps) - 1) * gap
        h = rng.choice([150, 170])
        boxes = ""
        for i, s in enumerate(steps):
            boxes += (f'<div class="box">{s}</div>')
            if i < len(steps) - 1:
                boxes += '<div class="arrow"></div>'
        css = (f"#c{{font-family:{font};padding:16px;display:flex;flex-direction:column;}}"
               f"h3{{margin:0 0 14px;font-size:16px;color:#111827;}}"
               f".flow{{flex:1;display:flex;align-items:center;}}"
               f".box{{width:{boxw}px;padding:12px 6px;text-align:center;border:2px solid {accent};"
               f"border-radius:{rng.choice([4, 8, 999])}px;font-size:13px;color:#111827;"
               f"background:{tint(accent, 0.08)};}}"
               f".arrow{{width:{gap}px;height:2px;background:{accent};position:relative;}}"
               f".arrow:after{{content:'';position:absolute;right:0;top:-4px;border-left:9px solid "
               f"{accent};border-top:5px solid transparent;border-bottom:5px solid transparent;}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css,
                    body=f'<h3>{title}</h3><div class="flow">{boxes}</div>')
        pairs = [(f"step {i+1}", s) for i, s in enumerate(steps)]
        expected = f"Flow diagram titled {title}. " + " then ".join(steps) + "."
        must = keywords(title, 2) + [s.lower() for s in steps]
        tag, html, nearby = chart_context(title)
        items.append(make("complex", spec, expected, must, [], tag, html, nearby,
                          f"flow diagram, {len(steps)} steps"))

    # org charts
    orgs = [
        ("Store team", "Manager", ["Bakery", "Deli", "Checkout"]),
        ("Studio structure", "Director", ["Design", "Build", "Accounts"]),
        ("Library staff", "Head librarian", ["Lending", "Archives", "Events"]),
        ("Kitchen roles", "Head chef", ["Pastry", "Grill", "Prep"]),
        ("Support desk", "Team lead", ["Tier 1", "Tier 2"]),
    ]
    for title, root, children in orgs:
        font = rng.choice(SANS)
        accent = rng.choice(ACCENTS)
        boxw = 110
        gap = 26
        w = 40 + len(children) * boxw + (len(children) - 1) * gap
        h = 220
        kids = "".join(f'<div class="node">{c}</div>' for c in children)
        css = (f"#c{{font-family:{font};padding:16px;text-align:center;}}"
               f"h3{{margin:0 0 14px;font-size:16px;color:#111827;}}"
               f".root{{display:inline-block;padding:10px 18px;border-radius:6px;background:{accent};"
               f"color:#fff;font-size:13px;font-weight:600;}}"
               f".stem{{width:2px;height:22px;background:{accent};margin:0 auto;}}"
               f".bar{{height:2px;background:{accent};margin:0 {boxw//2}px;}}"
               f".kids{{display:flex;justify-content:center;gap:{gap}px;margin-top:0;}}"
               f".node{{width:{boxw}px;margin-top:22px;padding:10px 6px;border:2px solid {accent};"
               f"border-radius:6px;font-size:13px;color:#111827;position:relative;}}"
               f".node:before{{content:'';position:absolute;top:-22px;left:50%;width:2px;height:22px;"
               f"background:{accent};}}")
        spec = dict(w=w, h=h, bg="#ffffff", css=css,
                    body=f'<h3>{title}</h3><div class="root">{root}</div><div class="stem"></div>'
                         f'<div class="bar"></div><div class="kids">{kids}</div>')
        expected = (f"Organisation chart titled {title}. {root} above "
                    + ", ".join(children) + ".")
        must = keywords(title, 2) + [root.split()[0].lower()] + [c.split()[0].lower() for c in children]
        tag, html, nearby = chart_context(title)
        items.append(make("complex", spec, expected, must, [], tag, html, nearby,
                          f"org chart, {len(children)} reports"))

    # timelines
    timelines = [
        ("Company milestones", [("2016", "First shop"), ("2019", "Online store"),
                                ("2022", "Second shop"), ("2025", "Repair service")]),
        ("Project phases", [("2023", "Research"), ("2024", "Pilot"), ("2026", "Rollout")]),
        ("Building history", [("1904", "Built"), ("1962", "Extended"), ("2011", "Restored")]),
        ("Release history", [("2021", "Beta"), ("2022", "Version 1"), ("2024", "Version 2"),
                             ("2026", "Version 3")]),
        ("Grant timeline", [("2022", "Applied"), ("2023", "Awarded"), ("2025", "Reported")]),
    ]
    for title, points in timelines:
        font = rng.choice(SANS)
        accent = rng.choice(ACCENTS)
        w = rng.choice([440, 500, 560])
        h = 190
        n = len(points)
        marks = ""
        for i, (year, label) in enumerate(points):
            x = 60 + (w - 120) * (i / max(1, n - 1))
            marks += (f'<circle cx="{x:.0f}" cy="110" r="8" fill="{accent}"/>'
                      f'<text x="{x:.0f}" y="86" text-anchor="middle" font-size="14" '
                      f'font-weight="700" fill="#111827">{year}</text>'
                      f'<text x="{x:.0f}" y="140" text-anchor="middle" font-size="12" '
                      f'fill="#374151">{label}</text>')
        body = (f'<svg width="{w}" height="{h}" font-family="{font}">'
                f'<text x="24" y="36" font-size="17" font-weight="700" fill="#111827">{title}</text>'
                f'<line x1="50" y1="110" x2="{w-50}" y2="110" stroke="{accent}" stroke-width="3"/>'
                f'{marks}</svg>')
        spec = dict(w=w, h=h, bg="#ffffff", css="#c{display:block;}", body=body)
        expected = (f"Timeline titled {title}. "
                    + ", ".join(f"{y} {lab}" for y, lab in points) + ".")
        must = keywords(title, 2) + [y for y, _ in points]
        tag, html, nearby = chart_context(title)
        items.append(make("complex", spec, expected, must, [], tag, html, nearby,
                          f"timeline, {n} points"))
    return items


# ---------------------------------------------------------------- assembly

def validate(item):
    expected = item["expected_alt"].lower()
    for word in item["must_not_include"]:
        if word in expected:
            raise ValueError(f"{item['id']}: forbidden word {word!r} appears in expected_alt")
    if item["category"] == "decorative":
        if item["expected_alt"] != "" or item["must_include"]:
            raise ValueError(f"{item['id']}: decorative item must have empty alt and no keywords")
    else:
        if not item["expected_alt"]:
            raise ValueError(f"{item['id']}: empty expected_alt outside the decorative category")
    if item["category"] in ("informative", "image_of_text", "complex"):
        for word in item["must_include"]:
            if word not in expected:
                raise ValueError(f"{item['id']}: keyword {word!r} missing from expected_alt")


def build():
    started = time.time()
    generators = {
        "functional": gen_functional,
        "informative": gen_informative,
        "decorative": gen_decorative,
        "image_of_text": gen_image_of_text,
        "complex": gen_complex,
    }
    items = []
    for cat in CATEGORIES:
        made = generators[cat]()
        for i, item in enumerate(made, start=1):
            item["id"] = f"{cat}_{i:04d}"
            item["file"] = f"images/{item['id']}.png"
            item["context"]["html"] = item["context"]["html"].replace("{src}", item["file"])
            item["spec"]["w"] = max(64, int(item["spec"]["w"]))
            item["spec"]["h"] = max(64, int(item["spec"]["h"]))
            validate(item)
        items.extend(made)
    return items, started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--resume", action="store_true",
                        help="keep images that already exist and render only what is missing")
    args = parser.parse_args()

    items, started = build()

    if not args.resume and IMAGES.exists():
        shutil.rmtree(IMAGES)
    IMAGES.mkdir(parents=True, exist_ok=True)
    (IMAGES / ".gitkeep").write_text("")

    workdir = Path(tempfile.mkdtemp(prefix="altbench_"))
    lock = threading.Lock()
    free = list(range(args.workers))
    done = [0]

    def worker(item):
        with lock:
            slot = free.pop()
        try:
            out = IMAGES / f"{item['id']}.png"
            if not (args.resume and out.exists() and out.stat().st_size > 0):
                shoot(item["spec"], out, workdir, slot)
            width, height = png_size(out)
            longest = max(width, height)
            if not 64 <= longest <= 1200:
                raise ValueError(f"{item['id']}: long side {longest} out of range")
            item["width"] = width
            item["height"] = height
        finally:
            with lock:
                free.append(slot)
                done[0] += 1
                if done[0] % 25 == 0:
                    print(f"  rendered {done[0]}/{len(items)}", flush=True)

    print(f"rendering {len(items)} images with {args.workers} workers")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(worker, items))
    shutil.rmtree(workdir, ignore_errors=True)

    manifest_items = []
    for item in items:
        manifest_items.append({
            "id": item["id"],
            "file": item["file"],
            "category": item["category"],
            "expected_alt": item["expected_alt"],
            "must_include": item["must_include"],
            "must_not_include": item["must_not_include"],
            "context": item["context"],
            "notes": f"{item['notes']}; rendered {item['width']}x{item['height']} px, seed {SEED}",
        })

    MANIFEST.write_text(json.dumps({"version": 1, "items": manifest_items}, indent=2) + "\n",
                        encoding="utf-8")

    counts = {}
    for item in manifest_items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    elapsed = time.time() - started
    print(f"wrote {MANIFEST} with {len(manifest_items)} items in {elapsed:.1f}s")
    for cat in CATEGORIES:
        print(f"  {cat:<14} {counts.get(cat, 0)}")


if __name__ == "__main__":
    main()
