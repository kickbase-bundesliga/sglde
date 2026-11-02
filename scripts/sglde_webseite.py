# -*- coding: utf-8 -*-
"""Baut die SGLDE-Webseite aus liga/daten/ + scripts/sglde_vorlage.html.

Aufruf:  python scripts/sglde_webseite.py             -> liga/webseite/index.html (+ bilder/)
         python scripts/sglde_webseite.py --vorschau  -> zusaetzlich liga/vorschau.html
                                                        (eine Datei, Bilder eingebettet)
"""
import base64
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kickbase import ORDNER  # noqa: E402
from sglde_auswerten import auswerten  # noqa: E402

VORLAGE = os.path.join(ORDNER, "scripts", "sglde_vorlage.html")
BILDER = os.path.join(ORDNER, "liga", "bilder")
ZIEL = os.path.join(ORDNER, "liga", "webseite")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".gif": "image/gif", ".svg": "image/svg+xml"}
KOPF = ('<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        '<meta name="theme-color" content="#121210">\n<link rel="icon" href="bilder/logo.png">\n'
        '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n')
FUSS = "\n</body>\n</html>\n"


def verkleinern(roh, kante):
    """Mit Pillow (falls installiert) auf kante x kante verkleinern -> (mime, bytes) oder None."""
    try:
        from PIL import Image
        import io
    except ImportError:
        return None
    try:
        bild = Image.open(io.BytesIO(roh))
        bild.thumbnail((kante, kante))
        aus = io.BytesIO()
        if bild.mode in ("RGBA", "LA", "P"):
            bild.convert("RGBA").save(aus, "PNG", optimize=True)
            return "image/png", aus.getvalue()
        bild.convert("RGB").save(aus, "JPEG", quality=85)
        return "image/jpeg", aus.getvalue()
    except Exception:
        return None


def eingebettete_bilder(daten, max_bytes=1000000):
    """Bilder als data:-URIs (fuer die Vorschau ohne Bilderordner)."""
    karte = {}
    namen = {"logo": daten["liga"].get("logo")}
    for uid, m in daten["manager"].items():
        namen["manager_" + uid] = m.get("bild")
    for schluessel, datei in namen.items():
        if not datei:
            continue
        pfad = os.path.join(BILDER, datei)
        if not os.path.exists(pfad) or os.path.getsize(pfad) > max_bytes:
            continue
        typ = MIME.get(os.path.splitext(datei)[1].lower(), "image/png")
        with open(pfad, "rb") as f:
            roh = f.read()
        klein = verkleinern(roh, 160 if schluessel == "logo" else 96)
        if klein:
            typ, roh = klein
        karte[schluessel] = "data:%s;base64,%s" % (typ, base64.b64encode(roh).decode("ascii"))
    return karte


def bauen(daten, bilder_karte):
    with open(VORLAGE, encoding="utf-8") as f:
        html = f.read()
    roh = json.dumps(daten, ensure_ascii=False, separators=(",", ":"), default=str)
    roh = roh.replace("</", "<\\/")  # kein vorzeitiges </script>
    html = html.replace("/*__DATEN__*/null", roh, 1)
    html = html.replace("/*__BILDER__*/{}", json.dumps(bilder_karte), 1)
    return html


def main():
    daten = auswerten()
    os.makedirs(ZIEL, exist_ok=True)
    # Webseite mit Bilderordner
    ziel_bilder = os.path.join(ZIEL, "bilder")
    os.makedirs(ziel_bilder, exist_ok=True)
    if os.path.isdir(BILDER):
        for datei in os.listdir(BILDER):
            shutil.copy2(os.path.join(BILDER, datei), os.path.join(ziel_bilder, datei))
    with open(os.path.join(ZIEL, "index.html"), "w", encoding="utf-8") as f:
        f.write(KOPF + bauen(daten, {}) + FUSS)
    print("Webseite:", os.path.join(ZIEL, "index.html"))
    if "--vorschau" in sys.argv:
        pfad = os.path.join(ORDNER, "liga", "vorschau.html")
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(bauen(daten, eingebettete_bilder(daten)))
        print("Vorschau (eine Datei):", pfad)


if __name__ == "__main__":
    main()
