"""A decision PDF as one image, for the screen: every page rendered, the blank bottom of
each page cut off, and the pages stacked with a thin line between them.

A browser's own PDF viewer would leave a tall empty box under a one-page document
(03-ui-ux-design.md, section 3); an image is exactly as tall as the document.
The images are made the first time they are asked for and kept in .cache/pages/, which,
like the PDFs, stays on this machine.
"""

import os
import threading
from pathlib import Path

from PIL import Image, ImageChops

from .. import config
from ..fetch import pdf_path

PAGES_DIR = config.CACHE_DIR / "pages"
SCALE = 2  # pixels per PDF point: sharp on a high-resolution screen
MARGIN = 70  # white kept under the last line of each page, at that scale
DIVIDER = (195, 194, 183)  # the --rule colour of the screen


def trim(page: Image.Image, first: bool) -> Image.Image | None:
    """Cut the white below the last mark of a page (and above the first, after page one).

    None for a blank page. "White" allows for the faint grey of anti-aliasing.
    """
    ink = ImageChops.difference(page, Image.new("RGB", page.size, (255, 255, 255))).convert("L")
    box = ink.point(lambda v: 255 if v > 18 else 0).getbbox()
    if box is None:
        return None
    top = 0 if first else max(0, box[1] - MARGIN)
    return page.crop((0, top, page.width, min(page.height, box[3] + MARGIN)))


def stack(pages: list[Image.Image]) -> Image.Image:
    parts = [p for p in (trim(page, i == 0) for i, page in enumerate(pages)) if p is not None]
    if not parts:  # every page blank: show the first one as it is rather than nothing
        parts = pages[:1]
    sheet = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts) + 2 * (len(parts) - 1)), "white")
    y = 0
    for i, part in enumerate(parts):
        if i:
            sheet.paste(DIVIDER, (0, y, sheet.width, y + 2))
            y += 2
        sheet.paste(part, (0, y))
        y += part.height
    return sheet


def page_image(record: dict, directory: Path = PAGES_DIR) -> Path | None:
    """The stacked image of a decision, made now if it is not there yet. None without the PDF."""
    out = directory / f"{record['id']}.png"
    if out.exists():
        return out
    source = pdf_path(record["event"], record["number"])
    if not source.exists():
        return None
    import pypdfium2  # imported here: only the screen needs it

    document = pypdfium2.PdfDocument(source)
    try:
        pages = [page.render(scale=SCALE).to_pil().convert("RGB") for page in document]
    finally:
        document.close()
    directory.mkdir(parents=True, exist_ok=True)
    # Written under another name and renamed in one step, so a second request that arrives
    # while this one is saving never reads half a file.
    partial = out.with_name(f"{out.stem}.{os.getpid()}.{threading.get_ident()}.part.png")
    stack(pages).save(partial, optimize=True)
    os.replace(partial, out)
    return out
