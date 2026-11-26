# Changelog

## 0.3.0
- Depot-Tagebuch `/config/www/depot-daten/verlauf.json` (im Browser `/local/depot-daten/verlauf.json`):
  Tageskurse aller Depot-Positionen (aus Easy Stock/Yahoo, wächst dauerhaft weiter), einmalige
  Nachfüllung älterer Tageskurse über Eulerpool (nur wenn sie sich mit Yahoo decken), Bestände je Tag.
- Erkennt Käufe/Verkäufe (Sparplan, Abgleich, Handeingabe) alle 10 Minuten an den Stückzahl-/Einstand-
  Helfern und bucht sie mit Datum. Die Depot-Karte nutzt das für Verlauf und Kaufjahre.
- Sensor `sensor.depotdaten_verlauf` (Anzahl gespeicherter Tageskurse, Buchungen, Nachfüllung).
- Zugriff auf `/config` jetzt mit Schreibrecht (nur für `www/depot-daten/`).

## 0.2.3
- KGV mit Sondereffekt erkennen (ein Quartal > 1,8 × Median der letzten vier) und als „(Sondereffekt)“ kennzeichnen.
- Attribut `eps_quartale`: die letzten acht Quartalsgewinne zum Nachprüfen.

## 0.2.1
- KGV: doppelt geführte Quartale werden nicht mehr doppelt gezählt (Termine mind. 60 Tage auseinander).
- Alter Analysten-Konsens und veraltetes Kursziel werden in der Zeile als „alt MM/JJ“ markiert.
- US-ADR deutscher Titel über ihr Kürzel (BAYRY, HDELY, …) finden.
- Zurücksetzdatum des Eulerpool-Limits lesbar.

## 0.2.0
- Grundversion: findet alle Sensoren mit Label `beobachtungsliste` oder `depot_einzelaktie` selbst,
  holt täglich (Standard 05:00) Kursziel, Analysten-Konsens, Hoch-/Herabstufungen, Gewinnschätzungen,
  Quartalstermine, Kursverlauf, Dividenden, Splits, Insider (US/BaFin) und Leerverkäufe (US).
- KGV und erwartetes KGV selbst gerechnet (Eulerpool liefert dort 0).
- Kursziel = Median (robuster gegen Ausreißer); bei veraltetem Ziel deutscher Titel: Abstand der US-ADR.
- Plausibilitätsprüfung mit Hinweisen (veraltet, Split, Kursabweichung, Ziel sehr weit weg).
- Sensoren per MQTT: `sensor.depotdaten_<titel>`, Status, Abrufe heute/Monat/übrig, letzter Lauf,
  Knopf „Jetzt aktualisieren“.
- Schreibt die Kennzahlen-Zeile in `input_text.watchlist_<titel>_kennzahlen`.

## 0.1.0
- Prüfmodus: alle Eulerpool-Abrufe für ein paar Titel einmal aufrufen.
