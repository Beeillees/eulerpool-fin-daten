# Depot-Daten

Holt jeden Morgen Kennzahlen, Kursziele, Analysten, Termine, Insider und Leerverkäufe von
[Eulerpool](https://eulerpool.com) für deine Depot- und Beobachtungstitel nach Home Assistant.

## Voraussetzungen
- Mosquitto-Broker (App) und die MQTT-Integration.
- Eulerpool-Schlüssel: `eulerpool_token:` in der `secrets.yaml` **oder** im Feld **token**.

## Welche Titel?
Alle Sensoren mit dem Label **beobachtungsliste** oder **depot_einzelaktie**. Neues Label setzen genügt,
beim nächsten Lauf ist der Titel dabei. Nicht börsennotierte Titel (Anthropic, SpaceX) und Rohstoff-ETCs
werden übersprungen.

## Einstellungen
| Option | Bedeutung |
|---|---|
| `token` | Eulerpool-Schlüssel; leer = aus `secrets.yaml` |
| `uhrzeit` | tägliche Abrufzeit (Standard 05:00) |
| `monatslimit` | dein Eulerpool-Limit pro Monat, nur für die Anzeige (Standard 100000) |
| `isin_zuordnung` | falls ein Titel falsch erkannt wird: `SYMBOL=ISIN`, z. B. `HEI.DE=DE0006047004` |

## Entitäten
- `sensor.depotdaten_<titel>`: Abstand zum Kursziel in %, alle Kennzahlen als Attribute
- `sensor.depotdaten_status`, `sensor.depotdaten_letzter_lauf`
- `sensor.depotdaten_abrufe_heute`, `sensor.depotdaten_abrufe_monat`, `sensor.depotdaten_abrufe_rest`
- `button.depotdaten_aktualisieren`

## Verbrauch
Etwa 12 Abrufe pro Titel und Tag (deutsche Titel mit veraltetem Kursziel 3–4 mehr).
