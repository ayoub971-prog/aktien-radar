# Aktien-Radar

Statische PWA (GitHub Pages) mit Kursen und Nachrichten zur eigenen Watchlist. Deutsch (de-CH), mobile zuerst.

Live: https://ayoub971-prog.github.io/aktien-radar/

## Aufbau
- `watchlist.json`: Standardliste (Kuerzel, Name, Sektor, Suchbegriffe) und Marktthemen.
- `scripts/fetch_data.py`: holt Kurse (Yahoo Finance chart API) und Nachrichten (Yahoo-RSS, Google-News-RSS de/en), schreibt `data/quotes.json` und `data/news.json`.
- `.github/workflows/update.yml`: laeuft per Cron (werktags tagsueber alle 20 Min, sonst stuendlich) und manuell; committet die JSON-Dateien.
- `.github/workflows/watchlist-issue.yml`: traegt Aktien ein/aus, wenn der Repo-Besitzer ein Issue mit Titel `Watchlist: ...` und JSON im Text anlegt (die App erzeugt dieses Issue per Knopf).
- `scripts/build_catalog.py`: baut `data/catalog.json` (Suchindex S&P 500 aus Wikipedia plus Watchlist).
- `app.js`, `index.html`, `sw.js`: die App (Service Worker: Huelle aus Cache, `data/*.json` zuerst Netz, sonst letzter Stand).

## Grenzen
Kurse koennen bis zu 15 Minuten verzoegert sein. GitHub-Cron kann 10 bis 30 Minuten Verzug haben. Etiketten sind reine Stichwort-Treffer, keine Prognose, keine Anlageberatung.
