#!/usr/bin/env python3
"""Sincroniza las piezas del formulario de Google con la web.

Lee el CSV publicado de la hoja de respuestas (variable SHEET_CSV_URL),
descarga las fotos nuevas de Google Drive, las procesa con Pillow y
regenera por completo:

  - _data/piezas.json  (registro de datos, artefacto generado)
  - index.html         (tarjetas entre CLOP:PIEZAS-START/END y
                        JSON-LD entre CLOP:PIEZAS-LD-START/END)

La hoja de calculo es la unica fuente de verdad: todo lo generado se
reescribe entero en cada ejecucion. No editar a mano ni el JSON ni los
bloques marcados de index.html.

SHEET_CSV_URL puede ser una URL https o la ruta de un CSV local (pruebas
y migracion). Las celdas de foto aceptan o bien un enlace de Drive del
formulario o bien una ruta relativa del repositorio (p. ej. img/post-01.jpg),
que se usa tal cual sin descargar nada.
"""

import csv
import html
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "index.html"
JSON_PATH = ROOT / "_data" / "piezas.json"
IMG_DIR = ROOT / "img" / "piezas"

SITE_URL = "https://www.cloppatchwork.es/"

CARDS_START = "<!-- CLOP:PIEZAS-START -->"
CARDS_END = "<!-- CLOP:PIEZAS-END -->"
LD_START = "<!-- CLOP:PIEZAS-LD-START -->"
LD_END = "<!-- CLOP:PIEZAS-LD-END -->"

MAX_SIDE = 1600
JPEG_QUALITY = 82

# Estado -> (clase del chip, clave i18n del chip)
STATUS_MAP = {
    "pieza única": ("chip-ok", "chip-uni"),
    "pieza unica": ("chip-ok", "chip-uni"),
    "por encargo": ("chip-warn", "chip-ord"),
    "vendido": ("chip-last", "chip-sold"),
    "vendidos": ("chip-last", "chip-sold"),
}

TS_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def log(msg):
    print(msg, flush=True)


def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------- CSV

def fetch_csv(url):
    """Devuelve el texto CSV. Cualquier fallo es fatal: no se publica nada."""
    if not url.lower().startswith("http"):
        path = Path(url)
        if not path.is_file():
            die(f"CSV local no encontrado: {url}")
        return path.read_text(encoding="utf-8-sig")
    import requests
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        die(f"El CSV respondio {resp.status_code}")
    ctype = resp.headers.get("Content-Type", "")
    if "html" in ctype.lower():
        die("La URL del CSV devolvio HTML; revisa el enlace de 'Publicar en la web'")
    resp.encoding = "utf-8"
    return resp.text


def resolve_columns(fieldnames):
    """Mapea encabezados de la hoja (español, con posibles retoques) a claves."""
    norm = {h: (h or "").strip().lower() for h in fieldnames}

    def find(pred):
        for original, lowered in norm.items():
            if pred(lowered):
                return original
        return None

    cols = {
        "timestamp": find(lambda h: h.startswith("marca temporal") or h.startswith("timestamp")),
        "name": find(lambda h: h.startswith("nombre de la pieza")),
        "description": find(lambda h: h == "descripción" or h == "descripcion"),
        "photo": find(lambda h: h.startswith("foto")),
        "alt": find(lambda h: h.startswith("descripción de la foto") or h.startswith("descripcion de la foto")),
        "status": find(lambda h: h == "estado"),
        "price": find(lambda h: h.startswith("precio")),
        "instagram": find(lambda h: h.startswith("enlace")),
        "hide": find(lambda h: h == "ocultar"),
        "order": find(lambda h: h == "orden"),
        "name_en": find(lambda h: h in ("nombre en", "name en")),
        "description_en": find(lambda h: h in ("descripción en", "descripcion en")),
    }
    required = ["timestamp", "name", "description", "photo", "alt", "status"]
    missing = [k for k in required if cols[k] is None]
    if missing:
        die(f"Faltan columnas en el CSV: {missing}. Encabezados: {fieldnames}")
    return cols


def parse_timestamp(raw):
    raw = (raw or "").strip()
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------- datos

def slugify(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "pieza"


def normalize_price(raw):
    raw = (raw or "").replace("€", "").replace("EUR", "").strip()
    if not raw:
        return None
    if not re.fullmatch(r"\d{1,5}([.,]\d{1,2})?", raw):
        log(f"  aviso: precio no reconocido «{raw}», se omite")
        return None
    value = float(raw.replace(",", "."))
    return f"{value:.2f}".replace(".", ",") + " €"


def normalize_instagram(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if not re.match(r"https?://(www\.)?instagram\.com/", raw):
        log(f"  aviso: enlace no es de instagram.com «{raw}», se omite")
        return None
    return raw


def extract_drive_ids(cell):
    return re.findall(r"[-\w]{25,}", cell or "")


# ---------------------------------------------------------------- Drive

def download_drive_file(file_id):
    """Descarga un archivo de Drive publico. Gestiona el interstitial de confirmacion."""
    import requests
    session = requests.Session()
    urls = [
        f"https://drive.usercontent.google.com/download?id={file_id}&export=download",
        f"https://drive.google.com/uc?export=download&id={file_id}",
    ]
    for url in urls:
        resp = session.get(url, timeout=120)
        if resp.status_code != 200:
            continue
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" in ctype:
            m = re.search(r'name="confirm"\s+value="([^"]+)"', resp.text) or \
                re.search(r"confirm=([0-9A-Za-z_-]+)", resp.text)
            if not m:
                continue
            resp = session.get(f"{url}&confirm={m.group(1)}", timeout=120)
            if resp.status_code != 200 or "text/html" in resp.headers.get("Content-Type", "").lower():
                continue
        return resp.content
    return None


def process_image(raw_bytes, dest_path):
    """Endereza, reduce y comprime. Devuelve True si el archivo cambio."""
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception as exc:
        log(f"  aviso: los bytes descargados no son una imagen valida ({exc})")
        return None
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    new_bytes = buf.getvalue()
    if dest_path.is_file() and dest_path.read_bytes() == new_bytes:
        return False
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(new_bytes)
    return True


# ---------------------------------------------------------------- registro

def build_records(rows, cols):
    """Filtra, deduplica por slug (gana la fila mas reciente) y construye registros."""
    survivors = []
    for idx, row in enumerate(rows, start=2):  # fila 1 = encabezados
        name = (row.get(cols["name"]) or "").strip()
        desc = (row.get(cols["description"]) or "").strip()
        photo = (row.get(cols["photo"]) or "").strip()
        if not name or not desc or not photo:
            log(f"  fila {idx}: incompleta (nombre/descripcion/foto), se omite")
            continue
        hide = (row.get(cols["hide"]) or "").strip().lower() if cols["hide"] else ""
        if hide in ("si", "sí"):
            log(f"  fila {idx}: oculta ({name})")
            continue
        ts = parse_timestamp(row.get(cols["timestamp"]))
        survivors.append({"idx": idx, "ts": ts, "row": row, "name": name})

    # slugs deterministas; colisiones de piezas distintas -> sufijo en orden temporal
    survivors.sort(key=lambda r: (r["ts"] or datetime.min, r["idx"]))
    slug_by_name = {}
    taken = {}
    for r in survivors:
        if r["name"] in slug_by_name:
            r["slug"] = slug_by_name[r["name"]]
            continue
        base = slugify(r["name"])
        slug, n = base, 1
        while slug in taken and taken[slug] != r["name"]:
            n += 1
            slug = f"{base}-{n}"
            log(f"  aviso: slug duplicado «{base}» -> «{slug}» ({r['name']})")
        slug_by_name[r["name"]] = slug
        taken[slug] = r["name"]
        r["slug"] = slug

    # ultima fila por slug = version vigente (reenvio del formulario = edicion)
    latest = {}
    for r in survivors:
        latest[r["slug"]] = r

    records = []
    images_downloaded = 0
    for r in latest.values():
        row, slug = r["row"], r["slug"]
        photo_cell = (row.get(cols["photo"]) or "").strip()

        if photo_cell.startswith("img/"):
            image_path = photo_cell            # ruta del repo: se usa tal cual
            if not (ROOT / image_path).is_file():
                log(f"  aviso: {image_path} no existe en el repo ({r['name']})")
        else:
            ids = extract_drive_ids(photo_cell)
            if not ids:
                log(f"  fila {r['idx']}: celda de foto sin ID de Drive, se omite ({r['name']})")
                continue
            dest = IMG_DIR / f"{slug}.jpg"
            raw = download_drive_file(ids[0])
            if raw is None:
                if dest.is_file():
                    log(f"  aviso: no se pudo descargar la foto de «{r['name']}», se conserva la anterior")
                else:
                    log(f"  fila {r['idx']}: no se pudo descargar la foto, se omite ({r['name']})")
                    continue
            else:
                changed = process_image(raw, dest)
                if changed is None:
                    if not dest.is_file():
                        log(f"  fila {r['idx']}: la foto no es una imagen valida, se omite ({r['name']})")
                        continue
                elif changed:
                    images_downloaded += 1
            image_path = f"img/piezas/{slug}.jpg"

        status = (row.get(cols["status"]) or "").strip()
        if status.lower() not in STATUS_MAP:
            log(f"  aviso: estado desconocido «{status}» en «{r['name']}», se muestra como pieza unica")

        order_raw = (row.get(cols["order"]) or "").strip() if cols["order"] else ""
        order = int(order_raw) if order_raw.isdigit() else None

        records.append({
            "submitted": r["ts"].isoformat() if r["ts"] else None,
            "name": r["name"],
            "slug": slug,
            "description": (row.get(cols["description"]) or "").strip(),
            "image": image_path,
            "alt": (row.get(cols["alt"]) or "").strip(),
            "status": status or "Pieza única",
            "price": normalize_price(row.get(cols["price"]) if cols["price"] else ""),
            "instagram": normalize_instagram(row.get(cols["instagram"]) if cols["instagram"] else ""),
            "order": order,
            "name_en": (row.get(cols["name_en"]) or "").strip() or None if cols["name_en"] else None,
            "description_en": (row.get(cols["description_en"]) or "").strip() or None if cols["description_en"] else None,
        })

    # orden de aparicion: Orden asc primero, resto por fecha desc (nuevo arriba)
    with_order = sorted([x for x in records if x["order"] is not None], key=lambda x: x["order"])
    without = sorted([x for x in records if x["order"] is None],
                     key=lambda x: x["submitted"] or "", reverse=True)
    return with_order + without, images_downloaded


# ---------------------------------------------------------------- render

def esc(text):
    return html.escape(text, quote=False)


def esc_attr(text):
    return html.escape(text, quote=True)


def render_card(rec):
    chip_class, chip_key = STATUS_MAP.get(rec["status"].lower(), ("chip-ok", "chip-uni"))
    en_name = f' data-en="{esc_attr(rec["name_en"])}"' if rec["name_en"] else ""
    en_desc = f' data-en="{esc_attr(rec["description_en"])}"' if rec["description_en"] else ""

    img = (f'<img class="card-photo" src="{esc_attr(rec["image"])}"'
           f' alt="{esc_attr(rec["alt"])}" loading="lazy">')
    if rec["instagram"]:
        art = (f'          <a class="card-art" href="{esc_attr(rec["instagram"])}">\n'
               f'            {img}\n'
               f'          </a>')
        see = (f'              <a class="see-post" data-i18n="see-post"'
               f' href="{esc_attr(rec["instagram"])}">Ver el post →</a>\n')
    else:
        art = (f'          <span class="card-art">\n'
               f'            {img}\n'
               f'          </span>')
        see = ""

    price = f'              <span class="price-tag">{esc(rec["price"])}</span>\n' if rec["price"] else ""

    return (
        '        <article class="card reveal">\n'
        f'{art}\n'
        '          <div class="card-body">\n'
        f'            <h3{en_name}>{esc(rec["name"])}</h3>\n'
        f'            <p class="mat"{en_desc}>{esc(rec["description"])}</p>\n'
        '            <div class="card-meta">\n'
        f'{see}{price}'
        f'              <span class="chip {chip_class}" data-i18n="{chip_key}">{esc(rec["status"])}</span>\n'
        '            </div>\n'
        '          </div>\n'
        '        </article>'
    )


def render_cards(records):
    return "\n\n".join(render_card(r) for r in records)


def render_jsonld(records):
    items = []
    for pos, rec in enumerate(records, start=1):
        product = {
            "@type": "Product",
            "position": pos,
            "name": f"{rec['name']} · patchwork hecho a mano",
            "description": rec["description"],
            "image": SITE_URL + rec["image"],
            "url": rec["instagram"] or (SITE_URL + "#coleccion"),
            "brand": {"@type": "Brand", "name": "CLOP Patchwork"},
        }
        if rec["price"]:
            product["offers"] = {
                "@type": "Offer",
                "price": rec["price"].replace(",", ".").replace(" €", ""),
                "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock"
                if rec["status"].lower() not in ("vendido", "vendidos")
                else "https://schema.org/SoldOut",
                "url": SITE_URL + "#coleccion",
            }
        items.append(product)
    data = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Colección de piezas de patchwork",
        "itemListElement": items,
    }
    body = json.dumps(data, ensure_ascii=False, indent=1)
    return f'<script type="application/ld+json">\n{body}\n</script>'


def inject(text, start, end, content):
    i = text.index(start) + len(start)
    j = text.index(end)
    return text[:i] + "\n" + content + "\n" + text[j:]


def write_if_changed(path, content):
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return True


# ---------------------------------------------------------------- main

def main():
    url = os.environ.get("SHEET_CSV_URL", "").strip()
    if not url:
        die("Falta la variable SHEET_CSV_URL")

    text = fetch_csv(url)
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        die("El CSV no tiene encabezados")
    cols = resolve_columns(reader.fieldnames)
    rows = list(reader)

    # guardia: un CSV vacio jamas debe borrar una coleccion existente
    if not rows:
        existing = []
        if JSON_PATH.is_file():
            existing = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        if existing:
            die("El CSV llego vacio pero la coleccion actual tiene piezas; se aborta")

    records, downloaded = build_records(rows, cols)
    if not records and JSON_PATH.is_file() and json.loads(JSON_PATH.read_text(encoding="utf-8")):
        die("Ninguna fila valida pero la coleccion actual tiene piezas; se aborta")

    json_text = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    json_changed = write_if_changed(JSON_PATH, json_text)

    index_text = INDEX_PATH.read_text(encoding="utf-8")
    for marker in (CARDS_START, CARDS_END, LD_START, LD_END):
        if marker not in index_text:
            die(f"Marcador {marker} no encontrado en index.html")
    index_text = inject(index_text, CARDS_START, CARDS_END, render_cards(records))
    index_text = inject(index_text, LD_START, LD_END, render_jsonld(records))
    index_changed = write_if_changed(INDEX_PATH, index_text)

    log(f"Piezas publicadas: {len(records)}")
    log(f"Imagenes nuevas o cambiadas: {downloaded}")
    log(f"piezas.json {'actualizado' if json_changed else 'sin cambios'}; "
        f"index.html {'actualizado' if index_changed else 'sin cambios'}")


if __name__ == "__main__":
    main()
