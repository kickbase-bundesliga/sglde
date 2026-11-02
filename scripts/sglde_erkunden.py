# -*- coding: utf-8 -*-
"""Einmalige API-Erkundung fuer SGLDE 4.1 (nur lesen, aendert nichts in Kickbase).

Aufruf:  python scripts/sglde_erkunden.py
Ergebnis: api_dump/sglde/ (Rohdaten je Abfrage + uebersicht.txt + bilder/)
Danach den Ordner api_dump/sglde als ZIP an Claude schicken.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kickbase import Api, ApiFehler, ORDNER, bild_url, bild_laden  # noqa: E402

LIGA = 4112495
ZIEL = os.path.join(ORDNER, "api_dump", "sglde")
BILDER = os.path.join(ZIEL, "bilder")
protokoll = []


def speichern(name, daten):
    with open(os.path.join(ZIEL, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)


def holen(api, name, pfad):
    try:
        daten = api.get(pfad)
        speichern(name, daten)
        groesse = len(json.dumps(daten))
        protokoll.append("OK    %-40s %s (%d Zeichen)" % (name, pfad, groesse))
        print("OK   ", name)
        return daten
    except ApiFehler as e:
        protokoll.append("FEHLER %-39s %s -> %s" % (name, pfad, e.status))
        print("FEHLER", name, e.status)
    except Exception as e:  # Netzwerk o. ae.
        protokoll.append("FEHLER %-39s %s -> %s" % (name, pfad, e))
        print("FEHLER", name, e)
    return None


def bilder_suchen(obj, gefunden):
    if isinstance(obj, dict):
        for v in obj.values():
            bilder_suchen(v, gefunden)
    elif isinstance(obj, list):
        for v in obj:
            bilder_suchen(v, gefunden)
    elif isinstance(obj, str) and re.search(r"\.(png|jpe?g|webp|gif)(\?|$)", obj, re.I):
        gefunden.add(obj)


def main():
    import kickbase
    print("SGLDE-Erkundung Version 3 | requests:", "ja" if kickbase.requests else "NEIN (urllib)")
    os.makedirs(BILDER, exist_ok=True)
    api = Api("privat")
    eigene_id = api.user.get("id") or api.user.get("i")
    print("Eingeloggt als", api.user.get("name") or api.user.get("unm"), eigene_id)
    L = "/v4/leagues/%d" % LIGA

    holen(api, "login_user", "/v4/user/settings")
    uebersicht = holen(api, "liga_overview", L + "/overview")
    holen(api, "liga_me", L + "/me")
    holen(api, "liga_settings", L + "/settings")
    holen(api, "liga_settings_managers", L + "/settings/managers")
    holen(api, "liga_info", "/v4/leagues/selection")
    ranking = holen(api, "ranking_aktuell", L + "/ranking")
    holen(api, "spielplan", "/v4/competitions/1/matchdays")

    # Wertung je Spieltag (bis zur ersten leeren Runde)
    manager = {}
    for st in range(1, 18):
        r = holen(api, "ranking_st%02d" % st, L + "/ranking?dayNumber=%d" % st)
        if not r:
            continue
        liste = r.get("us") or r.get("it") or []
        for m in liste:
            uid = m.get("i")
            if uid:
                manager[uid] = m.get("n")
        if liste and all(not m.get("mdp") for m in liste):
            print("   ST %d noch ohne Punkte -> Schluss" % st)
            break
    if not manager and ranking:
        for m in ranking.get("us") or []:
            manager[m.get("i")] = m.get("n")
    print("Manager:", len(manager))

    # je Manager
    for uid in manager:
        holen(api, "manager_%s_dashboard" % uid, L + "/managers/%s/dashboard" % uid)
        holen(api, "manager_%s_squad" % uid, L + "/managers/%s/squad" % uid)
        holen(api, "manager_%s_transfer" % uid, L + "/managers/%s/transfer" % uid)
        holen(api, "manager_%s_transfer_s25" % uid, L + "/managers/%s/transfer?start=25" % uid)
        holen(api, "manager_%s_teamcenter_st01" % uid, L + "/users/%s/teamcenter?dayNumber=1" % uid)

    # Aktivitaeten (Transfers, Kaeufe, Verkaeufe)
    holen(api, "activities_0", L + "/activitiesFeed?start=0&max=500")
    holen(api, "activities_500", L + "/activitiesFeed?start=500&max=500")

    # ein Beispielspieler aus der ersten Aufstellung: Punkte- und MW-Verlauf
    pid = None
    r1 = None
    pfad1 = os.path.join(ZIEL, "ranking_st01.json")
    if os.path.exists(pfad1):
        with open(pfad1, encoding="utf-8") as f:
            r1 = json.load(f)
        for m in r1.get("us") or []:
            if m.get("lp"):
                pid = m["lp"][0]
                break
    if pid:
        holen(api, "spieler_%s_liga" % pid, L + "/players/%s" % pid)
        holen(api, "spieler_%s_performance" % pid, L + "/players/%s/performance" % pid)
        holen(api, "spieler_%s_comp_performance" % pid, "/v4/competitions/1/players/%s/performance" % pid)
        holen(api, "spieler_%s_mw92" % pid, L + "/players/%s/marketvalue/92" % pid)
        holen(api, "spieler_%s_transfers" % pid, L + "/players/%s/transfers" % pid)
        holen(api, "spieler_%s_transferhistory" % pid, L + "/players/%s/transferHistory" % pid)

    # Bilder (Liga-Logo, Profilbilder) aus allen gesammelten Daten
    gefunden = set()
    for datei in os.listdir(ZIEL):
        if datei.endswith(".json") and datei.startswith(("liga_", "ranking_aktuell")) \
                or datei.endswith("_dashboard.json"):
            with open(os.path.join(ZIEL, datei), encoding="utf-8") as f:
                bilder_suchen(json.load(f), gefunden)
    print("Bilder gefunden:", len(gefunden))
    for nr, roh in enumerate(sorted(gefunden)):
        url = bild_url(roh)
        endung = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        ziel = os.path.join(BILDER, "bild_%03d%s" % (nr, endung))
        try:
            n = bild_laden(url, ziel)
            protokoll.append("BILD  %s -> %s (%d Bytes)" % (roh, os.path.basename(ziel), n))
        except Exception as e:
            protokoll.append("BILD-FEHLER %s -> %s" % (roh, e))

    with open(os.path.join(ZIEL, "uebersicht.txt"), "w", encoding="utf-8") as f:
        f.write("Eigene User-ID: %s\n" % eigene_id)
        f.write("Manager: %s\n\n" % json.dumps(manager, ensure_ascii=False))
        f.write("\n".join(protokoll))
    print("\nFertig. Bitte den Ordner api_dump\\sglde als ZIP an Claude schicken.")


if __name__ == "__main__":
    os.makedirs(ZIEL, exist_ok=True)
    try:
        main()
    except BaseException:
        import traceback
        text = traceback.format_exc()
        print(text)
        with open(os.path.join(ZIEL, "fehler.txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n" + "\n".join(protokoll))
        print("Fehler gespeichert in api_dump\\sglde\\fehler.txt")
