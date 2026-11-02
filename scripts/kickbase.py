# -*- coding: utf-8 -*-
"""Kleiner Kickbase-Client fuer SGLDE (Python 3.7, nutzt requests wenn vorhanden).

Zugang: Umgebungsvariablen <NAME>_EMAIL / <NAME>_PASSWORT
        oder Datei config/<name>.txt (Zeile 1 E-Mail, Zeile 2 Passwort).
"""
import json
import os
import time
import urllib.error
import urllib.request

try:
    import requests  # wie bei den Junkies; Cloudflare sperrt die urllib-Kennung
except ImportError:
    requests = None

KENNUNG = "python-requests/2.31.0"

BASIS = "https://api.kickbase.com"
BILD_BASIS = "https://kickbase.b-cdn.net/"
ORDNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def zugang(name):
    em = os.environ.get(name.upper() + "_EMAIL")
    pw = os.environ.get(name.upper() + "_PASSWORT")
    if em and pw:
        return em.strip(), pw.strip()
    pfad = os.path.join(ORDNER, "config", name + ".txt")
    if not os.path.exists(pfad):
        raise SystemExit("Zugang fehlt: %s (oder Env %s_EMAIL/_PASSWORT)" % (pfad, name.upper()))
    with open(pfad, encoding="utf-8-sig") as f:
        zeilen = [z.strip() for z in f.read().splitlines() if z.strip()]
    return zeilen[0], zeilen[1]


class ApiFehler(Exception):
    def __init__(self, status, text):
        Exception.__init__(self, "HTTP %s: %s" % (status, text[:200]))
        self.status = status


class Api(object):
    def __init__(self, name="privat", pause=0.25):
        self.pause = pause
        self.token = None
        self.user = None
        em, pw = zugang(name)
        try:
            antwort = self._roh("POST", "/v4/user/login",
                                {"em": em, "pass": pw, "loy": False, "rep": {}})
        except ApiFehler as e:
            raise SystemExit("Login fehlgeschlagen (%s) - E-Mail/Passwort in config/%s.txt pruefen."
                             % (e, name))
        self.token = antwort.get("tkn")
        self.user = antwort.get("u") or {}
        if not self.token:
            raise SystemExit("Login fehlgeschlagen (kein Token).")

    def _roh(self, methode, pfad, daten=None):
        url = pfad if pfad.startswith("http") else BASIS + pfad
        kopf = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            kopf["Authorization"] = "Bearer " + self.token
        try:
            if requests is not None:
                r = requests.request(methode, url, json=daten, headers=kopf, timeout=30)
                if r.status_code >= 400:
                    raise ApiFehler(r.status_code, r.text)
                text = r.text
            else:
                kopf["User-Agent"] = KENNUNG
                koerper = json.dumps(daten).encode("utf-8") if daten is not None else None
                req = urllib.request.Request(url, data=koerper, method=methode, headers=kopf)
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        text = r.read().decode("utf-8")
                except urllib.error.HTTPError as e:
                    raise ApiFehler(e.code, e.read().decode("utf-8", "replace"))
        finally:
            time.sleep(self.pause)
        return json.loads(text) if text.strip() else {}

    def get(self, pfad, versuche=4):
        """GET mit Wiederholung bei Verbindungsabbruch oder Serverfehler (5xx/429)."""
        for nr in range(versuche):
            try:
                return self._roh("GET", pfad)
            except ApiFehler as e:
                if e.status not in (429, 500, 502, 503, 504) or nr == versuche - 1:
                    raise
            except Exception:
                if nr == versuche - 1:
                    raise
            time.sleep(2 + 3 * nr)


def bild_url(wert):
    """Kickbase liefert Bilder teils als relativen Pfad."""
    if not wert:
        return None
    if wert.startswith("http"):
        return wert
    return BILD_BASIS + wert.lstrip("/")


def bild_laden(url, ziel):
    if requests is not None:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        daten = r.content
    else:
        req = urllib.request.Request(url, headers={"User-Agent": KENNUNG})
        with urllib.request.urlopen(req, timeout=30) as r:
            daten = r.read()
    with open(ziel, "wb") as f:
        f.write(daten)
    return len(daten)
