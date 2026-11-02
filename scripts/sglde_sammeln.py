# -*- coding: utf-8 -*-
"""Sammelt alle Daten der Liga SGLDE 4.1 nach liga/daten/ (nur lesen).

Aufruf:  python scripts/sglde_sammeln.py            (normaler Lauf, holt nur Neues)
         python scripts/sglde_sammeln.py --alles    (alle Spieltage und Spieler neu)

Ablage (liga/daten/):
  liga.json          Ligaprofil (Name, Logo, Manager mit Bild)
  spielplan.json     Bundesliga-Spielplan (Anstosszeiten, Status)
  st_NN.json         Wertung je Spieltag (Punkte, Platz, Kaderwert, Startelf)
  transfers.json     kompletter Transferverlauf je Manager
  aktivitaeten.json  Aktivitaetsfeed, wird bei jedem Lauf ergaenzt (Kickbase haelt nur ~2-3 Wochen)
  kader.json         aktueller Kader je Manager
  spieler.json       Spieler (Name, Verein, Position, Punkte je Spieltag, Marktwert)
  stand.json         Zeitpunkt des Laufs, abgeschlossene Spieltage
  ../bilder/         logo.* und manager_<id>.*
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kickbase import Api, ApiFehler, ORDNER, bild_url, bild_laden  # noqa: E402
from sglde_auswerten import berlin_offset, berlin_nach_utc  # noqa: E402

CONFIG = os.path.join(ORDNER, "config", "sglde.json")
DATEN = os.path.join(ORDNER, "liga", "daten")
BILDER = os.path.join(ORDNER, "liga", "bilder")
# Aktionsarten Saison 26/27 (aus /v4/live/eventtypes, mit Ergebnissen ST 7 abgeglichen)
TOR_CODES = {4285, 4288, 4291, 4294, 4045}      # Goal (GK/MF/DEF/ST), Penalty scored
ASSIST_CODES = {4297, 4300, 4303, 4306}         # Assist (GK/DEF/MF/ST)
# Kickbase rechnet am Tag nach dem letzten Spiel um 18 Uhr (Ortszeit) ab.
# Ein Spieltag gilt als abgeschlossen ab Abrechnung + 1 Stunde (normal Montag 19 Uhr).
ABRECHNUNG_UHR = 18
FERTIG_NACH_ABRECHNUNG_MIN = 60
NACHKONTROLLE_TAGE = 3     # abgeschlossene Spieltage werden so lange noch neu geholt


def lesen(name, standard=None):
    pfad = os.path.join(DATEN, name)
    if not os.path.exists(pfad):
        return standard
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def schreiben(name, daten):
    pfad = os.path.join(DATEN, name)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, pfad)


def iso_z(dt):
    return dt.isoformat() + "Z"


def zeit(text):
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


def spieltage_auswerten(spielplan, jetzt):
    """-> {st: {'start','ende','fertig_ab','fertig'}} (UTC)"""
    info = {}
    for md in spielplan.get("it", []):
        st = md.get("day")
        anstoesse = sorted(zeit(m["dt"]) for m in md.get("it", []) if m.get("dt"))
        if not st or not anstoesse:
            continue
        lokal = anstoesse[-1] + berlin_offset(anstoesse[-1])
        abrechnung = (lokal + datetime.timedelta(days=1)).replace(hour=ABRECHNUNG_UHR, minute=0, second=0)
        fertig_ab = berlin_nach_utc(abrechnung) + datetime.timedelta(minutes=FERTIG_NACH_ABRECHNUNG_MIN)
        info[st] = {"start": anstoesse[0].isoformat() + "Z",
                    "letzter_anstoss": anstoesse[-1].isoformat() + "Z",
                    "fertig_ab": fertig_ab.isoformat() + "Z",
                    "fertig": jetzt >= fertig_ab,
                    "begonnen": jetzt >= anstoesse[0]}
    return info


def scorer_sammeln(api, cfg, spielplan, fertige, sti, spieler, jetzt, alles=False):
    """Tore und Assists der aufgestellten Spieler je Spieltag -> scorer.json {st: {pid: [tore, assists]}}."""
    # --- Tore und Assists der aufgestellten Spieler (Spielaktionen je Spieler und Spieltag)
    #     Korrekturen kommen als Gegenbuchung mit negativen Punkten -> netto zaehlen.
    scorer = lesen("scorer.json", {}) or {}
    wb = cfg.get("wettbewerb", 1)
    for st in fertige:
        alt_st = scorer.get(str(st))
        grenze = zeit(sti[st]["fertig_ab"]) + datetime.timedelta(days=NACHKONTROLLE_TAGE)
        if alt_st and not alles and jetzt >= grenze and alt_st.get("_stand", "") >= iso_z(grenze):
            continue
        d = lesen("st_%02d.json" % st) or {"manager": []}
        spiele = {str(m.get("mi")) for md in spielplan.get("it", []) if md.get("day") == st
                  for m in md.get("it", [])}
        eintrag = {"_stand": jetzt.isoformat() + "Z"}
        for m in d["manager"]:
            for pid in m.get("lp", []):
                pid = str(pid)
                if pid in eintrag:
                    continue
                if str(st) not in (spieler.get(pid) or {}).get("punkte", {}):
                    eintrag[pid] = [0, 0]   # kein Einsatz -> keine Abfrage noetig
                    continue
                try:
                    pc = api.get("/v4/competitions/%s/playercenter/%s?dayNumber=%d" % (wb, pid, st))
                except ApiFehler as e:
                    print("Scorer %s ST %d: %s" % (pid, st, e))
                    continue
                if spiele and str(pc.get("mi")) not in spiele:
                    eintrag[pid] = [0, 0]
                    continue
                tore = assists = 0
                for ev in pc.get("events", []) or []:
                    eti = int(ev.get("eti") or 0)
                    vz = 1 if (ev.get("p") or 0) > 0 else -1 if (ev.get("p") or 0) < 0 else 0
                    if eti in TOR_CODES:
                        tore += vz
                    elif eti in ASSIST_CODES:
                        assists += vz
                eintrag[pid] = [max(0, tore), max(0, assists)]
        scorer[str(st)] = eintrag
        print("Scorer ST %d: %d Tore, %d Assists" % (
            st, sum(v[0] for k, v in eintrag.items() if k != "_stand"),
            sum(v[1] for k, v in eintrag.items() if k != "_stand")))
        schreiben("scorer.json", scorer)


def main():
    alles = "--alles" in sys.argv
    os.makedirs(DATEN, exist_ok=True)
    os.makedirs(BILDER, exist_ok=True)
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    liga = cfg["liga_id"]
    L = "/v4/leagues/%s" % liga
    st_von = cfg["spieltage"]["von"]
    st_bis = cfg["spieltage"]["bis"] or 34
    jetzt = datetime.datetime.utcnow()

    api = Api(cfg.get("zugang", "privat"))
    print("Eingeloggt als", api.user.get("name"), "| Liga", liga)

    # --- Liga und Spielplan
    uebersicht = api.get(L + "/overview")
    me = api.get(L + "/me")
    spielplan = api.get("/v4/competitions/%s/matchdays" % cfg.get("wettbewerb", 1))
    schreiben("spielplan.json", spielplan)
    sti = spieltage_auswerten(spielplan, jetzt)

    # --- Wertungen je Spieltag
    alt_stand = lesen("stand.json", {}) or {}
    geholt_am = alt_stand.get("st_geholt", {})
    fertige = []
    for st in range(st_von, st_bis + 1):
        info = sti.get(st)
        if not info or not info["begonnen"]:
            break
        datei = "st_%02d.json" % st
        vorhanden = os.path.exists(os.path.join(DATEN, datei))
        neu_noetig = alles or not vorhanden or not info["fertig"]
        if vorhanden and info["fertig"] and not alles:
            # Nachkontrolle: bis NACHKONTROLLE_TAGE nach "fertig_ab" weiter neu holen
            grenze = zeit(info["fertig_ab"]) + datetime.timedelta(days=NACHKONTROLLE_TAGE)
            neu_noetig = jetzt < grenze
        if neu_noetig:
            r = api.get(L + "/ranking?dayNumber=%d" % st)
            eintrag = {"st": st, "fertig": info["fertig"], "abgerufen": jetzt.isoformat() + "Z",
                       "manager": []}
            for m in r.get("us", []):
                eintrag["manager"].append({
                    "i": m.get("i"), "n": m.get("n"), "adm": m.get("adm", False),
                    "mdp": m.get("mdp", 0), "mdpl": m.get("mdpl"), "sp": m.get("sp", 0),
                    "spl": m.get("spl"), "tv": m.get("tv"), "lp": m.get("lp", []),
                    "uim": m.get("uim")})
            schreiben(datei, eintrag)
            geholt_am[str(st)] = jetzt.isoformat() + "Z"
            print("Spieltag %d %s" % (st, "(fertig)" if info["fertig"] else "(laeuft)"))
        if info["fertig"]:
            fertige.append(st)

    # --- Manager: Liste aus der aktuellsten Wertung
    akt = api.get(L + "/ranking")
    manager = {}
    for m in akt.get("us", []):
        manager[m["i"]] = {"n": m.get("n"), "uim": m.get("uim"), "adm": m.get("adm", False),
                           "sp": m.get("sp"), "tv": m.get("tv")}

    # --- Kader und Transfers je Manager
    kader = {}
    ab = cfg.get("transfers_ab", "2026-08-01")   # aeltere Transfers (Vorsaison) ignorieren
    transfers = lesen("transfers.json", {}) or {}
    for uid in list(transfers):
        transfers[uid] = [t for t in transfers[uid] if (t.get("dt") or "") >= ab]
    for uid in manager:
        sq = api.get(L + "/managers/%s/squad" % uid)
        kader[uid] = [{"pi": p.get("pi"), "pn": p.get("pn"), "tid": p.get("tid"),
                       "pos": p.get("pos"), "mv": p.get("mv"), "prc": p.get("prc"),
                       "p": p.get("p"), "ap": p.get("ap"), "st": p.get("st"),
                       "lo": p.get("lo")} for p in sq.get("it", [])]
        manager[uid]["status"] = sq.get("st")
        bekannt = {(t["pi"], t["dt"], t["tty"]) for t in transfers.get(uid, [])}
        neu = []
        start = 0
        while start < 2000:
            seite = api.get(L + "/managers/%s/transfer?start=%d" % (uid, start)).get("it", [])
            if not seite:
                break
            treffer_alt = 0
            zu_alt = 0
            for t in seite:
                if (t.get("dt") or "") < ab:
                    zu_alt += 1
                    continue
                schluessel = (t.get("pi"), t.get("dt"), t.get("tty"))
                if schluessel in bekannt:
                    treffer_alt += 1
                    continue
                bekannt.add(schluessel)
                neu.append({"pi": t.get("pi"), "pn": t.get("pn"), "tid": t.get("tid"),
                            "tty": t.get("tty"), "trp": t.get("trp"), "dt": t.get("dt")})
            if (treffer_alt and not alles) or zu_alt:
                break   # ab hier ist alles schon gespeichert bzw. aus der Vorsaison
            start += len(seite)
        transfers[uid] = sorted(transfers.get(uid, []) + neu, key=lambda t: t["dt"])
        print("Manager %-20s Kader %2d | Transfers %3d (+%d)"
              % (manager[uid]["n"], len(kader[uid]), len(transfers[uid]), len(neu)))
    schreiben("kader.json", kader)
    schreiben("transfers.json", transfers)

    # --- Aktivitaetsfeed (ergaenzen, nie loeschen)
    feed = lesen("aktivitaeten.json", {}) or {}
    start = 0
    while start < 5000:
        seite = api.get(L + "/activitiesFeed?start=%d&max=500" % start).get("af", [])
        if not seite:
            break
        neu = 0
        for a in seite:
            if a.get("i") and a["i"] not in feed:
                feed[a["i"]] = {"t": a.get("t"), "dt": a.get("dt"), "data": a.get("data")}
                neu += 1
        if not neu and not alles:
            break
        start += len(seite)
    schreiben("aktivitaeten.json", feed)
    print("Aktivitaeten gesamt:", len(feed))

    # --- Spieler: alle aus Startelfen, Kadern und Transfers
    spieler = lesen("spieler.json", {}) or {}
    ids = set()
    for st in fertige + [s for s in sti if sti[s]["begonnen"] and s <= st_bis]:
        d = lesen("st_%02d.json" % st)
        if d:
            for m in d["manager"]:
                ids.update(str(p) for p in m.get("lp", []))
    for liste in kader.values():
        ids.update(str(p["pi"]) for p in liste)
    for liste in transfers.values():
        ids.update(str(t["pi"]) for t in liste if t["dt"] >= sti.get(st_von, {}).get("start", ab))
    letzter_fertiger = max(fertige) if fertige else 0
    laufend = [s for s in sti if sti[s]["begonnen"] and not sti[s]["fertig"]]
    geholt = 0
    print("Spieler pruefen:", len(ids))
    for nr, pid in enumerate(sorted(ids, key=int), 1):
        if nr % 50 == 0:
            print("  %d / %d" % (nr, len(ids)))
            schreiben("spieler.json", spieler)   # Zwischenstand, falls abgebrochen wird
        alt = spieler.get(pid)
        if alt and not alles and not laufend:
            # nur neu holen, wenn ein abgeschlossener Spieltag fehlt oder in der Nachkontrolle ist
            hat = alt.get("stand_st", 0)
            if hat >= letzter_fertiger and alt.get("stand", "") > geholt_am.get(str(letzter_fertiger), ""):
                continue
        try:
            perf = api.get(L + "/players/%s/performance" % pid)
            # Stammdaten nur fuer neue Spieler (spart die Haelfte der Abfragen)
            info = api.get(L + "/players/%s" % pid) if (alles or not alt) else {}
        except ApiFehler as e:
            print("Spieler %s: %s" % (pid, e))
            continue
        saison = (perf.get("it") or [{}])[-1]
        punkte = {}
        for h in saison.get("ph", []):
            if h.get("p") is not None:
                punkte[str(h["day"])] = {"p": h["p"], "mp": h.get("mp"), "mi": h.get("mi")}
        alt = alt or {}
        spieler[pid] = {"n": info.get("ln") or alt.get("n"), "fn": info.get("fn") or alt.get("fn"),
                        "tid": info.get("tid") or alt.get("tid"), "tn": info.get("tn") or alt.get("tn"),
                        "pos": info.get("pos") or alt.get("pos"), "pim": info.get("pim") or alt.get("pim"),
                        "saison": saison.get("ti"), "punkte": punkte,
                        "stand_st": letzter_fertiger, "stand": jetzt.isoformat() + "Z"}
        geholt += 1
    schreiben("spieler.json", spieler)
    print("Spieler gesamt %d, aktualisiert %d" % (len(spieler), geholt))

    scorer_sammeln(api, cfg, spielplan, fertige, sti, spieler, jetzt, alles)

    # --- Bilder (Logo + Manager), nur wenn noch nicht vorhanden
    def bild(roh, name):
        if not roh:
            return None
        url = bild_url(roh)
        endung = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
        if endung == ".jpe":
            endung = ".jpg"
        datei = name + endung
        ziel = os.path.join(BILDER, datei)
        if not os.path.exists(ziel) or alles:
            try:
                bild_laden(url, ziel)
            except Exception as e:
                print("Bild %s: %s" % (name, e))
                return None
        return datei
    logo = bild(uebersicht.get("lim") or me.get("lim"), "logo")
    for uid, m in manager.items():
        m["bild"] = bild(m.get("uim"), "manager_%s" % uid)

    schreiben("liga.json", {"i": str(liga), "name": uebersicht.get("lnm"), "logo": logo,
                            "mgc": uebersicht.get("mgc"), "budget_start": uebersicht.get("b"),
                            "kader_max": uebersicht.get("mppu"), "max_je_verein": uebersicht.get("mpst"),
                            "manager": manager})
    schreiben("stand.json", {"lauf": jetzt.isoformat() + "Z", "fertige": fertige,
                             "laufend": laufend, "spieltage": sti, "st_geholt": geholt_am})
    print("\nFertig. Abgeschlossene Spieltage:", fertige, "| laufend:", laufend)


if __name__ == "__main__":
    main()
