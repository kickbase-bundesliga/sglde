# SGLDE 4.1 HR 26/27

Tabelle, Abgabeliste, Bumstabelle, Managerprofile, Transfers und Aufstellungen der Kickbase-Liga SGLDE 4.1 (Liga-ID 4112495, Hinrunde ST 1-14).

Webseite: https://kickbase-bundesliga.github.io/sglde/

## Online (GitHub)
- Workflow **SGLDE** (Reiter "Actions") laeuft taeglich frueh morgens und dienstags kurz nach der Abgabefrist (22 Uhr): holt neue Daten, speichert sie im Repository und veroeffentlicht die Webseite.
- Manuell: Actions -> SGLDE -> Run workflow. Haken "Nur Webseite neu bauen" = ohne Kickbase-Abruf.
- Aenderungen an `config/` oder `scripts/` (auch direkt auf github.com) bauen die Webseite automatisch neu.
- Secrets (Settings -> Secrets and variables -> Actions): `PRIVAT_EMAIL`, `PRIVAT_PASSWORT` (privater Account, Mitglied der Liga).

## Lokal
- Vor jeder Arbeit in GitHub Desktop **Fetch/Pull**, danach **Commit + Push**. Die Daten holt online die Automatik - lokal nur Config/Skripte aendern.
- Zugangsdaten fuer lokale Tests: `config/privat.txt` (Zeile 1 E-Mail, Zeile 2 Passwort). Wird nie hochgeladen.
- `start.bat` = Daten sammeln + Webseite bauen (nur fuer Tests; danach die Daten nicht committen, sondern verwerfen). Vorschau als Einzeldatei: `liga/vorschau.html`.

## Einstellungen (`config/sglde.json`)
- `spieltage.bis`: letzter Spieltag der Hinrunde (14).
- `ausnahmen`: Sonderfaelle bei den Abgaben, z. B. `{"st": 5, "manager": "<Manager-ID>", "name": "...", "grund": "..."}`.
- `abgabe.frist_je_st`: abweichende Frist fuer einen Spieltag, z. B. `{"9": "2026-11-11T21:00:00Z"}` (UTC).
- `admin_ids`: Accounts, die nicht gewertet werden (leer = alle zaehlen).
- `transfers_ab`: Transfers davor (Vorsaison) werden ignoriert.

## Daten (`liga/daten/`)
`st_NN.json` Wertung je Spieltag, `spieler.json` Punkte je Spieler und Spieltag, `scorer.json` Tore/Assists der aufgestellten Spieler, `transfers.json`, `aktivitaeten.json` (Feed wird ergaenzt, Kickbase haelt nur ca. 3 Wochen), `kader.json`, `liga.json`, `spielplan.json`, `stand.json`.
