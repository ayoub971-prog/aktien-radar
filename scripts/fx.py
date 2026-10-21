"""Wechselkurse -> USD. Quelle: Frankfurter (EZB-Referenzkurse, ohne Schluessel), Ersatz: Yahoo FX. Letzter Stand in data/fx.json."""
import json, os, urllib.request
UA = {"User-Agent": "Mozilla/5.0 aktien-radar"}
def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r: return json.loads(r.read())
def load(path, currencies, log=print):
    try: old = json.load(open(path, encoding="utf-8"))
    except Exception: old = {}
    doc = None
    try:
        d = _get("https://api.frankfurter.dev/v1/latest?base=USD")
        doc = {"date": d["date"], "source": "EZB-Referenzkurse (Frankfurter)", "per_usd": {k: float(v) for k, v in d["rates"].items()}}
    except Exception as e: log("FX Frankfurter Fehler: %s" % str(e)[:100])
    need = [c for c in currencies if c and c.upper() not in ("USD", "GBP") or c == "GBP"]
    if doc is None or any(c.upper() not in doc["per_usd"] and c.upper() != "USD" for c in need if c != "GBp"):
        doc = doc or {"date": None, "source": "Yahoo Finance FX", "per_usd": {}}
        for c in set(x.upper() for x in need):
            if c in doc["per_usd"] or c == "USD": continue
            try:
                m = _get("https://query1.finance.yahoo.com/v8/finance/chart/USD%s=X?range=1d&interval=1d" % c)["chart"]["result"][0]["meta"]
                doc["per_usd"][c] = float(m["regularMarketPrice"]); doc["date"] = doc["date"] or __import__("time").strftime("%Y-%m-%d")
                doc["source"] += " + Yahoo FX"
            except Exception as e: log("FX Yahoo Fehler %s: %s" % (c, str(e)[:80]))
    if not doc.get("per_usd") and old.get("per_usd"): doc = old; log("FX: nutze letzten Stand %s" % old.get("date"))
    for c, v in (old.get("per_usd") or {}).items(): doc["per_usd"].setdefault(c, v)
    with open(path, "w", encoding="utf-8") as f: json.dump(doc, f, ensure_ascii=False)
    return doc
def factor(fx, cur):
    """Faktor lokal -> USD (None = unbekannt)."""
    if not cur or cur == "USD": return 1.0
    div = 1.0
    if cur in ("GBp", "GBX"): cur, div = "GBP", 100.0
    if cur == "ZAc": cur, div = "ZAR", 100.0
    r = (fx.get("per_usd") or {}).get(cur.upper())
    return (1.0 / r / div) if r else None
def convert_quote(q, fx):
    if not q or q.get("currency") in (None, "USD"): return q
    f = factor(fx, q["currency"])
    if f is None: return q
    q = dict(q); q["orig_currency"] = q["currency"]; q["fx"] = f; q["currency"] = "USD"
    for k in ("price", "prev_close", "change", "high52", "low52", "open", "day_high", "day_low"):
        if isinstance(q.get(k), (int, float)): q[k] = round(q[k] * f, 6)
    for k in ("spark_day", "spark_5d", "spark"):
        if isinstance(q.get(k), list): q[k] = [round(x * f, 6) if isinstance(x, (int, float)) else x for x in q[k]]
    return q
def convert_analyst(a, cur, fx, local_price=None):
    if not a or a.get("usd") or not cur: return a
    f = factor(fx, cur)
    if f is None: return a
    a = dict(a); t = a.get("target")
    if isinstance(t, dict):
        t = dict(t)
        for k in ("mean", "high", "low", "median", "current"):
            if isinstance(t.get(k), (int, float)): t[k] = round(t[k] * f, 4)
        a["target"] = t
    if isinstance(a.get("changes"), list) and local_price:
        import math
        ch = []
        for c in a["changes"]:
            c = dict(c); pt = c.get("pt")
            if isinstance(pt, (int, float)) and pt > 0:
                # Kursziele aus der Analysten-Historie: oft schon in USD (z. B. ADR). Naeher am lokalen Kurs -> umrechnen.
                if abs(math.log(pt / local_price)) < abs(math.log(pt / (local_price * f))):
                    c["pt"] = round(pt * f, 2)
                    if isinstance(c.get("pt_prior"), (int, float)): c["pt_prior"] = round(c["pt_prior"] * f, 2)
            ch.append(c)
        a["changes"] = ch
    a["usd"] = True; a["orig_currency"] = cur
    return a
