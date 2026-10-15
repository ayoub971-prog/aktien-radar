#!/usr/bin/env python3
"""Fuegt eine Aktie per Name oder Kuerzel hinzu (repository_dispatch 'add-stock', iPhone-Kurzbefehl).
Eingabe: env QUERY. Loest per Yahoo-Suche auf, prueft streng (nur Aktien/ETFs mit Kurs), schreibt watchlist.json
und data/added.json (damit die App die Aktie automatisch einblendet)."""
import json, os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sectors import map_sector
import fetch_data as fd
ROOT = fd.ROOT
Q_RE = re.compile(r"^[A-Za-z0-9ÄÖÜäöüéèàç^.=&' \-]{1,40}$")
SYM_RE = re.compile(r"^[A-Za-z0-9^.=\-]{1,16}$")
MAX_TOTAL = 80
OK_TYPES = ("EQUITY", "ETF")

def out(msg, changed=False):
    print(msg); open("/tmp/summary.md", "w").write(msg); open("/tmp/changed", "w").write("1" if changed else "0")

def search(q):
    url = "https://query2.finance.yahoo.com/v1/finance/search?q=%s&quotesCount=10&newsCount=0" % urllib.parse.quote(q)
    try: return json.loads(fd.http_get(url, tries=3)).get("quotes", [])
    except Exception as e: print("Suche fehlgeschlagen:", e); return []

def main():
    q = re.sub(r"\s+", " ", os.environ.get("QUERY", "")).strip()
    if not Q_RE.match(q): return out("Ungültige Eingabe: %r" % q[:40])
    cands = [c for c in search(q) if (c.get("quoteType") or "").upper() in OK_TYPES and SYM_RE.match(c.get("symbol", ""))]
    exact = [c for c in cands if c["symbol"].upper() == q.upper().replace(" ", "")]
    if exact: c = exact[0]
    elif cands: c = cands[0]  # Yahoo sortiert nach Relevanz (Hauptbörse zuerst)
    else: return out("Nichts gefunden für %r." % q)
    sym = c["symbol"]
    path = os.path.join(ROOT, "watchlist.json"); wl = json.load(open(path, encoding="utf-8"))
    have = {s["symbol"].upper() for s in wl["stocks"]}
    try:
        meta = fd.chart(sym, "1d", "15m")["meta"]
        if meta.get("regularMarketPrice") is None: raise RuntimeError("kein Kurs")
    except Exception as e: return out("%s: kein Kurs bei Yahoo (%s)." % (sym, str(e)[:80]))
    name = re.sub(r"[\r\n\t]+", " ", (c.get("shortname") or c.get("longname") or meta.get("shortName") or sym))[:60]
    changed = False
    if sym.upper() not in have:
        if len(wl["stocks"]) >= MAX_TOTAL: return out("Liste ist voll (%d)." % MAX_TOTAL)
        sec = map_sector(c.get("sector"), c.get("industry"), c.get("quoteType"))
        etf = (c.get("quoteType") or "").upper() == "ETF"
        st = {"symbol": sym, "name": name, "sector": sec, "q_de": name + (" ETF" if etf else " Aktie"), "q_en": name + (" ETF" if etf else " stock")}
        if etf: st["type"] = "etf"
        wl["stocks"].append(st); changed = True
        with open(path, "w", encoding="utf-8") as f: json.dump(wl, f, ensure_ascii=False, indent=2); f.write("\n")
    ap = os.path.join(ROOT, "data", "added.json")
    try: ad = json.load(open(ap, encoding="utf-8"))
    except Exception: ad = {"items": []}
    ad["items"] = [i for i in ad.get("items", []) if i.get("symbol") != sym][-29:] + [{"symbol": sym, "name": name, "at": int(time.time())}]
    with open(ap, "w", encoding="utf-8") as f: json.dump(ad, f, ensure_ascii=False, indent=1); f.write("\n")
    out("%s (%s): %s, Kurs %s %s" % (sym, name, "hinzugefügt" if changed else "schon in der Liste", meta.get("regularMarketPrice"), meta.get("currency")), True)

main()
