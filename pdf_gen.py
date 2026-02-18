"""
pdf_gen.py - ProxyForge PDF Generator
Produces a Silhouette Cameo print-and-cut compatible PDF with:
  - Standard MTG card size: 63 x 88 mm
  - Letter paper: 215.9 x 279.4 mm (8.5 x 11 in)
  - 3x3 grid = 9 cards per page
  - Silhouette Type-1 registration marks (3-point: top-left square, top-right L, bottom-left L)
  - 3mm bleed extension on card corners
  - Alternating front/back pages for duplex printing
"""

from io import BytesIO
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import letter

# ── Card & page constants ───────────────────────────────────────────────────
CARD_W      = 63 * mm       # 63 mm
CARD_H      = 88 * mm       # 88 mm
PAGE_W, PAGE_H = letter     # 215.9 x 279.4 mm in points

COLS        = 3
ROWS        = 3
CARDS_PER_PAGE = COLS * ROWS

# Registration mark geometry (Silhouette default Type-1 positions)
# Square mark: top-left corner
# L-marks: top-right and bottom-left corners
REG_INSET   = 6.35 * mm    # 0.25 inch inset from page edge (Silhouette default)
REG_SIZE    = 5    * mm    # mark arm length
REG_THICK   = 0.8  * mm    # line thickness
REG_GAP     = 1    * mm    # gap between mark end and printable area

# Printable area starts after reg marks + gap
PRINT_X     = REG_INSET + REG_SIZE + REG_GAP
PRINT_Y     = REG_INSET + REG_SIZE + REG_GAP
PRINT_W     = PAGE_W - PRINT_X - (REG_INSET + REG_SIZE + REG_GAP)
PRINT_H     = PAGE_H - PRINT_Y - (REG_INSET + REG_SIZE + REG_GAP)

# Card grid: centre the 3x3 grid in the printable area
GRID_W      = COLS * CARD_W
GRID_H      = ROWS * CARD_H
GRID_X      = PRINT_X + (PRINT_W - GRID_W) / 2   # left edge of grid
GRID_Y      = PRINT_Y + (PRINT_H - GRID_H) / 2   # bottom edge of grid


def _draw_reg_marks(c: canvas.Canvas):
    """Draw Silhouette Type-1 3-point registration marks."""
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(REG_THICK)

    s = REG_SIZE
    i = REG_INSET
    t = REG_THICK

    # ── Top-left: filled square ─────────────────────────────────────────────
    c.rect(i, PAGE_H - i - s, s, s, fill=1, stroke=0)

    # ── Top-right: L-shape (two rectangles) ────────────────────────────────
    tr_x = PAGE_W - i - s
    tr_y = PAGE_H - i - s
    c.rect(tr_x, tr_y + s - t, s, t, fill=1, stroke=0)      # horizontal
    c.rect(tr_x, tr_y, t, s, fill=1, stroke=0)               # vertical

    # ── Bottom-left: L-shape (two rectangles) ──────────────────────────────
    bl_x = i
    bl_y = i
    c.rect(bl_x, bl_y, s, t, fill=1, stroke=0)               # horizontal
    c.rect(bl_x, bl_y, t, s, fill=1, stroke=0)               # vertical


def _card_position(index: int) -> tuple[float, float]:
    """Return (x, y) bottom-left corner of card slot [index] in the grid.
    Index 0 = top-left, reading order left-to-right, top-to-bottom.
    ReportLab y=0 is bottom of page."""
    col = index % COLS
    row = index // COLS          # 0 = top row
    x = GRID_X + col * CARD_W
    # row 0 = top, so highest y value
    y = GRID_Y + (ROWS - 1 - row) * CARD_H
    return x, y


def _place_image(c: canvas.Canvas, img_bytes: bytes, x: float, y: float,
                 w: float = CARD_W, h: float = CARD_H, extend_corners: int = 0):
    """Draw a card image at (x,y) with optional corner bleed extension."""
    try:
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception:
        # Draw placeholder if image is broken
        c.setFillColorRGB(0.15, 0.15, 0.2)
        c.rect(x, y, w, h, fill=1, stroke=0)
        return

    if extend_corners > 0:
        # Expand image slightly to cover rounded-corner bleed gaps
        px = extend_corners
        new_w = img.width  + px * 2
        new_h = img.height + px * 2
        expanded = Image.new("RGB", (new_w, new_h), (0, 0, 0))
        expanded.paste(img, (px, px))
        img = expanded

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)

    c.drawImage(
        __import__('reportlab.lib.utils', fromlist=['ImageReader']).ImageReader(buf),
        x, y, width=w, height=h,
        preserveAspectRatio=False,
        mask='auto'
    )


def build_pdf(
    front_images: list[bytes],          # ordered list of front image bytes
    back_images:  list[bytes | None],   # matching backs (None = use generic_back)
    generic_back: bytes | None = None,  # single back used for all normal cards
    extend_corners: int = 10,
    paper_size: str = "letter",
) -> bytes:
    """
    Build a print-and-cut PDF.
    Pages alternate: front sheet, back sheet, front sheet, back sheet ...
    Front page: cards in normal reading order (left-right, top-bottom).
    Back page:  cards mirrored horizontally so they align when sheet is flipped.

    Returns PDF as bytes.
    """
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("ProxyForge Proxy Sheet")

    total = len(front_images)
    pages = (total + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE

    for page in range(pages):
        start = page * CARDS_PER_PAGE
        end   = min(start + CARDS_PER_PAGE, total)
        slots = end - start

        # ── Front page ──────────────────────────────────────────────────────
        _draw_reg_marks(c)
        for i in range(slots):
            x, y = _card_position(i)
            _place_image(c, front_images[start + i], x, y,
                         extend_corners=extend_corners)

        c.setFont("Helvetica", 6)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(REG_INSET, REG_INSET * 0.4,
                     f"ProxyForge | Page {page+1} front | Print at 100% scale, no fit-to-page")
        c.showPage()

        # ── Back page ───────────────────────────────────────────────────────
        _draw_reg_marks(c)
        for i in range(slots):
            # Mirror column so backs align when sheet is physically flipped
            col = i % COLS
            row = i // COLS
            mirrored_col = COLS - 1 - col
            mirrored_i   = row * COLS + mirrored_col

            back_bytes = back_images[start + i] if back_images else None
            if back_bytes is None:
                back_bytes = generic_back

            if back_bytes:
                x, y = _card_position(mirrored_i)
                _place_image(c, back_bytes, x, y, extend_corners=extend_corners)

        c.setFont("Helvetica", 6)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawString(REG_INSET, REG_INSET * 0.4,
                     f"ProxyForge | Page {page+1} back  | Print at 100% scale, no fit-to-page")
        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
