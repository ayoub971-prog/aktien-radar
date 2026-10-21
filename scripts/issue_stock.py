#!/usr/bin/env python3
"""Aktie per GitHub-Issue hinzufuegen/entfernen (nur Besitzer, Pruefung im Workflow).
Titel: "add: Apple" / "add: AAPL" / "remove: NVDA". Schreibt watchlist.json, data/added.json,
/tmp/summary.md (deutscher Kommentar), /tmp/changed (1/0) und /tmp/state (ok/mehrdeutig/fehler)."""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import add_stock as ad
from sectors import map_sector
import fetch_data as fd
ROOT = fd.ROOT
WL = os.path.join(ROOT, "watchlist.json")
def done(msg, changed=False, state="ok"):
    print(msg)
    open("/tmp/summary.md", "w").write(msg); open("/tmp/changed", "w").write("1" if changed else "0"); open("/tmp/state", "w").write(state)
PRIMARY = ["NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "GER", "EBS", "LSE", "HKG", "KSC", "KOE", "JPX", "TYO", "PAR", "AMS", "MIL", "MCE", "STO", "CPH", "HEL", "OSL", "TOR", "ASX", "TAI", "SHH", "SHZ", "BRU", "VIE", "LIS", "DUB"]
SECOND = {"FRA", "STU", "MUN", "BER", "DUS", "HAM", "HAN", "CXE", "AQS", "IOB", "NEO"}
def main_listing(g):
    """Hauptboerse bevorzugen: echte Heimatboerse vor Zweitplaetzen (Frankfurt, Cboe Europe ...) und OTC."""
    def rank(c):
        e = c.get("exchange") or ""
        if e in PRIMARY: r = 0
        elif e in ad.OTC: r = 3
        elif e in SECOND: r = 2
        else: r = 1
        if re.match(r"^\d[A-Z]", c["symbol"]) and e in ("MIL", "MCE", "EBS"): r = 2   # Zweitnotiz wie 1MBG.MI
        return (r, -float(c.get("score") or 0))
    return sorted(g, key=rank)[0]
def label(c): return "**%s** – %s (%s)" % (c["symbol"], re.sub(r"\s+", " ", c.get("longname") or c.get("shortname") or "").strip(), c.get("exchDisp") or c.get("exchange") or "")
def save(wl):
    with open(WL, "w", encoding="utf-8") as f: json.dump(wl, f, ensure_ascii=False, indent=2); f.write("\n")
def add(q):
    if not ad.Q_RE.match(q): return done("❌ Ungültige Eingabe: „%s“. Bitte nur Name oder Kürzel." % q[:40], state="fehler")
    cands = [c for c in ad.search(q) if (c.get("quoteType") or "").upper() in ad.OK_TYPES and ad.SYM_RE.match(c.get("symbol", ""))]
    if not cands: return done("❌ Nichts gefunden für „%s“. Bitte den genauen Namen oder das Kürzel (z. B. AAPL) nehmen." % q, state="fehler")
    nq, qs = ad.norm(q), q.upper().replace(" ", "")
    exact = [c for c in cands if c["symbol"].upper() == qs]
    if exact: c = exact[0]
    else:
        fn = lambda c: ad.norm(c.get("shortname") or c.get("longname")).replace("-", " ")
        eq = [x for x in cands if (x.get("quoteType") or "").upper() == "EQUITY"]
        if eq and "etf" not in q.lower(): cands = eq
        nq = nq.replace("-", " ")
        sc = lambda c: float(c.get("score") or 0)
        groups = {}
        for x in cands: groups.setdefault(fn(x), []).append(x)
        named = groups.get(nq)
        order = sorted(groups.items(), key=lambda g: -max(sc(x) for x in g[1]))
        if not named:
            if len(order) > 1 and max(sc(x) for x in order[1][1]) >= 0.5 * max(sc(x) for x in order[0][1]):
                top = [main_listing(g) for _, g in order[:3]]
                return done("🤔 „%s“ ist nicht eindeutig. Meintest du:\n\n%s\n\nBitte das Issue bearbeiten: Titel auf `add: KÜRZEL` ändern (z. B. `add: %s`) und wieder öffnen („Reopen“)." %
                            (q, "\n".join("%d. %s" % (i + 1, label(x)) for i, x in enumerate(top)), top[0]["symbol"]), state="mehrdeutig")
            named = order[0][1]
        c = main_listing(named)
    sym = c["symbol"]
    wl = json.load(open(WL, encoding="utf-8")); have = {s["symbol"].upper() for s in wl["stocks"]}
    same = [s for s in wl["stocks"] if ad.norm(s.get("name")) and ad.norm(s.get("name")) == ad.norm(c.get("shortname") or c.get("longname"))]
    if same and sym.upper() not in have:
        return done("ℹ️ **%s** ist schon in deiner Liste (als %s)." % (same[0]["name"], same[0]["symbol"]), False)
    try:
        meta = fd.chart(sym, "1d", "15m")["meta"]
        if meta.get("regularMarketPrice") is None: raise RuntimeError("kein Kurs")
    except Exception as e: return done("❌ %s: kein Kurs bei Yahoo (%s)." % (sym, str(e)[:80]), state="fehler")
    name = re.sub(r"\s+", " ", (c.get("shortname") or c.get("longname") or meta.get("shortName") or sym)).strip()
    name = re.sub(r"(\s[A-Z])+$", "", name).strip()
    if name.isupper() and len(name) > 4: name = " ".join(w if len(w) <= 3 else w.capitalize() for w in name.split())
    name = name[:60]; changed = False
    if sym.upper() not in have:
        if len(wl["stocks"]) >= ad.MAX_TOTAL: return done("❌ Die Liste ist voll (%d Aktien)." % ad.MAX_TOTAL, state="fehler")
        etf = (c.get("quoteType") or "").upper() == "ETF"
        st = {"symbol": sym, "name": name, "sector": map_sector(c.get("sector"), c.get("industry"), c.get("quoteType")),
              "q_de": name + (" ETF" if etf else " Aktie"), "q_en": name + (" ETF" if etf else " stock")}
        if etf: st["type"] = "etf"
        wl["stocks"].append(st); save(wl); changed = True
    ap = os.path.join(ROOT, "data", "added.json")
    try: a = json.load(open(ap, encoding="utf-8"))
    except Exception: a = {"items": []}
    a["items"] = [i for i in a.get("items", []) if i.get("symbol") != sym][-29:] + [{"symbol": sym, "name": name, "at": int(time.time())}]
    with open(ap, "w", encoding="utf-8") as f: json.dump(a, f, ensure_ascii=False, indent=1); f.write("\n")
    if not changed: return done("ℹ️ **%s** (%s) ist schon in deiner Liste." % (name, sym), True)
    done("✅ **%s** (%s, %s) wurde hinzugefügt.\n\nKurse, Nachrichten und Zusammenfassung erscheinen in ca. 5–10 Minuten in der App (einmal neu laden)." % (name, sym, c.get("exchDisp") or c.get("exchange")), True)
def remove(q):
    wl = json.load(open(WL, encoding="utf-8")); qs = q.upper().replace(" ", ""); nq = ad.norm(q)
    hit = [s for s in wl["stocks"] if s["symbol"].upper() == qs] or [s for s in wl["stocks"] if ad.norm(s.get("name")) == nq]
    if not hit: return done("❌ „%s“ ist nicht in deiner Liste. Nichts geändert." % q, state="fehler")
    if len(hit) > 1: return done("🤔 Mehrere Treffer: %s. Bitte mit dem Kürzel: `remove: %s`." % (", ".join(s["symbol"] for s in hit), hit[0]["symbol"]), state="mehrdeutig")
    s = hit[0]; wl["stocks"] = [x for x in wl["stocks"] if x is not s]; save(wl)
    done("🗑 **%s** (%s) wurde aus der Liste entfernt. In ca. 5 Minuten ist sie auch in der App weg (einmal neu laden)." % (s.get("name"), s["symbol"]), True)
def main():
    t = re.sub(r"\s+", " ", os.environ.get("ISSUE_TITLE", "")).strip()
    m = re.match(r"^(add|remove|hinzufügen|entfernen)\s*:\s*(.+)$", t, re.I)
    if not m: return done("❌ Titel nicht erkannt. Bitte `add: Name` oder `remove: KÜRZEL`.", state="fehler")
    (add if m.group(1).lower() in ("add", "hinzufügen") else remove)(m.group(2).strip())
if __name__ == "__main__": main()
