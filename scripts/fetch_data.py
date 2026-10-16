#!/usr/bin/env python3
"""Holt Kurse (Yahoo Finance chart API) und Nachrichten (Yahoo-RSS, Google-News-RSS)
fuer alle Aktien aus watchlist.json und schreibt data/quotes.json und data/news.json.
Nur Python-Standardbibliothek. Keine erfundenen Daten: Was nicht geholt werden kann, wird als Fehler vermerkt."""
import json, os, re, sys, time, html, hashlib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quality import item_quality
import insights, official, translate, ai_summary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NOW = datetime.now(timezone.utc)
KEEP_DAYS = 14
MAX_NEWS = 3000

def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def http_get(url, timeout=25, tries=3, accept=None):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept or "*/*", "Accept-Language": "en-US,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            code = getattr(e, "code", None)
            if code in (400, 401, 403, 404):
                break
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("%s: %s" % (type(last).__name__, last))

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def decimate(vals, n=60):
    if len(vals) <= n:
        return vals
    step = (len(vals) - 1) / float(n - 1)
    return [vals[int(round(i * step))] for i in range(n)]

def rnd(x, d=4):
    return None if x is None else round(float(x), d)

# ---------------- Kurse ----------------
def chart(symbol, rng, interval):
    q = urllib.parse.quote(symbol, safe="")
    last = None
    for host in ("query1", "query2"):
        url = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s&includePrePost=false" % (host, q, rng, interval)
        try:
            d = json.loads(http_get(url, tries=2))
            res = d["chart"]["result"]
            if res:
                return res[0]
            last = RuntimeError(str(d["chart"].get("error")))
        except Exception as e:
            last = e
    raise last

def closes(res):
    try:
        c = res["indicators"]["quote"][0]["close"]
        ts = res.get("timestamp") or []
        return [(t, v) for t, v in zip(ts, c) if v is not None]
    except Exception:
        return []

def fetch_quote(stock):
    sym = stock["symbol"]
    r1 = chart(sym, "1d", "15m")
    m = r1["meta"]
    price = m.get("regularMarketPrice")
    prev = m.get("chartPreviousClose")
    if prev is None:
        prev = m.get("previousClose")
    if price is None:
        raise RuntimeError("kein Kurs in der Antwort")
    day = closes(r1)
    spark5 = []
    try:
        r5 = chart(sym, "5d", "60m")
        spark5 = [round(v, 4) for _, v in closes(r5)]
    except Exception:
        pass
    chg = (price - prev) if prev not in (None, 0) else None
    pct = (chg / prev * 100.0) if chg is not None else None
    mt = m.get("regularMarketTime")
    return {
        "symbol": sym,
        "name": stock.get("name") or m.get("shortName") or sym,
        "long_name": m.get("longName") or m.get("shortName"),
        "currency": m.get("currency"),
        "exchange": m.get("fullExchangeName") or m.get("exchangeName"),
        "price": rnd(price),
        "prev_close": rnd(prev),
        "change": rnd(chg),
        "change_pct": rnd(pct, 3),
        "market_time": iso(datetime.fromtimestamp(mt, timezone.utc)) if mt else None,
        "high52": rnd(m.get("fiftyTwoWeekHigh")),
        "low52": rnd(m.get("fiftyTwoWeekLow")),
        "spark_day": [round(v, 4) for v in decimate([v for _, v in day], 60)],
        "spark_5d": decimate(spark5, 60),
        "fetched_at": iso(NOW),
        "stale": False,
    }

# ---------------- Nachrichten ----------------
def strip_tags(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def parse_rss(data, default_source):
    items = []
    root = ET.fromstring(data)
    for it in root.iter("item"):
        title = strip_tags(it.findtext("title") or "")
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None and src_el.text else default_source
        if not title or not link or not pub:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        # Google News haengt " - Quelle" an den Titel
        if source and default_source == "Google News" and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        items.append({"title": title, "link": link, "source": source or default_source, "published": iso(dt)})
    return items

def yahoo_rss(symbol):
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US" % urllib.parse.quote(symbol, safe="")
    return parse_rss(http_get(url, tries=2), "Yahoo Finance")

def gnews(query, lang, when):
    hl, gl, ceid = ("de", "CH", "CH:de") if lang == "de" else ("en-US", "US", "US:en")
    q = urllib.parse.quote("%s when:%s" % (query, when))
    url = "https://news.google.com/rss/search?q=%s&hl=%s&gl=%s&ceid=%s" % (q, hl, gl, ceid)
    return parse_rss(http_get(url, tries=2), "Google News")

def norm_key(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())[:90]

def news_for_stock(stock):
    """liefert (items, fehlerliste)"""
    sym = stock["symbol"]
    out, errs = [], []
    def add(items, via, limit):
        items = sorted(items, key=lambda x: x["published"], reverse=True)[:limit]
        for i in items:
            i = dict(i); i["via"] = via; i["symbols"] = [sym]; out.append(i)
    try:
        add(yahoo_rss(sym), "yahoo", 15)
    except Exception as e:
        errs.append("yahoo-rss: %s" % e)
    for lang, key in (("de", "q_de"), ("en", "q_en")):
        q = stock.get(key) or ("%s %s" % (stock.get("name", sym), "Aktie" if lang == "de" else "stock"))
        try:
            add(gnews(q, lang, "2d"), "gnews-" + lang, 12)
        except Exception as e:
            errs.append("gnews-%s: %s" % (lang, e))
    if len(out) < 8:   # wenige frische Meldungen: auf 14 Tage erweitern
        for lang, key in (("de", "q_de"), ("en", "q_en")):
            q = stock.get(key) or stock.get("name", sym)
            try:
                add(gnews(q, lang, "14d"), "gnews-" + lang, 8)
            except Exception as e:
                errs.append("gnews14-%s: %s" % (lang, e))
    return out, errs

def news_for_topic(t):
    out, errs = [], []
    for lang, key in (("de", "q_de"), ("en", "q_en")):
        got = 0
        for when in ("2d", "14d"):
            try:
                items = sorted(gnews(t[key], lang, when), key=lambda x: x["published"], reverse=True)[:12]
            except Exception as e:
                errs.append("%s/%s/%s: %s" % (t["topic"], lang, when, e)); break
            for i in items:
                i = dict(i); i["via"] = "gnews-" + lang; i["symbols"] = []; i["topic"] = t["topic"]; out.append(i)
            got += len(items)
            if got >= 5:
                break
    return out, errs

def merge_news(batches, old_items):
    by = {}
    def put(i):
        k = norm_key(i["title"])
        if not k:
            return
        cur = by.get(k)
        if cur is None:
            by[k] = i
            return
        cur["symbols"] = sorted(set(cur.get("symbols", [])) | set(i.get("symbols", [])))
        if i.get("official") and not cur.get("official"):
            for k in ("official", "form", "desc", "title_de"):
                if i.get(k): cur[k] = i[k]
            cur["source"], cur["link"] = i["source"], i["link"]
        if i.get("topic") and not cur.get("topic"):
            cur["topic"] = i["topic"]
        if i["published"] > cur["published"]:
            cur["published"] = i["published"]
        if cur.get("source") in (None, "", "Google News", "Yahoo Finance") and i.get("source") not in (None, "", "Google News"):
            cur["source"], cur["link"] = i["source"], i["link"]
        vs = set(cur.get("via", "").split(",")) | set(i.get("via", "").split(","))
        cur["via"] = ",".join(sorted(v for v in vs if v))
    for i in old_items:
        put(i)
    for b in batches:
        for i in b:
            put(i)
    for v in list(by.values()):   # Quellenfilter: Clickbait/unserioese Quellen raus
        v["q"] = 3 if v.get("official") else item_quality(v)
    by = {k: v for k, v in by.items() if v["q"] > 0}
    cutoff = iso(NOW - timedelta(days=KEEP_DAYS))
    cut_sec = iso(NOW - timedelta(days=90))
    future = iso(NOW + timedelta(hours=2))
    # Offizielle Mitteilungen (SEC 90 Tage, Firmen KEEP_DAYS) immer behalten, nur normale Meldungen begrenzen
    off = [v for v in by.values() if v.get("official") and v["published"] <= future and v["published"] >= (cut_sec if v.get("official") == "sec" else cutoff)]
    res = [v for v in by.values() if not v.get("official") and v["published"] >= cutoff and v["published"] <= future]
    res.sort(key=lambda x: x["published"], reverse=True)
    res = res[:MAX_NEWS] + off
    res.sort(key=lambda x: x["published"], reverse=True)
    for v in res:
        v["id"] = hashlib.sha1(norm_key(v["title"]).encode()).hexdigest()[:12]
    return res

def main():
    wl = load_json(os.path.join(ROOT, "watchlist.json"), None)
    if not wl:
        print("watchlist.json fehlt oder ist ungueltig", file=sys.stderr); sys.exit(1)
    stocks = wl["stocks"]
    topics = wl.get("market_topics", [])
    qpath = os.path.join(ROOT, "data", "quotes.json")
    npath = os.path.join(ROOT, "data", "news.json")
    oldq = load_json(qpath, {}).get("quotes", {})
    oldn = load_json(npath, {})
    errors = []
    quotes = {}

    def q_job(s):
        try:
            return s["symbol"], fetch_quote(s), None
        except Exception as e:
            return s["symbol"], None, str(e)
    with ThreadPoolExecutor(max_workers=5) as ex:
        for sym, q, err in ex.map(q_job, stocks):
            if q:
                quotes[sym] = q
                print("Kurs OK    %-10s %s %s" % (sym, q["price"], q["currency"]))
            else:
                print("Kurs FEHLER %-10s %s" % (sym, err))
                errors.append({"symbol": sym, "what": "quote", "error": err})
                if sym in oldq:
                    o = dict(oldq[sym]); o["stale"] = True; o["error"] = err; quotes[sym] = o
    batches = []
    def n_job(s):
        items, errs = news_for_stock(s)
        return s["symbol"], items, errs
    with ThreadPoolExecutor(max_workers=4) as ex:
        for sym, items, errs in ex.map(n_job, stocks):
            batches.append(items)
            print("News       %-10s %3d Meldungen%s" % (sym, len(items), ("  Fehler: " + "; ".join(errs)) if errs else ""))
            for e in errs:
                errors.append({"symbol": sym, "what": "news", "error": e})
    mbatches = []
    for t in topics:
        items, errs = news_for_topic(t)
        mbatches.append(items)
        print("Marktweit  %-18s %3d Meldungen%s" % (t["topic"], len(items), ("  Fehler: " + "; ".join(errs)) if errs else ""))
        for e in errs:
            errors.append({"symbol": "markt:" + t["topic"], "what": "news", "error": e})
    old_items = oldn.get("items", []) if isinstance(oldn, dict) else []
    sec, e1 = official.sec_items(stocks, NOW)
    ir, e2 = official.ir_items(stocks, gnews)
    for e in e1 + e2: errors.append(e)
    print("Offiziell: %d SEC, %d Firmen-Mitteilungen" % (len(sec), len(ir)))
    items = merge_news(batches + mbatches + [sec, ir], old_items)
    tr = translate.translate_all([i["title"] for i in items if not i.get("official") == "sec"], os.path.join(ROOT, "data", "translations.json"))
    for i in items:
        if i.get("official") != "sec":
            de = tr.get(i["title"])
            if de: i["title_de"] = de
            else: i.pop("title_de", None)
    ok_news = sum(1 for b in batches if b) + sum(1 for b in mbatches if b)
    if ok_news == 0 and old_items:
        print("Keine neuen Nachrichten erhalten, behalte alte Daten", file=sys.stderr)
    qdoc = {"generated_at": iso(NOW), "source": "Yahoo Finance (chart API v8), Kurse koennen bis zu 15 Min verzoegert sein", "quotes": quotes, "errors": [e for e in errors if e["what"] == "quote"]}
    ndoc = {"generated_at": iso(NOW), "source": "Yahoo Finance RSS, Google News RSS", "items": items, "errors": [e for e in errors if e["what"] in ("news", "official")]}
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    def dump(path, doc):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    dump(qpath, qdoc); dump(npath, ndoc)
    # Analysten + Kurz-Zusammenfassung
    ipath = os.path.join(ROOT, "data", "insights.json")
    oldi = load_json(ipath, {}).get("stocks", {})
    adata, aerrs = insights.fetch_analysts(stocks, quotes, NOW)
    ist = {}
    for s in stocks:
        sym = s["symbol"]
        a = adata.get(sym)
        a_at = iso(NOW) if a is not None else None
        if a is None and sym in oldi and oldi[sym].get("analyst"):
            a = oldi[sym]["analyst"]; a_at = oldi[sym].get("analyst_at")   # letzter bekannter Stand, mit Datum
        ist[sym] = {"summary": insights.summarize(sym, items, NOW, a, s, (quotes.get(sym) or {}).get("currency")), "analyst": a or {}, "analyst_at": a_at,
                    "analyst_news": insights.analyst_news(sym, items, s)}
    dump(ipath, {"generated_at": iso(NOW), "source": "Yahoo Finance quoteSummary (Analysten), Nachrichten extraktiv zusammengefasst", "stocks": ist, "errors": aerrs})
    try:
        ai_summary.run(stocks, items, ist, insights.relevance_re, os.path.join(ROOT, "data", "ai.json"), NOW)
    except Exception as e:
        print("KI-Zusammenfassung FEHLER (App nutzt extraktive Zusammenfassung): %s" % str(e)[:200], file=sys.stderr)
    print("Analysten: %d/%d mit Daten" % (sum(1 for v in ist.values() if v["analyst"].get("consensus") or v["analyst"].get("target")), len(stocks)))
    print("Fertig: %d/%d Kurse, %d Meldungen, %d Fehler" % (len([q for q in quotes.values() if not q.get("stale")]), len(stocks), len(items), len(errors)))
    if len(quotes) == 0:
        sys.exit(2)

if __name__ == "__main__":
    main()
