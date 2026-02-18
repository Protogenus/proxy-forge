"""
pdf_gen.py - ProxyForge PDF Generator
Produces a Silhouette Cameo print-and-cut compatible PDF matching the
structure used by Alan-Cha/silhouette-card-maker:

  - Page orientation: LANDSCAPE (11 x 8.5 in) at 300 PPI → 3300 x 2550 px
  - Standard MTG card size: 63 x 88 mm → 744 x 1039 px at 300 PPI
  - 4x4 grid = 16 cards per page
  - Silhouette Type-1 registration marks drawn in pixel space:
      top-left filled square, top-right L, bottom-left L
  - extend_corners: expands each card image by N px on all sides before
    placing, bleeding past the slot boundary to fix rounded-corner artifacts
  - Alternating front/back pages; backs mirrored horizontally to align
    when the sheet is physically flipped on the short axis
  - PDF produced via Pillow → img2pdf pipeline (300 PPI, correct page size)
"""

from io import BytesIO
from PIL import Image, ImageDraw
import img2pdf

# ── Resolution ───────────────────────────────────────────────────────────────
PPI = 300

# ── Page dimensions — landscape letter at 300 PPI ────────────────────────────
# 11 × 8.5 inches → 3300 × 2550 px
PAGE_W_PX = 3300
PAGE_H_PX = 2550

# ── Card dimensions at 300 PPI ───────────────────────────────────────────────
# 63 mm × 88 mm → (63/25.4)*300 ≈ 744 px  ×  (88/25.4)*300 ≈ 1039 px
CARD_W_PX = 744
CARD_H_PX = 1039

COLS = 4
ROWS = 2
CARDS_PER_PAGE = COLS * ROWS

# ── Registration mark geometry (pixel units at 300 PPI) ──────────────────────
# ── Registration mark geometry (pixel units matching Official PDF v2) ────────
REG_INSET_PX = 112
REG_SIZE_PX  = 188
REG_THICK_PX = 12
REG_GAP_PX   = 0     # Gap seems negligible or handled by grid placement

# ── Card grid (coordinates matching Official PDF v2) ────────────────────────
GRID_X = 150
GRID_Y = 224

# 754px width discovered in Official PDF (likely 744px + bleed)
# 1076px height discovered (likely 1039px + bleed)
CARD_GAP_X = 754  
CARD_GAP_Y = 1076


# ─────────────────────────────────────────────────────────────────────────────
def _new_page() -> Image.Image:
    """Return a blank white landscape letter page at 300 PPI."""
    return Image.new("RGB", (PAGE_W_PX, PAGE_H_PX), (255, 255, 255))


def _draw_reg_marks(page: Image.Image) -> None:
    """
    Draw Silhouette Type-1 3-point registration marks onto the page.
      - Top-left:    filled black square
      - Top-right:   L-shape (open toward bottom-right)
      - Bottom-left: L-shape (open toward top-right)
    """
    draw = ImageDraw.Draw(page)
    i = REG_INSET_PX
    s = REG_SIZE_PX
    t = REG_THICK_PX
    W, H = PAGE_W_PX, PAGE_H_PX

    # Top-left: filled square
    draw.rectangle([i, i, i + s, i + s], fill=(0, 0, 0))

    # Top-right: L (top bar + left vertical)
    tr_x, tr_y = W - i - s, i
    draw.rectangle([tr_x, tr_y, tr_x + s, tr_y + t], fill=(0, 0, 0))  # horizontal
    draw.rectangle([tr_x + s - t, tr_y, tr_x + s, tr_y + s], fill=(0, 0, 0))  # vertical

    # Bottom-left: L (bottom bar + right vertical)
    bl_x, bl_y = i, H - i - s
    draw.rectangle([bl_x, bl_y + s - t, bl_x + s, bl_y + s], fill=(0, 0, 0))  # horizontal
    draw.rectangle([bl_x, bl_y, bl_x + t, bl_y + s], fill=(0, 0, 0))          # vertical


def _card_top_left(index: int) -> tuple[int, int]:
    """
    Return the (x, y) top-left pixel corner of card slot [index].
    Index 0 = top-left, using Official PDF spacing.
    """
    col = index % COLS
    row = index // COLS
    x = GRID_X + col * CARD_GAP_X
    y = GRID_Y + row * CARD_GAP_Y
    return x, y


def _place_card(page: Image.Image, img_bytes: bytes,
                x: int, y: int, extend_corners: int = 0) -> None:
    """
    Decode card image bytes and paste onto the page at (x, y).

    If extend_corners > 0, the image is resized to fill an expanded bounding
    box (card slot + ec px on each side) and pasted offset by -ec so it bleeds
    slightly outside its slot boundary, eliminating the white-corner artifact
    from rounded card art.
    """
    try:
        card = Image.open(BytesIO(img_bytes)).convert("RGB")
    except Exception:
        placeholder = Image.new("RGB", (CARD_W_PX, CARD_H_PX), (38, 38, 51))
        page.paste(placeholder, (x, y))
        return

    if extend_corners > 0:
        ec = extend_corners
        expanded_w = CARD_W_PX + ec * 2
        expanded_h = CARD_H_PX + ec * 2
        card = card.resize((expanded_w, expanded_h), Image.LANCZOS)
        paste_x = x - ec
        paste_y = y - ec
    else:
        card = card.resize((CARD_W_PX, CARD_H_PX), Image.LANCZOS)
        paste_x, paste_y = x, y

    page.paste(card, (paste_x, paste_y))


def _add_label(page: Image.Image, text: str) -> None:
    """Stamp a small grey label centered in the bottom margin."""
    draw = ImageDraw.Draw(page)
    w = draw.textlength(text)
    x = (PAGE_W_PX - w) // 2
    y = PAGE_H_PX - REG_INSET_PX + (REG_INSET_PX // 2)
    draw.text((x, y), text, fill=(160, 160, 160))


def _page_to_jpeg(page: Image.Image, quality: int = 90) -> bytes:
    """Encode a PIL Image as JPEG bytes for img2pdf."""
    buf = BytesIO()
    page.save(buf, format="JPEG", quality=quality, dpi=(PPI, PPI))
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
def build_pdf(
    front_images:   list[bytes],
    back_images:    list[bytes | None],
    generic_back:   bytes | None = None,
    extend_corners: int = 10,
    quality:        int = 90,
    paper_size:     str = "letter",   # reserved for future multi-size support
) -> bytes:
    """
    Build a Silhouette-ready print-and-cut PDF.

    Pages alternate: front sheet → back sheet → front sheet → back sheet …

    Front page : cards in normal reading order (left→right, top→bottom).
    Back page  : cards mirrored horizontally so they align when the sheet is
                 physically flipped on its short axis.

    Parameters
    ----------
    front_images    : Ordered list of raw front image bytes, one per card.
    back_images     : Matching list of back image bytes; use None for slots
                      that should fall back to generic_back.
    generic_back    : Fallback back image for any None entry in back_images.
    extend_corners  : Pixels to bleed each card image past its slot edges.
                      Recommended value: 10.
    quality         : JPEG compression quality (0–100). Higher = larger file.
    paper_size      : Reserved. Currently only "letter" (landscape) supported.

    Returns
    -------
    PDF as bytes.
    """
    total     = len(front_images)
    num_pages = (total + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE

    jpeg_pages: list[bytes] = []

    for page_num in range(num_pages):
        start = page_num * CARDS_PER_PAGE
        end   = min(start + CARDS_PER_PAGE, total)
        slots = end - start

        # ── Front page ───────────────────────────────────────────────────────
        front_pg = _new_page()
        _draw_reg_marks(front_pg)

        for i in range(slots):
            x, y = _card_top_left(i)
            _place_card(front_pg, front_images[start + i], x, y, extend_corners)

        _add_label(front_pg,
                   f"ProxyForge | Page {page_num + 1} front | "
                   "Print at 100% scale, no fit-to-page")
        jpeg_pages.append(_page_to_jpeg(front_pg, quality))

        # ── Back page ────────────────────────────────────────────────────────
        back_pg = _new_page()
        _draw_reg_marks(back_pg)

        for i in range(slots):
            # Mirror column so backs align after the sheet is flipped
            col          = i % COLS
            row          = i // COLS
            mirrored_col = COLS - 1 - col
            mirrored_i   = row * COLS + mirrored_col

            back_bytes = (
                back_images[start + i]
                if back_images and back_images[start + i] is not None
                else generic_back
            )

            if back_bytes:
                x, y = _card_top_left(mirrored_i)
                _place_card(back_pg, back_bytes, x, y, extend_corners)

        _add_label(back_pg,
                   f"ProxyForge | Page {page_num + 1} back  | "
                   "Print at 100% scale, no fit-to-page")
        jpeg_pages.append(_page_to_jpeg(back_pg, quality))

    # ── Pack JPEG pages into a PDF via img2pdf (no re-encoding) ──────────────
    layout = img2pdf.get_layout_fun(
        (img2pdf.in_to_pt(11), img2pdf.in_to_pt(8.5))  # landscape letter
    )
    return img2pdf.convert(jpeg_pages, layout_fun=layout)
