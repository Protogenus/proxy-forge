"""
pdf_gen.py - ProxyForge PDF Generator
Produces a standard print-ready PDF with:
  - Standard MTG card size: 63.5 x 88.9 mm (2.5 x 3.5 in)
  - Letter paper: 215.9 x 279.4 mm (8.5 x 11 in)
  - 4x2 grid = 8 cards per page
  - Simple corner registration marks
  - Alternating front/back pages for duplex printing
"""

from io import BytesIO
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm, inch
from reportlab.lib.pagesizes import letter

# ── Card & page constants ───────────────────────────────────────────────────
CARD_W      = 2.5 * inch     # Standard MTG card width
CARD_H      = 3.5 * inch     # Standard MTG card height
PAGE_W, PAGE_H = letter      # 215.9 x 279.4 mm (8.5 x 11 in)

COLS        = 4
ROWS        = 2
CARDS_PER_PAGE = COLS * ROWS

# Margins and registration marks
MARGIN      = 0.5 * inch    # margin from page edge
REG_SIZE    = 0.15 * inch   # small square registration mark size
REG_THICK   = 2              # line thickness in points

# Calculate grid positioning
GRID_W      = COLS * CARD_W
GRID_H      = ROWS * CARD_H
GRID_X      = (PAGE_W - GRID_W) / 2    # center horizontally
GRID_Y      = (PAGE_H - GRID_H) / 2    # center vertically


def _draw_reg_marks(c: canvas.Canvas):
    """Draw simple corner registration marks."""
    c.setLineWidth(REG_THICK)
    c.setStrokeColorRGB(0, 0, 0)
    
    s = REG_SIZE
    t = REG_THICK / 2
    
    # Top-left: small square
    c.rect(MARGIN - s/2, PAGE_H - MARGIN - s/2, s, s, fill=0, stroke=1)
    
    # Top-right: small square
    c.rect(PAGE_W - MARGIN - s/2, PAGE_H - MARGIN - s/2, s, s, fill=0, stroke=1)
    
    # Bottom-left: L-shape
    c.line(MARGIN - s/2, MARGIN - s/2, MARGIN + s/2, MARGIN - s/2)
    c.line(MARGIN - s/2, MARGIN - s/2, MARGIN - s/2, MARGIN + s/2)


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
                 w: float = CARD_W, h: float = CARD_H):
    """Draw a card image at (x,y)."""
    try:
        img = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception:
        # Draw placeholder if image is broken
        c.setFillColorRGB(0.85, 0.85, 0.85)
        c.rect(x, y, w, h, fill=1, stroke=0)
        return

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
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
) -> bytes:
    """
    Build a standard print-ready PDF.
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
            _place_image(c, front_images[start + i], x, y)

        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(MARGIN, MARGIN * 0.3,
                     f"sheet: {page+1}, template: letter_standard_v4")
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
                _place_image(c, back_bytes, x, y)

        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawString(MARGIN, MARGIN * 0.3,
                     f"sheet: {page+1}, template: letter_standard_v4")
        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
