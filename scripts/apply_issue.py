#!/usr/bin/env python3
"""Wendet eine Watchlist-Aenderung aus einem GitHub-Issue an (vom Besitzer ausgeloest).
Issue-Text enthaelt JSON: {"add":[{"symbol":"NVDA","name":"Nvidia","sector":"Halbleiter/Hardware"}],"remove":["XYZ"]}
Symbole werden streng validiert und bei Yahoo geprueft. Schreibt watchlist.json und /tmp/summary.md."""
import json, os, re, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sectors import map_sector
import fetch_data as fd
ROOT = fd.ROOT
SYM_RE = re.compile(r"^[A-Za-z0-9^.=\-]{1,16}$")
MAX_ADD, MAX_TOTAL = 10, 80

def yahoo_search(sym):
    url = "https://query2.finance.yahoo.com/v1/finance/search?q=%s&quotesCount=6&newsCount=0" % urllib.parse.quote(sym)
    try:
        d = json.loads(fd.http_get(url, tries=2))
        for q in d.get("quotes", []):
            if q.get("symbol", "").upper() == sym.upper():
                return q
    except Exception:
        pass
    return {}

def main():
    body = os.environ.get("ISSUE_BODY", "")
    m = re.search(r"\{.*\}", body, re.S)
    lines = []
    if not m:
        open("/tmp/summary.md", "w").write("Kein JSON im Issue-Text gefunden. Nichts geaendert."); return
    try:
        req = json.loads(m.group(0))
    except Exception as e:
        open("/tmp/summary.md", "w").write("JSON nicht lesbar (%s). Nichts geaendert." % e); return
    path = os.path.join(ROOT, "watchlist.json")
    wl = json.load(open(path, encoding="utf-8"))
    have = {s["symbol"].upper(): s for s in wl["stocks"]}
    adds = req.get("add") or []
    rems = req.get("remove") or []
    changed = False
    for a in adds[:MAX_ADD]:
        if not isinstance(a, dict): continue
        sym = str(a.get("symbol", "")).strip()
        if not SYM_RE.match(sym):
            lines.append("- %r: ungueltiges Kuerzel, uebersprungen" % sym[:20]); continue
        if sym.upper() in have:
            lines.append("- %s: schon in der Liste" % sym); continue
        if len(wl["stocks"]) >= MAX_TOTAL:
            lines.append("- %s: Liste ist voll (%d)" % (sym, MAX_TOTAL)); continue
        try:
            res = fd.chart(sym, "1d", "15m"); meta = res["meta"]
            if meta.get("regularMarketPrice") is None: raise RuntimeError("kein Kurs")
        except Exception as e:
            lines.append("- %s: bei Yahoo nicht gefunden (%s), uebersprungen" % (sym, str(e)[:80])); continue
        info = yahoo_search(sym)
        name = str(a.get("name") or "").strip()[:60] or info.get("shortname") or meta.get("shortName") or sym
        name = re.sub(r"[\r\n\t]+", " ", name)
        sec = a.get("sector")
        if sec not in wl["sectors"]:
            sec = map_sector(info.get("sector"), info.get("industry"), info.get("quoteType") or meta.get("instrumentType"))
        etf = (info.get("quoteType") or meta.get("instrumentType") or "").upper() in ("ETF", "INDEX", "MUTUALFUND")
        st = {"symbol": sym, "name": name, "sector": sec, "q_de": name + (" ETF" if etf else " Aktie"), "q_en": name + (" ETF" if etf else " stock")}
        if etf: st["type"] = "etf"
        wl["stocks"].append(st); have[sym.upper()] = st; changed = True
        lines.append("- %s (%s, %s): hinzugefuegt, Kurs %s %s" % (sym, name, sec, meta.get("regularMarketPrice"), meta.get("currency")))
    for r in rems[:MAX_ADD * 3]:
        sym = str(r).strip()
        if not SYM_RE.match(sym): continue
        if sym.upper() in have:
            wl["stocks"] = [s for s in wl["stocks"] if s["symbol"].upper() != sym.upper()]; changed = True
            lines.append("- %s: entfernt" % sym)
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wl, f, ensure_ascii=False, indent=2); f.write("\n")
    open("/tmp/summary.md", "w").write("Ergebnis:\n" + ("\n".join(lines) if lines else "- keine Aenderung"))
    print("\n".join(lines))
    open("/tmp/changed", "w").write("1" if changed else "0")

main()
