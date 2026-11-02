# -*- coding: utf-8 -*-
"""Wertet liga/daten/ aus und liefert ein Datenpaket fuer die Webseite.

Aufruf direkt:  python scripts/sglde_auswerten.py   (schreibt liga/daten/auswertung.json zur Kontrolle)
Normalerweise ueber sglde_webseite.py.
"""
import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kickbase import ORDNER  # noqa: E402

DATEN = os.path.join(ORDNER, "liga", "daten")
CONFIG = os.path.join(ORDNER, "config", "sglde.json")
TAG = datetime.timedelta(days=1)
GLEICHZEITIG = 120  # Sekunden: Verkauf und Kauf so dicht beieinander = Verkauf an Mitmanager


# ---------------------------------------------------------------- Hilfen
def lesen(name, standard=None):
    pfad = os.path.join(DATEN, name)
    if not os.path.exists(pfad):
        return standard
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def utc(text):
    return datetime.datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _letzter_sonntag(jahr, monat):
    d = datetime.datetime(jahr, monat + 1, 1) - TAG if monat < 12 else datetime.datetime(jahr, 12, 31)
    while d.weekday() != 6:
        d -= TAG
    return d


def berlin_offset(dt_utc):
    """Sommerzeit: letzter So im Maerz 01:00 UTC bis letzter So im Oktober 01:00 UTC."""
    j = dt_utc.year
    beginn = _letzter_sonntag(j, 3).replace(hour=1)
    ende = _letzter_sonntag(j, 10).replace(hour=1)
    return datetime.timedelta(hours=2 if beginn <= dt_utc < ende else 1)


def berlin_nach_utc(dt_lokal):
    probe = dt_lokal - datetime.timedelta(hours=1)
    return dt_lokal - berlin_offset(probe)


def frist_berechnen(letzter_anstoss_utc, regel="Di 22:00"):
    """Frist = naechster Dienstag (Wochentag aus der Regel) nach dem letzten Anstoss, Ortszeit Berlin."""
    tage = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
    wtag, uhr = regel.split()
    h, m = [int(x) for x in uhr.split(":")]
    lokal = letzter_anstoss_utc + berlin_offset(letzter_anstoss_utc)
    d = (lokal + TAG).replace(hour=h, minute=m, second=0, microsecond=0)
    while d.weekday() != tage[wtag]:
        d += TAG
    return berlin_nach_utc(d)


# ---------------------------------------------------------------- Transfers
def transfers_aufbereiten(transfers, namen, feed):
    """Alle Transfers als Liste mit Gegenpartei: 'Markt' oder Manager-ID."""
    alle = []
    for uid, liste in transfers.items():
        for t in liste:
            alle.append({"uid": uid, "pi": str(t["pi"]), "pn": t.get("pn"), "tid": t.get("tid"),
                         "art": "kauf" if t.get("tty") == 1 else "verkauf",
                         "preis": t.get("trp") or 0, "dt": utc(t["dt"]), "gegen": "Markt"})
    kaeufe = [t for t in alle if t["art"] == "kauf"]
    verkaeufe = [t for t in alle if t["art"] == "verkauf"]
    # Verkauf an Mitmanager: passender Kauf desselben Spielers, gleicher Preis, fast gleiche Zeit
    for v in verkaeufe:
        for k in kaeufe:
            if k["pi"] == v["pi"] and k["uid"] != v["uid"] and k["preis"] == v["preis"] \
                    and abs((k["dt"] - v["dt"]).total_seconds()) <= GLEICHZEITIG:
                v["gegen"] = k["uid"]
                k["gegen"] = v["uid"]
                break
    # Feed als zweite Quelle (Typ 15: slr + byr = zwischen Managern)
    name_zu_id = {n: i for i, n in namen.items()}
    for a in feed.values():
        if a.get("t") != 15:
            continue
        d = a.get("data") or {}
        if d.get("slr") and d.get("byr"):
            s, b = name_zu_id.get(d["slr"]), name_zu_id.get(d["byr"])
            for v in verkaeufe:
                if v["uid"] == s and v["pi"] == str(d.get("pi")) \
                        and abs((v["dt"] - utc(a["dt"])).total_seconds()) <= GLEICHZEITIG:
                    v["gegen"] = b or v["gegen"]
    alle.sort(key=lambda t: t["dt"])
    return alle


def kader_zum_zeitpunkt(alle, uid, pid, zeitpunkt):
    """True, wenn Spieler pid zum Zeitpunkt beim Manager uid war (letzte Bewegung davor = Kauf)."""
    letzte = None
    for t in alle:
        if t["uid"] == uid and t["pi"] == pid and t["dt"] <= zeitpunkt:
            letzte = t
    return letzte is not None and letzte["art"] == "kauf"


# ---------------------------------------------------------------- Hauptauswertung
def auswerten(jetzt=None):
    jetzt = jetzt or datetime.datetime.utcnow()
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    liga = lesen("liga.json", {})
    stand = lesen("stand.json", {})
    spieler = lesen("spieler.json", {})
    scorer = lesen("scorer.json", {}) or {}
    kader = lesen("kader.json", {})
    feed = lesen("aktivitaeten.json", {})
    transfers = lesen("transfers.json", {})
    sti = {int(k): v for k, v in (stand.get("spieltage") or {}).items()}
    st_bis = cfg["spieltage"]["bis"] or 34
    ausgeschlossen = set(str(x) for x in cfg.get("admin_ids", []))

    # Spieltage laden
    spieltage = {}
    for st in range(cfg["spieltage"]["von"], st_bis + 1):
        d = lesen("st_%02d.json" % st)
        if d:
            d["manager"] = [m for m in d["manager"] if str(m["i"]) not in ausgeschlossen]
            spieltage[st] = d
    fertige = [st for st in sorted(spieltage) if sti.get(st, {}).get("fertig")]
    laufend = [st for st in sorted(spieltage) if st not in fertige]

    manager = {}
    for uid, m in (liga.get("manager") or {}).items():
        if uid in ausgeschlossen:
            continue
        manager[uid] = {"i": uid, "n": m["n"], "bild": m.get("bild"), "adm": m.get("adm")}
    for d in spieltage.values():
        for m in d["manager"]:
            manager.setdefault(m["i"], {"i": m["i"], "n": m["n"], "bild": None})
    namen = {u: m["n"] for u, m in manager.items()}

    def punkte(pid, st):
        e = (spieler.get(str(pid)) or {}).get("punkte", {}).get(str(st))
        return e["p"] if e else 0

    def spieler_name(pid):
        return (spieler.get(str(pid)) or {}).get("n") or str(pid)

    alle_transfers = transfers_aufbereiten(transfers, namen, feed)

    # ------------------------------------------------ Tabelle je Spieltag
    leer = lambda: {"sp": {}, "mdp": {}, "spl": {}, "mdpl": {}, "tv": {}, "tore": {}, "assists": {}}
    verlauf = {u: leer() for u in manager}
    for st, d in spieltage.items():
        sc = scorer.get(str(st), {})
        for m in d["manager"]:
            v = verlauf.setdefault(m["i"], leer())
            if sc:
                ga = [sc.get(str(p), [0, 0]) for p in m.get("lp", [])]
                v["tore"][st] = sum(x[0] for x in ga)
                v["assists"][st] = sum(x[1] for x in ga)
            v["sp"][st] = m["sp"]
            v["mdp"][st] = m["mdp"]
            v["spl"][st] = m["spl"]
            v["mdpl"][st] = m["mdpl"]
            v["tv"][st] = m["tv"]

    def tabelle(bis_st):
        zeilen = []
        gespielt = [s for s in spieltage if s <= bis_st]
        for u in manager:
            v = verlauf[u]
            if bis_st not in v["sp"]:
                continue
            liste = [v["mdp"][s] for s in gespielt if s in v["mdp"]]
            zeilen.append({"i": u, "sp": v["sp"][bis_st], "mdp": v["mdp"][bis_st],
                           "pl": v["spl"][bis_st], "mdpl": v["mdpl"][bis_st],
                           "siege": sum(1 for s in gespielt if v["mdpl"].get(s) == 1),
                           "schnitt": round(sum(liste) / len(liste)) if liste else 0,
                           "vorplatz": v["spl"].get(bis_st - 1), "tv": v["tv"].get(bis_st),
                           "tore": sum(v["tore"].get(s, 0) for s in gespielt),
                           "assists": sum(v["assists"].get(s, 0) for s in gespielt),
                           "st_tore": v["tore"].get(bis_st), "st_assists": v["assists"].get(bis_st),
                           "scorer_da": bool(v["tore"])})
        zeilen.sort(key=lambda z: (z["pl"] or 99, -z["sp"]))
        if zeilen:
            fuehrer = zeilen[0]["sp"]
            for z in zeilen:
                z["rueckstand"] = fuehrer - z["sp"]
        return zeilen

    tabellen = {st: tabelle(st) for st in sorted(spieltage)}

    # ------------------------------------------------ Aufstellungen mit Punkten
    aufstellungen = {}
    for st, d in spieltage.items():
        aufstellungen[st] = {}
        for m in d["manager"]:
            elf = []
            for pid in m.get("lp", []):
                s = spieler.get(str(pid)) or {}
                e = s.get("punkte", {}).get(str(st))
                elf.append({"i": str(pid), "n": s.get("n") or str(pid), "pos": s.get("pos"),
                            "tid": s.get("tid"), "p": e["p"] if e else None,
                            "mp": e.get("mp") if e else None})
            elf.sort(key=lambda x: (x["pos"] or 9, -(x["p"] or 0)))
            aufstellungen[st][m["i"]] = elf

    # ------------------------------------------------ Abgabeliste
    regel_frist = cfg["abgabe"].get("frist", {}).get("wochenende", "Di 22:00")
    frist_ueberschreiben = cfg["abgabe"].get("frist_je_st", {})
    ausnahmen = cfg.get("ausnahmen", [])
    abgaben = {}
    benutzt = set()   # jeder Verkauf erfuellt hoechstens eine Pflicht (frueheste zuerst)
    straf_offen = []
    bums_faelle = []
    for st in fertige:
        info = sti.get(st, {})
        st_start = utc(info["start"])
        frist = utc(frist_ueberschreiben[str(st)]) if str(st) in frist_ueberschreiben \
            else frist_berechnen(utc(info["letzter_anstoss"]), regel_frist)
        liste = []
        for m in spieltage[st]["manager"]:
            u = m["i"]
            if m["mdpl"] is not None and m["mdpl"] <= 3:
                stufe, top = "Platz %d am Spieltag" % m["mdpl"], 3
            elif m["mdp"] >= 1000:
                stufe, top = "1000+", 3
            elif m["mdp"] >= 800:
                stufe, top = "800+", 5
            else:
                continue
            elf = sorted(aufstellungen[st][u], key=lambda x: -(x["p"] or 0))
            if not elf:
                continue
            grenze = elf[min(top, len(elf)) - 1]["p"] or 0
            kandidaten = [x for x in elf if (x["p"] or 0) >= grenze]
            kids = {x["i"] for x in kandidaten}
            # Verkaeufe dieser Kandidaten ab Spieltagsbeginn
            verk = [t for t in alle_transfers if t["uid"] == u and t["art"] == "verkauf"
                    and t["pi"] in kids and t["dt"] >= st_start]
            markt = [t for t in verk if t["gegen"] == "Markt" and id(t) not in benutzt]
            an_manager = [t for t in verk if t["gegen"] != "Markt"]
            erledigt = markt[0] if markt else None
            if erledigt:
                benutzt.add(id(erledigt))
            ausnahme = next((a for a in ausnahmen if str(a.get("st")) == str(st)
                             and str(a.get("manager")) == u), None)
            # Strafe: je angefangenem Tag nach der Frist ein zusaetzlicher Verkauf aus der Startelf
            bezug = erledigt["dt"] if erledigt else jetzt
            strafe = 0
            if bezug > frist:
                strafe = int((bezug - frist).total_seconds() // 86400) + 1
            if ausnahme:
                strafe = 0
            if ausnahme:
                status = "ausnahme"
            elif erledigt and erledigt["dt"] <= frist:
                status = "erledigt"
            elif erledigt:
                status = "verspaetet"
            elif jetzt <= frist:
                status = "offen"
            else:
                status = "ueberfaellig"
            eintrag = {
                "i": u, "mdp": m["mdp"], "mdpl": m["mdpl"], "stufe": stufe, "top": top,
                "kandidaten": [{"i": x["i"], "n": x["n"], "p": x["p"],
                                "weg": next((("markt" if t["gegen"] == "Markt" else "manager")
                                             for t in verk if t["pi"] == x["i"]), None)}
                               for x in kandidaten],
                "abgegeben": {"i": erledigt["pi"], "n": spieler_name(erledigt["pi"]),
                              "dt": iso(erledigt["dt"]), "preis": erledigt["preis"]} if erledigt else None,
                "an_manager": [{"i": t["pi"], "n": spieler_name(t["pi"]), "an": namen.get(t["gegen"], t["gegen"]),
                                "dt": iso(t["dt"])} for t in an_manager],
                "status": status, "strafe": strafe,
                "strafe_erledigt": 0, "straf_verkaeufe": [],
                "ausnahme": ausnahme.get("grund") if ausnahme else None}
            liste.append(eintrag)
            straf_offen.append((eintrag, st, frist, {x["i"] for x in elf}))
            if erledigt:
                # behalten = die uebrigen Spieler der Auswahl (Top 3/5 inkl. Gleichstand)
                bums_faelle.append({"st": st, "u": u, "pi": erledigt["pi"], "dt": erledigt["dt"],
                                    "art": "Pflicht", "behalten": sorted(kids - {erledigt["pi"]})})
        liste.sort(key=lambda e: (e["mdpl"] or 99))
        abgaben[st] = {"frist": iso(frist), "liste": liste}

    # Strafverkaeufe erst danach zuordnen, damit sie keiner spaeteren Pflicht den Verkauf wegnehmen:
    # jeder Marktverkauf eines Spielers aus der damaligen Startelf nach der Frist, der noch frei ist.
    for eintrag, st, frist, elf_ids in straf_offen:
        if not eintrag["strafe"]:
            continue
        u = eintrag["i"]
        frei = [t for t in alle_transfers if t["uid"] == u and t["art"] == "verkauf"
                and t["gegen"] == "Markt" and t["pi"] in elf_ids and t["dt"] > frist
                and id(t) not in benutzt][:eintrag["strafe"]]
        benutzt.update(id(t) for t in frei)
        eintrag["strafe_erledigt"] = len(frei)
        eintrag["straf_verkaeufe"] = [{"n": spieler_name(t["pi"]), "dt": iso(t["dt"])} for t in frei]
        weg = {t["pi"] for t in frei} | ({eintrag["abgegeben"]["i"]} if eintrag["abgegeben"] else set())
        for t in frei:
            # behalten = die uebrige Startelf dieses Spieltags
            bums_faelle.append({"st": st, "u": u, "pi": t["pi"], "dt": t["dt"], "art": "Strafe",
                                "behalten": sorted(elf_ids - weg)})

    # ------------------------------------------------ Bumstabelle
    # Durchschnitt ueber ALLE Spieltage im Zeitraum; ohne Einsatz zaehlt der Spieltag mit 0.
    def einsatz(pid, st):
        e = (spieler.get(str(pid)) or {}).get("punkte", {}).get(str(st))
        return e["p"] if e else None

    def schnitt(summe, n):
        return round(summe / n) if n else None

    bums = []
    for f in bums_faelle:
        verlauf_pkt = []
        fenster = []
        zurueck = None
        for st in fertige:
            if utc(sti[st]["start"]) <= f["dt"]:
                continue
            elf_ids = {x["i"] for x in aufstellungen.get(st, {}).get(f["u"], [])}
            if f["pi"] in elf_ids:
                zurueck = st
                break
            fenster.append(st)
            p = einsatz(f["pi"], st)
            verlauf_pkt.append({"st": st, "p": p or 0, "ohne": p is None})
        # Vergleich: behaltene Spieler im selben Zeitraum, egal bei wem sie spielen
        beh = []
        for pid in f.get("behalten", []):
            werte = [einsatz(pid, st) or 0 for st in fenster]
            beh.append({"i": pid, "n": spieler_name(pid), "summe": sum(werte), "einsaetze": len(werte),
                        "schnitt": schnitt(sum(werte), len(werte))})
        summe = sum(x["p"] for x in verlauf_pkt)
        beh_summe = sum(x["summe"] for x in beh)
        beh_n = sum(x["einsaetze"] for x in beh)
        bums.append({"st": f["st"], "u": f["u"], "i": f["pi"], "n": spieler_name(f["pi"]),
                     "art": f["art"], "dt": iso(f["dt"]), "verlauf": verlauf_pkt,
                     "spieltage": len(fenster), "einsaetze": len(verlauf_pkt),
                     "summe": summe, "schnitt": schnitt(summe, len(verlauf_pkt)),
                     "behalten": beh, "beh_summe": beh_summe, "beh_einsaetze": beh_n,
                     "beh_schnitt": schnitt(beh_summe, beh_n), "zurueck": zurueck})
    bums.sort(key=lambda b: (-(b["schnitt"] or -9999), -b["summe"]))
    bums_tabelle = []
    for u in manager:
        eigene = [b for b in bums if b["u"] == u]
        n_weg = sum(b["einsaetze"] for b in eigene)
        n_beh = sum(b["beh_einsaetze"] for b in eigene)
        s_weg = sum(b["summe"] for b in eigene)
        s_beh = sum(b["beh_summe"] for b in eigene)
        z = {"i": u, "anzahl": len(eigene),
             "strafen": sum(1 for b in eigene if b["art"] == "Strafe"),
             "summe": s_weg, "einsaetze": n_weg, "schnitt": schnitt(s_weg, n_weg),
             "beh_einsaetze": n_beh, "beh_schnitt": schnitt(s_beh, n_beh),
             "bester": max(eigene, key=lambda b: b["summe"])["n"] if eigene else None}
        # positiv = Behaltene waren im Schnitt besser = richtig abgegeben
        z["bilanz"] = (z["beh_schnitt"] - z["schnitt"]) if z["schnitt"] is not None \
            and z["beh_schnitt"] is not None else None
        bums_tabelle.append(z)
    bums_tabelle.sort(key=lambda z: (z["bilanz"] is None, z["bilanz"] if z["bilanz"] is not None else 0,
                                     -z["summe"]))

    # ------------------------------------------------ Transfers und Bilanz
    kauf_offen = {}
    transfer_liste = []
    for t in alle_transfers:
        if t["uid"] not in manager:
            continue
        schluessel = (t["uid"], t["pi"])
        e = {"u": t["uid"], "i": t["pi"], "n": t["pn"] or spieler_name(t["pi"]), "tid": t["tid"],
             "art": t["art"], "preis": t["preis"], "dt": iso(t["dt"]),
             "gegen": "Markt" if t["gegen"] == "Markt" else namen.get(t["gegen"], t["gegen"])}
        if t["art"] == "kauf":
            kauf_offen[schluessel] = t["preis"]
        else:
            kp = kauf_offen.pop(schluessel, None)
            e["kaufpreis"] = kp
            e["gewinn"] = t["preis"] - kp if kp is not None else None
        transfer_liste.append(e)
    bilanz = []
    for u in manager:
        eig = [t for t in transfer_liste if t["u"] == u]
        offen_wert = []
        for p in kader.get(u, []):
            kp = kauf_offen.get((u, str(p["pi"])))
            if kp is None:
                kp = p.get("prc")
            offen_wert.append({"i": str(p["pi"]), "n": p.get("pn"), "mv": p.get("mv"),
                               "kaufpreis": kp, "diff": (p.get("mv") or 0) - kp if kp else None,
                               "pos": p.get("pos"), "tid": p.get("tid"), "p": p.get("p")})
        bilanz.append({
            "i": u,
            "kaeufe": sum(1 for t in eig if t["art"] == "kauf"),
            "verkaeufe": sum(1 for t in eig if t["art"] == "verkauf"),
            "ausgaben": sum(t["preis"] for t in eig if t["art"] == "kauf"),
            "einnahmen": sum(t["preis"] for t in eig if t["art"] == "verkauf"),
            "gewinn": sum(t["gewinn"] for t in eig if t.get("gewinn") is not None),
            "buchgewinn": sum(x["diff"] for x in offen_wert if x["diff"] is not None),
            "kader": sorted(offen_wert, key=lambda x: (x["pos"] or 9, -(x["mv"] or 0)))})
    bilanz.sort(key=lambda b: -(b["gewinn"] + b["buchgewinn"]))

    # ------------------------------------------------ Punktekorrekturen (Feed Typ 29)
    korrekturen = []
    for a in feed.values():
        if a.get("t") == 29:
            d = a.get("data") or {}
            korrekturen.append({"i": str(d.get("i")), "n": d.get("n"), "amt": d.get("amt"),
                                "dt": a.get("dt")})
    for k in cfg.get("korrekturen", []):
        korrekturen.append(k)
    korrekturen.sort(key=lambda k: k.get("dt") or "")

    # ------------------------------------------------ Manager-Statistik und Rekorde
    profile = {}
    alle_st_werte = []
    spieler_fuer = {}
    for u in manager:
        v = verlauf[u]
        werte = [(s, v["mdp"][s]) for s in fertige if s in v["mdp"]]
        alle_st_werte += [(p, s, u) for s, p in werte]
        for s in fertige:
            for x in aufstellungen.get(s, {}).get(u, []):
                k = (u, x["i"])
                spieler_fuer.setdefault(k, [0, 0, x["n"]])
                spieler_fuer[k][0] += x["p"] or 0
                spieler_fuer[k][1] += 1
        punkte_liste = [p for _, p in werte]
        n = len(punkte_liste)
        schnitt = sum(punkte_liste) / n if n else 0
        streuung = math.sqrt(sum((p - schnitt) ** 2 for p in punkte_liste) / n) if n else 0
        top_spieler = sorted([(sp[0], sp[1], sp[2], pid) for (uu, pid), sp in spieler_fuer.items()
                              if uu == u], reverse=True)[:5]
        profile[u] = {
            "schnitt": round(schnitt), "streuung": round(streuung),
            "bester": max(werte, key=lambda w: w[1]) if werte else None,
            "schlechtester": min(werte, key=lambda w: w[1]) if werte else None,
            "siege": sum(1 for s in fertige if v["mdpl"].get(s) == 1),
            "letzte": sum(1 for s in fertige if v["mdpl"].get(s) == len(spieltage[s]["manager"])),
            "ueber1000": sum(1 for _, p in werte if p >= 1000),
            "ueber800": sum(1 for _, p in werte if 800 <= p < 1000),
            "top3": sum(1 for s in fertige if (v["mdpl"].get(s) or 99) <= 3),
            "top_spieler": [{"n": t[2], "p": t[0], "einsaetze": t[1], "i": t[3]} for t in top_spieler]}

    rekorde = []
    if alle_st_werte:
        hoch = max(alle_st_werte)
        rekorde.append({"titel": "Höchste Spieltagspunkte", "wert": hoch[0],
                        "wer": [u for p, s, u in alle_st_werte if p == hoch[0]],
                        "st": [s for p, s, u in alle_st_werte if p == hoch[0]]})
        tief = min(alle_st_werte)
        rekorde.append({"titel": "Niedrigste Spieltagspunkte", "wert": tief[0],
                        "wer": [u for p, s, u in alle_st_werte if p == tief[0]],
                        "st": [s for p, s, u in alle_st_werte if p == tief[0]]})
    def rekord_aus_profil(titel, feld, einheit=""):
        if not profile:
            return
        w = max(p[feld] for p in profile.values())
        if w:
            rekorde.append({"titel": titel, "wert": w, "einheit": einheit,
                            "wer": [u for u, p in profile.items() if p[feld] == w]})
    rekord_aus_profil("Meiste Spieltagssiege", "siege")
    rekord_aus_profil("Meiste 1000er-Spieltage", "ueber1000")
    rekord_aus_profil("Höchster Schnitt", "schnitt", " Ø")
    konstant = min(profile.items(), key=lambda kv: kv[1]["streuung"]) if profile else None
    if konstant and fertige:
        rekorde.append({"titel": "Konstantester Manager", "wert": konstant[1]["streuung"],
                        "einheit": " Streuung", "wer": [konstant[0]]})
    # Einzelspieler-Rekord (aufgestellt)
    beste_leistung = None
    for s in fertige:
        for u, elf in aufstellungen.get(s, {}).items():
            for x in elf:
                if x["p"] is not None and (beste_leistung is None or x["p"] > beste_leistung[0]):
                    beste_leistung = (x["p"], s, u, x["n"])
    if beste_leistung:
        rekorde.append({"titel": "Beste Einzelleistung (aufgestellt)", "wert": beste_leistung[0],
                        "wer": [beste_leistung[2]], "st": [beste_leistung[1]], "spieler": beste_leistung[3]})
    meiste = max(bums_tabelle, key=lambda z: z["anzahl"]) if bums_tabelle else None
    if meiste and meiste["anzahl"]:
        rekorde.append({"titel": "Meiste Abgaben", "wert": meiste["anzahl"],
                        "wer": [z["i"] for z in bums_tabelle if z["anzahl"] == meiste["anzahl"]]})

    # ------------------------------------------------ Spieltagszusammenfassung + Vorschau
    zusammenfassung = None
    if fertige:
        s = fertige[-1]
        ms = sorted(spieltage[s]["manager"], key=lambda m: -m["mdp"])
        mvp = None
        for u, elf in aufstellungen[s].items():
            for x in elf:
                if x["p"] is not None and (mvp is None or x["p"] > mvp["p"]):
                    mvp = {"n": x["n"], "p": x["p"], "u": u}
        zusammenfassung = {
            "st": s, "sieger": ms[0]["i"], "sieger_p": ms[0]["mdp"],
            "letzter": ms[-1]["i"], "letzter_p": ms[-1]["mdp"],
            "schnitt": round(sum(m["mdp"] for m in ms) / len(ms)),
            "ueber1000": [m["i"] for m in ms if m["mdp"] >= 1000],
            "ueber800": [m["i"] for m in ms if 800 <= m["mdp"] < 1000],
            "mvp": mvp,
            "fuehrung": tabellen[s][0]["i"] if tabellen.get(s) else None}
    naechster = None
    for st in sorted(sti):
        if st > st_bis:
            break
        if not sti[st].get("begonnen"):
            naechster = {"st": st, "start": sti[st]["start"]}
            break

    ergebnis = {
        "erstellt": iso(jetzt),
        "liga": {"name": liga.get("name") or cfg["name"], "logo": liga.get("logo"),
                 "id": cfg["liga_id"], "saison": cfg.get("saison")},
        "regeln": cfg.get("regeln"), "abgaberegeln": cfg.get("abgabe"),
        "spieltage": {"von": cfg["spieltage"]["von"], "bis": st_bis, "fertig": fertige,
                      "laufend": laufend,
                      "termine": {st: sti[st]["start"] for st in sti if st <= st_bis}},
        "manager": manager,
        "verlauf": verlauf,
        "tabellen": tabellen,
        "aufstellungen": aufstellungen,
        "abgaben": abgaben,
        "bums": bums, "bums_tabelle": bums_tabelle,
        "transfers": transfer_liste, "bilanz": bilanz,
        "korrekturen": korrekturen,
        "profile": profile, "rekorde": rekorde,
        "zusammenfassung": zusammenfassung, "naechster": naechster,
        "vereine": {},
    }
    for s in spieler.values():
        if s.get("tid") and s.get("tn"):
            ergebnis["vereine"][s["tid"]] = s["tn"]
    return ergebnis


if __name__ == "__main__":
    e = auswerten()
    with open(os.path.join(DATEN, "auswertung.json"), "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1, default=str)
    print("Fertige Spieltage:", e["spieltage"]["fertig"])
    for st, a in sorted(e["abgaben"].items()):
        print("ST %s Frist %s: %s" % (st, a["frist"], ", ".join(
            "%s %s %s" % (e["manager"][x["i"]]["n"], x["stufe"], x["status"]) for x in a["liste"])))
