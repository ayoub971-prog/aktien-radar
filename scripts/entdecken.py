"""Entdecken: bis 30 auffaellige Aktien aus S&P 500 + Nasdaq-100 + Watchlist (auch nicht auf der Liste).
Quellen: Wikipedia (Indexlisten), Yahoo Finance (Kurse, Kursziele, Hoch-/Abstufungen, Quartalszahlen, Schlagzeilen),
optional Google Gemini Gratis-Kontingent (nur fuer kurze Begruendung bei 'Frische Zahlen'; faellt bei Quota weg).
Nichts wird erfunden: fehlende Werte bleiben leer. Alle Betraege in USD. Ergebnis: data/entdecken.json"""
import json, os, re, sys, time, html, urllib.parse
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from insights import Yahoo, raw, grade, ACTION_DE
import ai_summary

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "entdecken.json")
N = 30
NOW = datetime.now(timezone.utc)

def wiki_tickers(y, page):
    t = y.get("https://en.wikipedia.org/wiki/" + page).decode("utf-8", "ignore")
    best = []
    for tb in re.findall(r'<table[^>]*wikitable.*?</table>', t, re.S):
        out = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)[1:]:
            txt = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)[:2]]
            tk = next((x for x in txt if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", x)), None)
            if tk: out.append(tk.replace(".", "-"))
        if len(out) > len(best): best = out
    out = best
    return out

def chunks(l, n):
    for i in range(0, len(l), n): yield l[i:i + n]

def quotes(y, syms):
    res = {}
    for c in chunks(syms, 50):
        u = "https://query1.finance.yahoo.com/v7/finance/quote?symbols=%s&crumb=%s" % (",".join(c), urllib.parse.quote(y.crumb))
        try:
            for r in json.loads(y.get(u))["quoteResponse"]["result"]: res[r["symbol"]] = r
        except Exception as e: print("quote-Fehler", e)
        time.sleep(0.3)
    return res

def spark(y, syms):
    res = {}
    for c in chunks(syms, 20):
        u = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=%s&range=3mo&interval=1d" % ",".join(c)
        try:
            for r in json.loads(y.get(u))["spark"]["result"]:
                rr = (r.get("response") or [{}])[0]
                ts = rr.get("timestamp") or []; cl = ((rr.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
                pts = [(t, v) for t, v in zip(ts, cl) if v]
                if len(pts) > 15: res[r["symbol"]] = pts
        except Exception as e: print("spark-Fehler", e)
        time.sleep(0.3)
    return res

def perf(pts, days):
    last_t, last = pts[-1]; cut = last_t - days * 86400
    base = next((v for t, v in pts if t >= cut), None)
    return round((last / base - 1) * 100, 1) if base else None

def summary(y, sym):
    u = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/%s?modules=financialData,upgradeDowngradeHistory,earningsHistory&crumb=%s" % (
        urllib.parse.quote(sym), urllib.parse.quote(y.crumb))
    for i in range(2):
        try:
            r = json.loads(y.get(u))["quoteSummary"]["result"]
            return r[0] if r else {}
        except Exception as e:
            if getattr(e, "code", None) == 404: return {}
            time.sleep(1.5)
    return {}

def d_ch(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y")
def pct(x): return ("+" if x > 0 else "") + ("%.1f" % x).replace(".", ",") + " %"
def usd(x): return ("%.2f" % x) + " USD"

def headlines(y, sym, n=4):
    try:
        t = y.get("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US" % sym).decode("utf-8", "ignore")
        return [html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", x)).strip() for x in re.findall(r"<item>.*?<title>(.*?)</title>", t, re.S)][:n]
    except Exception: return []

def main():
    old = {}
    try: old = json.load(open(OUT))
    except Exception: pass
    y = Yahoo(); y.login()
    wl = json.load(open(os.path.join(ROOT, "watchlist.json")))["stocks"]
    mine = {s["symbol"] for s in wl}
    fx = (json.load(open(os.path.join(ROOT, "data", "fx.json"))).get("per_usd") or {})
    uni = []
    for p in ("List_of_S%26P_500_companies", "Nasdaq-100"):
        try: uni += wiki_tickers(y, p)
        except Exception as e: print("Wikipedia-Fehler", p, e)
    uni += [s["symbol"] for s in wl if not s["symbol"].startswith("^") and not s["symbol"].endswith("=F")]
    uni = list(dict.fromkeys(uni)); print("Universum", len(uni))
    if len(uni) < 100: raise SystemExit("Universum zu klein, alter Stand bleibt")
    q = quotes(y, uni); sp = spark(y, list(q)); print("Kurse", len(q), "Verlauf", len(sp))
    rows = {}
    for s, r in q.items():
        if r.get("quoteType") not in ("EQUITY", None): continue
        cur, price = r.get("currency"), r.get("regularMarketPrice")
        if not price or not cur: continue
        k = 1.0 if cur == "USD" else (1 / fx[cur] if fx.get(cur) else None)
        if cur in ("GBp", "GBX"): k = 1 / fx["GBP"] / 100 if fx.get("GBP") else None
        if not k: continue
        pts = sp.get(s)
        rows[s] = {"symbol": s, "name": r.get("longName") or r.get("shortName") or s, "price_usd": round(price * k, 2), "fx": k,
                   "mine": s in mine, "m1": perf(pts, 30) if pts else None, "m3": perf(pts, 90) if pts else None, "mcap": r.get("marketCap")}
    for i, s in enumerate(rows):
        a = summary(y, s); r = rows[s]
        fd = a.get("financialData") or {}
        mean, cp, n = raw(fd.get("targetMeanPrice")), raw(fd.get("currentPrice")), raw(fd.get("numberOfAnalystOpinions"))
        if mean and cp and n: r.update(target_usd=round(mean * r["fx"], 2), upside=round((mean / cp - 1) * 100, 1), analysts=n)
        ch = []
        for x in sorted(((a.get("upgradeDowngradeHistory") or {}).get("history") or []), key=lambda x: -(x.get("epochGradeDate") or 0)):
            if (x.get("epochGradeDate") or 0) < (NOW - timedelta(days=21)).timestamp(): break
            if x.get("action") in ("up", "down"): ch.append({"t": x["epochGradeDate"], "firm": x.get("firm"), "a": x["action"], "to": grade(x.get("toGrade"))})
        r["changes"] = ch[:3]
        eh = sorted(((a.get("earningsHistory") or {}).get("history") or []), key=lambda h: raw(h.get("quarter")) or 0)
        if eh:
            h = eh[-1]; qd, act, est, sur = raw(h.get("quarter")), raw(h.get("epsActual")), raw(h.get("epsEstimate")), raw(h.get("surprisePercent"))
            # Quartalsende liegt vor der Publikation; Zahlen sind "frisch", wenn Yahoo die letzte Publikation <= 21 Tage meldet
            et = q[s].get("earningsTimestamp")
            if act is not None and est is not None and et and qd and 0 < et - qd < 75 * 86400 and NOW.timestamp() - 21 * 86400 <= et <= NOW.timestamp():
                r["earn"] = {"t": et, "act": act, "est": est, "sur": round(sur * 100, 1) if sur is not None else None, "cur": q[s].get("financialCurrency") or q[s].get("currency")}
        if i % 50 == 0: print("Analysen", i, "/", len(rows))
        time.sleep(0.25)
    R = list(rows.values())
    def item(r, metric, reason):
        return {"symbol": r["symbol"], "name": r["name"], "price_usd": r["price_usd"], "mine": r["mine"], "metric": metric, "reason": reason}
    def chtxt(r):
        return " ".join("%s %s (%s)." % (c["firm"], "stuft hoch" + (" auf " + c["to"] if c["to"] else "") if c["a"] == "up" else "stuft ab" + (" auf " + c["to"] if c["to"] else ""), d_ch(c["t"])) for c in r["changes"][:2])
    pot = sorted([r for r in R if r.get("upside") is not None and r.get("analysts", 0) >= 8], key=lambda r: -(r["upside"] + 3 * sum(1 if c["a"] == "up" else -1 for c in r["changes"])))[:N]
    L_pot = [item(r, pct(r["upside"]) + " bis Kursziel", "Ø Kursziel von %d Analysten: %s. %s" % (r["analysts"], usd(r["target_usd"]), chtxt(r))) for r in pot]
    gro = sorted([r for r in R if r.get("m3") is not None], key=lambda r: -r["m3"])[:N]
    L_gro = [item(r, pct(r["m3"]) + " in 3 Mt.", "Kurs in 3 Monaten %s, im letzten Monat %s." % (pct(r["m3"]), pct(r["m1"]) if r.get("m1") is not None else "–")) for r in gro]
    zr = sorted([r for r in R if r.get("earn")], key=lambda r: -abs(r["earn"]["sur"] or 0))[:N]
    L_z = []
    for r in zr:
        e = r["earn"]; bm = "über" if e["act"] > e["est"] else ("unter" if e["act"] < e["est"] else "genau bei")
        L_z.append(dict(item(r, ("Gewinn " + pct(e["sur"]) + " vs. Erwartung") if e["sur"] is not None else "Zahlen", "Zahlen vom %s: Gewinn je Aktie %.2f %s, %s der Erwartung (%.2f)." % (d_ch(e["t"]), e["act"], e["cur"], bm, e["est"])), beat=e["act"] >= e["est"], _h=None))
    neg = []
    for r in R:
        sc, why = 0, []
        if r.get("m1") is not None and r["m1"] < -8: sc += -r["m1"]; why.append("Kurs im letzten Monat %s." % pct(r["m1"]))
        e = r.get("earn")
        if e and e["act"] < e["est"]: sc += 10 + min(30, abs(e["sur"] or 0)); why.append("Zahlen vom %s unter Erwartung (%.2f statt %.2f)." % (d_ch(e["t"]), e["act"], e["est"]))
        dn = [c for c in r["changes"] if c["a"] == "down"]
        if dn: sc += 8 * len(dn); why.append(" ".join("%s stuft ab%s (%s)." % (c["firm"], " auf " + c["to"] if c["to"] else "", d_ch(c["t"])) for c in dn[:2]))
        if sc: neg.append((sc, r, " ".join(why)))
    neg.sort(key=lambda x: -x[0])
    L_neg = [item(r, pct(r["m1"]) + " in 1 Mt." if r.get("m1") is not None else "auffällig", w) for _, r, w in neg[:N]]
    # optionale KI: kurze Begruendung zu Zahlen/Produkten aus Schlagzeilen (1 Aufruf)
    ai_note = None; key = os.environ.get("GEMINI_API_KEY")
    if key and L_z:
        inp = {x["symbol"]: {"name": x["name"], "fakten": x["reason"], "schlagzeilen": headlines(y, x["symbol"])} for x in L_z[:20]}
        prompt = ("Schreibe pro Aktie 1-2 kurze, neutrale Sätze auf Deutsch (Schweiz, kein ß) zu den Quartalszahlen und, falls in den Schlagzeilen genannt, "
                  "zu neuen Produkten/Aufträgen mit Potenzial. Nur Fakten aus den Daten, nichts erfinden, keine Empfehlung. "
                  "Antworte als JSON {\"SYMBOL\": \"Text\"}.\nDaten: " + json.dumps(inp, ensure_ascii=False))
        for m in ai_summary.MODELS:
            try:
                out, _ = ai_summary.call(m, prompt, key)
                for x in L_z:
                    t = out.get(x["symbol"])
                    if isinstance(t, str) and 20 < len(t) < 400: x["ai"] = t.replace("ß", "ss").strip()
                ai_note = m; break
            except Exception as ex:
                print("KI", m, ai_summary.err_text(ex))
        if not ai_note: print("KI übersprungen (Kontingent/Fehler) – nur Zahlen")
    for x in L_z: x.pop("_h", None)
    doc = {"generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "universe": len(rows), "ai_model": ai_note,
           "sources": ["Wikipedia (S&P 500, Nasdaq-100)", "Yahoo Finance"] + (["Google Gemini (Kurztexte Frische Zahlen)"] if ai_note else []),
           "lists": {"potenzial": L_pot, "wachstum": L_gro, "zahlen": L_z, "gegenteil": L_neg}}
    json.dump(doc, open(OUT, "w"), ensure_ascii=False, indent=0)
    print("OK", {k: len(v) for k, v in doc["lists"].items()})

if __name__ == "__main__": main()
