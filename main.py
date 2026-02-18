import asyncio
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

app = FastAPI(title="ProxyForge")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FLIP_LAYOUTS = {"transform", "modal_dfc", "flip", "reversible_card", "battle", "meld"}
SCRYFALL_HEADERS = {"User-Agent": "ProxyForge/2.0", "Accept": "application/json"}

# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def normalise(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())

def parse_deck_list(text):
    cards = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        line = re.sub(r'\s*\[[^\]]*\]\s*$', '', line).strip()
        if not line:
            continue
        qty, rest = 1, line
        m = re.match(r'^(\d+)[xX]?\s+(.+)', line)
        if m:
            qty, rest = int(m.group(1)), m.group(2).strip()
        set_code = set_num = None
        name = rest
        m2 = re.match(r'^(.+?)\s+\(([a-zA-Z0-9]+)\)\s+([a-zA-Z0-9-]+)\s*$', rest)
        if m2:
            name, set_code, set_num = m2.group(1).strip(), m2.group(2).lower(), m2.group(3)
        if ' // ' in name:
            name = name.split(' // ')[0].strip()
        cards.append({"qty": qty, "name": name, "set_code": set_code, "set_num": set_num})
    return cards

def scryfall_get(set_code, set_num, name):
    try:
        if set_code and set_num:
            url = f"https://api.scryfall.com/cards/{set_code}/{set_num}"
            try:
                req = urllib.request.Request(url, headers=SCRYFALL_HEADERS)
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())
            except Exception:
                pass
        enc = urllib.parse.quote(name)
        req = urllib.request.Request(f"https://api.scryfall.com/cards/named?fuzzy={enc}", headers=SCRYFALL_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None

def best_image_url(obj):
    uris = obj.get("image_uris", {}) if obj else {}
    for size in ("png", "large", "normal", "small"):
        if uris.get(size):
            return uris[size]
    return None

def download_bytes(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ProxyForge/2.0", "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except Exception:
        return None

# ── Card fetch pipeline ────────────────────────────────────────────────────────

async def fetch_all_cards(deck_list):
    cards = parse_deck_list(deck_list)
    if not cards:
        raise HTTPException(400, "Could not parse any cards.")

    expanded = []
    for c in cards:
        for n in range(1, c["qty"] + 1):
            suffix = f" ({n})" if c["qty"] > 1 else ""
            expanded.append({**c, "suffix": suffix})

    front_list, back_list, report, cache = [], [], [], {}

    for entry in expanded:
        name, key, suffix = entry["name"], normalise(entry["name"]), entry["suffix"]

        if key in cache:
            cached = cache[key]
            if cached is None:
                report.append({"name": name, "suffix": suffix, "status": "error", "flip": False, "reason": "Lookup failed"})
                front_list.append(None); back_list.append(None)
                continue
            front_list.append(cached["front"]); back_list.append(cached.get("back"))
            report.append({"name": name, "suffix": suffix, "status": "copied", "flip": cached.get("flip", False)})
            continue

        data = scryfall_get(entry.get("set_code"), entry.get("set_num"), name)
        if not data:
            cache[key] = None
            report.append({"name": name, "suffix": suffix, "status": "error", "flip": False, "reason": "Scryfall lookup failed"})
            front_list.append(None); back_list.append(None)
            continue

        is_flip = data.get("layout", "normal") in FLIP_LAYOUTS
        faces   = data.get("card_faces", [])

        if is_flip:
            front_url = best_image_url(faces[0] if faces else None) or best_image_url(data)
            back_url  = best_image_url(faces[1]) if len(faces) > 1 else None
        else:
            front_url, back_url = best_image_url(data), None

        if not front_url:
            cache[key] = None
            report.append({"name": name, "suffix": suffix, "status": "error", "flip": False, "reason": "No image URL"})
            front_list.append(None); back_list.append(None)
            continue

        front_b = download_bytes(front_url)
        if not front_b:
            cache[key] = None
            report.append({"name": name, "suffix": suffix, "status": "error", "flip": False, "reason": "Download failed"})
            front_list.append(None); back_list.append(None)
            continue

        back_b = download_bytes(back_url) if back_url else None
        cache[key] = {"front": front_b, "back": back_b, "flip": is_flip}
        front_list.append(front_b); back_list.append(back_b)
        report.append({"name": name, "suffix": suffix, "status": "flip" if is_flip else "ok", "flip": is_flip})
        await asyncio.sleep(0.08)

    ok     = sum(1 for r in report if r["status"] in ("ok", "flip", "copied"))
    summary = {
        "total":  len(expanded),
        "ok":     ok,
        "flips":  sum(1 for r in report if r.get("flip")),
        "copied": sum(1 for r in report if r["status"] == "copied"),
        "errors": sum(1 for r in report if r["status"] == "error"),
    }
    return front_list, back_list, report, summary

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8"))


@app.post("/api/download")
async def api_download(deck_list: str = Form(...)):
    front_list, back_list, report, summary = await fetch_all_cards(deck_list)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for i, r in enumerate(report):
            fb = front_list[i]
            if fb is None:
                continue
            safe, suffix = safe_filename(r["name"]), r["suffix"]
            zout.writestr(f"fronts/{safe}{suffix}.jpg", fb)
            bb = back_list[i]
            if bb:
                zout.writestr(f"backs/{safe}{suffix}.jpg", bb)
        zout.writestr("_report.json", json.dumps(report, indent=2))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={
        "Content-Disposition": "attachment; filename=proxies.zip",
        "X-Summary": json.dumps(summary), "X-Report": json.dumps(report),
        "Access-Control-Expose-Headers": "X-Summary, X-Report",
    })


@app.post("/api/pdf")
async def api_pdf(
    deck_list:      str        = Form(...),
    generic_back:   UploadFile = File(None),
    extend_corners: int        = Form(10),
):
    from pdf_gen import build_pdf

    generic_back_bytes = None
    if generic_back and generic_back.filename:
        generic_back_bytes = await generic_back.read()

    front_list, back_list, report, summary = await fetch_all_cards(deck_list)

    fronts, backs = [], []
    for fb, bb in zip(front_list, back_list):
        if fb is not None:
            fronts.append(fb)
            backs.append(bb)

    if not fronts:
        raise HTTPException(400, "No cards were successfully downloaded.")

    pdf_bytes = build_pdf(
        front_images=fronts,
        back_images=backs,
        generic_back=generic_back_bytes,
        extend_corners=extend_corners,
    )

    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={
        "Content-Disposition": f"attachment; filename=proxies_{summary['ok']}cards.pdf",
        "X-Summary": json.dumps(summary), "X-Report": json.dumps(report),
        "Access-Control-Expose-Headers": "X-Summary, X-Report",
    })
