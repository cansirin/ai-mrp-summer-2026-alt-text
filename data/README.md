# The image set

This folder holds the benchmark images and the manifest that says what each one means.
Nothing here was downloaded. Every image is drawn from an HTML, CSS and SVG template and
photographed with headless Chrome, so the correct alt text is decided before the pixels
exist and there is no question of who owns the picture.

## How the images are made

scripts/make_dataset.py holds one generator per category. A generator builds a small HTML
page whose only element is the thing being pictured, sized exactly to the window it will be
shot in. The page is written to a temporary file and rendered with:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=old \
      --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
      --screenshot=data/images/<id>.png --window-size=<w>,<h> file://<page>

Rendering happens at 1x, so the PNG is the natural size of the element. Colours, sizes,
fonts, corner radii, icon weights, page backgrounds and layouts are drawn from a fixed
random seed (20260906), which makes the set varied between items and identical between
runs. Running the script wipes data/images and rewrites data/manifest.json from scratch.

## Categories

The five categories come from the W3C alt decision tree,
https://www.w3.org/WAI/tutorials/images/decision-tree/. Counts are the number of images
in this build.

functional (65). The image is a control or a link, so the alt text is the action, not the
picture. Icon-only buttons and links (search, delete, close, menu, settings, cart, play,
download, share, edit, back, next, home, print, account, wishlist, favourites, filter,
upload, refresh, mail, phone, lock, calendar, chat, help, external link, add, bookmark,
pause, mute, notifications, zoom, copy, map), buttons that pair an icon with its label,
linked wordmarks in a page header where the right answer is the destination, and third
party sign in and pay buttons. expected_alt is the action, for example "Search" or
"Delete" or "Kestrel Books home". must_not_include lists the appearance words that mark a
describe-instead-of-act failure, such as magnifying, trash, gear, envelope, icon.

informative (60). The image carries meaning that the surrounding text does not repeat.
Weather glyphs, star ratings, progress rings, status badges, initials avatars, national
flags, simple product renderings in a named colour, maps with a marked route, and small
scenes composed from SVG shapes. expected_alt is the meaning, for example "Sunny" or
"4 out of 5 stars" or "A red mug", and must_include carries the concepts a correct answer
has to name.

decorative (59). The image adds nothing a reader would miss, so the correct alt text is
empty. Rules and dividers, flourishes and swashes, gradient blobs, corner ornaments, dot
and hatch patterns, wave and zigzag section separators, and stylistic bullets. Every one
sits somewhere plausible in the DOM, between two sections or beside a heading, with no
role attribute doing the work for the model. expected_alt is "" and must_include is empty.

image_of_text (56). The picture is text, so the alt text is that text. Wordmarks, promo
banners, quote cards, headings rendered as images, distorted character strings of the kind
a CAPTCHA uses, multi-line addresses, phone numbers, stylised announcements on gradients
and event cards. expected_alt is the exact visible text and must_include holds the key
words in lower case.

complex (58). The image carries data, so the alt text needs the title and the values.
Vertical and horizontal bar charts, line charts, pie charts with a legend, stacked bars,
data tables rendered as images, flow diagrams, organisation charts and timelines, each
with a title and three to six values. expected_alt is the title followed by the values,
and must_include holds the title words plus every value as a string.

Total: 298 images.

## The manifest

data/manifest.json is a list of items. Each item gives the id, the file, the
category, expected_alt, must_include, must_not_include, a context block and a notes
string recording how the image was drawn and at what size.

The context block is the treatment in the third experimental condition. It is a short
piece of DOM that shows where the image sits on a realistic page: the tag it lives in, an
HTML snippet naming the actual image file, and the text a sighted user would read next to
it. A search button sits inside a form next to the label "Search products". A cart icon
sits inside a link to /cart. A divider sits in a div between two sections. A chart sits in
a figure whose caption is the chart title. The context is written to be true to the item,
because the point of the condition is to test whether the information that carries
function, and that is not in the pixels, is enough to recover the right alt text.
