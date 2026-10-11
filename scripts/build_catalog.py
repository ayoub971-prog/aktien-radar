#!/usr/bin/env python3
"""Baut data/catalog.json (Suchindex fuer 'Aktie hinzufuegen') aus den Wikipedia-Liste S&P 500
plus der eigenen Watchlist. Quelle: Wikipedia (GICS-Sektoren). Ohne Wikipedia bleibt nur die Watchlist."""
import json, os, re, sys, html, urllib.request, urllib.parse
from html.parser import HTMLParser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sectors import map_sector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "aktien-radar/1.0 (https://github.com/ayoub971-prog/aktien-radar)"

def wiki_html(page):
    url = "https://en.wikipedia.org/w/api.php?action=parse&format=json&prop=text&page=" + urllib.parse.quote(page)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=40))["parse"]["text"]["*"]

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables = []; self.t = None; self.row = None; self.cell = None
    def handle_starttag(self, tag, a):
        if tag == "table": self.t = []
        elif tag == "tr" and self.t is not None: self.row = []
        elif tag in ("td", "th") and self.row is not None: self.cell = []
    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", html.unescape("".join(self.cell))).strip()); self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.t is not None: self.t.append(self.row)
            self.row = None
        elif tag == "table" and self.t is not None:
            self.tables.append(self.t); self.t = None
    def handle_data(self, d):
        if self.cell is not None: self.cell.append(d)

def find_table(page, need):
    p = Tables(); p.feed(wiki_html(page))
    for t in p.tables:
        if t and all(any(n.lower() in h.lower() for h in t[0]) for n in need):
            return t
    return []

def col(header, name):
    for i, h in enumerate(header):
        if name.lower() in h.lower(): return i
    return None

def yahoo_sym(s):
    return s.strip().replace(".", "-")

def main():
    cat = {}
    for page, need in (("List_of_S&P_500_companies", ["Symbol", "Security", "GICS Sector"]),):
        try:
            t = find_table(page, need)
            h = t[0]
            si = col(h, "Symbol") if col(h, "Symbol") is not None else col(h, "Ticker")
            ni = col(h, "Security") if col(h, "Security") is not None else col(h, "Company")
            gi = col(h, "GICS Sector"); ii = col(h, "Sub-Industry")
            n = 0
            for r in t[1:]:
                if len(r) <= max(si, ni, gi): continue
                sym = yahoo_sym(r[si]); name = r[ni]
                if not re.match(r"^[A-Z0-9\-]{1,10}$", sym) or not name: continue
                sec = map_sector(r[gi], r[ii] if ii is not None and ii < len(r) else "")
                cat.setdefault(sym, {"s": sym, "n": name, "sec": sec}); n += 1
            print(page, n, "Eintraege")
        except Exception as e:
            print("WARNUNG", page, e, file=sys.stderr)
    wl = json.load(open(os.path.join(ROOT, "watchlist.json"), encoding="utf-8"))
    for s in wl["stocks"]:
        cat[s["symbol"]] = {"s": s["symbol"], "n": s["name"], "sec": s["sector"]}
    out = sorted(cat.values(), key=lambda x: x["n"].lower())
    if len(out) <= len(wl["stocks"]):
        print("Katalog nur aus Watchlist (Wikipedia nicht erreichbar?)", file=sys.stderr)
    with open(os.path.join(ROOT, "data", "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "Wikipedia (S&P 500) + Watchlist", "items": out}, f, ensure_ascii=False, separators=(",", ":"))
    print("catalog.json:", len(out))
main()
