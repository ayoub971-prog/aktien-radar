"""Analysten-Daten (Yahoo quoteSummary mit Cookie/Crumb) und extraktive Kurz-Zusammenfassung pro Aktie.
Nur Standardbibliothek, keine API-Schluessel. Nichts wird erfunden: fehlt etwas, bleibt es null."""
import json, re, time, urllib.request, urllib.parse, http.cookiejar
from datetime import datetime, timezone, timedelta
from quality import item_quality

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

class Yahoo:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.crumb = None
    def get(self, url, timeout=20):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.8"})
        with self.op.open(req, timeout=timeout) as r:
            return r.read()
    def login(self):
        for u in ("https://fc.yahoo.com", "https://finance.yahoo.com/"):
            try: self.get(u)
            except Exception: pass
        for host in ("query1", "query2"):
            try:
                c = self.get("https://%s.finance.yahoo.com/v1/test/getcrumb" % host).decode().strip()
                if c and "<" not in c and len(c) < 40:
                    self.crumb = c; return c
            except Exception as e:
                last = e
        raise RuntimeError("kein Crumb von Yahoo")
    def summary(self, sym):
        mods = "recommendationTrend,financialData,upgradeDowngradeHistory,calendarEvents"
        last = None
        for host in ("query2", "query1"):
            url = "https://%s.finance.yahoo.com/v10/finance/quoteSummary/%s?modules=%s&crumb=%s" % (
                host, urllib.parse.quote(sym, safe=""), mods, urllib.parse.quote(self.crumb or ""))
            for i in range(2):
                try:
                    d = json.loads(self.get(url))
                    res = (d.get("quoteSummary") or {}).get("result")
                    if res: return res[0]
                    last = RuntimeError(str((d.get("quoteSummary") or {}).get("error")))
                    break
                except Exception as e:
                    last = e
                    if getattr(e, "code", None) == 404: break
                    time.sleep(1 + i)
        raise RuntimeError(str(last))

def raw(x):
    if isinstance(x, dict): return x.get("raw")
    return x

def iso_ts(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

ACTION_DE = {"up": "hochgestuft", "down": "abgestuft", "init": "neu aufgenommen", "main": "bestätigt", "reit": "bestätigt"}
PT_DE = {"Raises": "Kursziel erhöht", "Lowers": "Kursziel gesenkt", "Maintains": "Kursziel bestätigt", "Announces": "Kursziel neu"}

def analyst_from(res, price, now):
    out = {}
    rt = ((res.get("recommendationTrend") or {}).get("trend") or [])
    cur = next((t for t in rt if t.get("period") == "0m"), rt[0] if rt else None)
    if cur:
        sb, b, h, s, ss = (int(cur.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
        if sb + b + h + s + ss > 0:
            out["consensus"] = {"kaufen": sb + b, "halten": h, "verkaufen": s + ss, "stark_kaufen": sb, "stark_verkaufen": ss}
    fd = res.get("financialData") or {}
    mean, hi, lo = raw(fd.get("targetMeanPrice")), raw(fd.get("targetHighPrice")), raw(fd.get("targetLowPrice"))
    n = raw(fd.get("numberOfAnalystOpinions"))
    if mean:
        cp = raw(fd.get("currentPrice")) or price   # gleiche Einheit wie die Kursziele
        out["target"] = {"mean": round(mean, 2), "high": hi and round(hi, 2), "low": lo and round(lo, 2),
                         "median": raw(fd.get("targetMedianPrice")), "analysts": n, 
                         "upside_pct": round((mean / cp - 1) * 100, 1) if cp else None}
    if fd.get("recommendationKey") and fd.get("recommendationKey") != "none":
        out["rec_key"] = fd.get("recommendationKey"); out["rec_mean"] = raw(fd.get("recommendationMean"))
    hist = ((res.get("upgradeDowngradeHistory") or {}).get("history") or [])
    cutoff = (now - timedelta(days=120)).timestamp()
    ch = []
    for x in sorted(hist, key=lambda x: x.get("epochGradeDate") or 0, reverse=True):
        t = x.get("epochGradeDate") or 0
        if t < cutoff or len(ch) >= 8: break
        ch.append({"date": iso_ts(t), "firm": x.get("firm"), "from": x.get("fromGrade") or None, "to": x.get("toGrade") or None,
                   "action": ACTION_DE.get(x.get("action"), x.get("action")), "pt_action": PT_DE.get(x.get("priceTargetAction")) or None,
                   "pt": x.get("currentPriceTarget") or None, "pt_prior": x.get("priorPriceTarget") or None})
    if ch: out["changes"] = ch
    ce = res.get("calendarEvents") or {}
    ed = [raw(e) for e in ((ce.get("earnings") or {}).get("earningsDate") or []) if raw(e)]
    ed = [e for e in ed if e >= (now - timedelta(days=1)).timestamp()]
    if ed: out["next_earnings"] = iso_ts(min(ed))
    return out

def fetch_analysts(stocks, quotes, now, log=print):
    y = Yahoo(); data, errs = {}, []
    try:
        y.login()
    except Exception as e:
        errs.append({"symbol": "*", "what": "analyst", "error": "Yahoo-Login: %s" % e})
        log("Analysten: Yahoo-Login fehlgeschlagen: %s" % e)
    for s in stocks:
        sym = s["symbol"]
        if sym.startswith("^") or sym.endswith("=F"):
            continue
        try:
            res = y.summary(sym)
            a = analyst_from(res, (quotes.get(sym) or {}).get("price"), now)
            data[sym] = a
            log("Analysten  %-10s %s" % (sym, ",".join(a.keys()) or "keine"))
        except Exception as e:
            errs.append({"symbol": sym, "what": "analyst", "error": str(e)[:200]})
            log("Analysten FEHLER %-10s %s" % (sym, e))
        time.sleep(0.3)
    return data, errs

# ---------------- Zusammenfassung ----------------
ANALYST_RE = re.compile(r"\bupgrades?\b|\bdowngrades?\b|hochgestuft|abgestuft|herabgestuft|heraufgestuft|kursziel|price target|"
                        r"\boutperform\b|\bunderperform\b|\boverweight\b|\bunderweight\b|\bstuft\b|\brating\b|\bbuy rating\b|initiat", re.I)
THEMES = [("Quartalszahlen", r"quartal|\bearnings\b|results|\bumsatz\b|revenue|\bq[1-4]\b|zahlen"),
          ("Analysten", ANALYST_RE.pattern),
          ("Übernahme/Deals", r"übernahme|übernimmt|\bacquir|merger|takeover|\bdeal\b|partnerschaft|partnership|auftrag|contract"),
          ("Prognose", r"prognose|ausblick|guidance|forecast|outlook"),
          ("Recht/Regulierung", r"klage|lawsuit|\bsues?\b|kartell|antitrust|ermittlung|investigation|regulator|aufsicht|\bsec\b"),
          ("Zölle/Handel", r"\bzoll|zölle|tariff|export|sanktion|sanction|china"),
          ("Produkte/KI", r"\bki\b|\bai\b|launch|lanciert|chip|produkt|product|modell|model"),
          ("Dividende/Rückkauf", r"dividend|rückkauf|buyback|repurchase"),
          ("Personal", r"\bceo\b|chef|rücktritt|resign|steps down|ernennt|appoints?")]
THEMES = [(n, re.compile(p, re.I)) for n, p in THEMES]
STOP = set("the a an of to in on for and or is are with as at by from its it this that der die das und in im zu den von mit für auf ist ein eine aktie stock shares".split())

def toks(t):
    return set(w for w in re.findall(r"[a-zà-ÿ0-9]+", t.lower()) if w not in STOP and len(w) > 2)

GENERIC = {"holding", "holdings", "group", "technology", "markets", "platforms", "electronics", "energy", "inc", "corp",
           "taiwan", "applied", "bloom", "siemens", "aerospace", "vernova", "materials", "the", "aktie", "stock"}
def relevance_re(stock):
    """Regex: Titel muss die Firma nennen (sonst ist die Meldung nur per Suchtreffer zugeordnet)."""
    if stock.get("type") in ("index", "etf"):
        if "gold" in (stock.get("name") or "").lower(): return re.compile(r"\bgold", re.I)
        return None
    keys = set()
    name = (stock.get("name") or "").strip()
    if name: keys.add(re.escape(name))
    words = re.findall(r"[A-Za-z0-9.&-]+", name)
    if words and len(words[0]) >= 3 and words[0].lower() not in GENERIC: keys.add(re.escape(words[0]))
    if len(words) >= 2: keys.add(re.escape(words[0] + " " + words[1]))
    q = (stock.get("q_de") or "").split()
    if q and len(q[0]) >= 3 and q[0].lower() not in GENERIC: keys.add(re.escape(q[0]))
    base = stock["symbol"].split(".")[0]
    if base.isalpha() and len(base) >= 3: keys.add(re.escape(base))
    return re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(keys, key=len, reverse=True)) + r")(?![a-z])", re.I)

def summarize(sym, items, now, analyst=None, stock=None, currency=None):
    nowt = now.timestamp()
    mine = []
    rel = relevance_re(stock) if stock else None
    for i in items:
        if sym not in (i.get("symbols") or []): continue
        if rel and not rel.search(i["title"]): continue
        q = i.get("q", item_quality(i))
        if q <= 0: continue
        try: t = datetime.strptime(i["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except Exception: continue
        age_h = max(0.0, (nowt - t) / 3600)
        if age_h > 24 * 7: continue
        # Rang: Qualitaet zaehlt stark, Aktualitaet faellt ueber ~2 Tage ab
        score = q * 1.0 + 2.0 / (1 + age_h / 18.0)
        if ANALYST_RE.search(i["title"]): score += 0.4
        mine.append((score, age_h, i))
    mine.sort(key=lambda x: -x[0])
    picked, seen = [], []
    for score, age_h, i in mine:
        tk = toks(i["title"])
        if not tk: continue
        if any(len(tk & s) / float(len(tk | s)) > 0.45 for s in seen): continue
        seen.append(tk); picked.append(i)
        if len(picked) >= 4: break
    picked.sort(key=lambda i: i["published"], reverse=True)
    recent = [x for x in mine if x[1] <= 48]
    themes = {}
    for _, _, i in recent:
        for n, rx in THEMES:
            if rx.search(i["title"]): themes[n] = themes.get(n, 0) + 1
    top_t = [n for n, c in sorted(themes.items(), key=lambda kv: -kv[1]) if c >= 1][:3]
    lines = []
    if recent:
        good = sum(1 for x in recent if (x[2].get("q") or 0) >= 3)
        s = ("1 Meldung" if len(recent) == 1 else "%d Meldungen" % len(recent)) + " zur Firma in den letzten 48 Std."
        if good: s += ", davon %d aus Top-Quellen" % good
        if top_t: s = s.rstrip(".") + ". Themen: " + ", ".join(top_t) + "."
        lines.append(s if s.endswith(".") else s + ".")
    elif mine:
        lines.append("Keine neuen Meldungen in den letzten 48 Std., wichtigste der letzten 7 Tage:")
    else:
        lines.append("Keine Meldungen zur Firma aus seriösen Quellen in den letzten 7 Tagen.")
    a = analyst or {}
    c = a.get("consensus")
    if c:
        tot = c["kaufen"] + c["halten"] + c["verkaufen"]
        s = "Analysten: %d× Kaufen, %d× Halten, %d× Verkaufen" % (c["kaufen"], c["halten"], c["verkaufen"])
        tg = a.get("target")
        if tg and tg.get("upside_pct") is not None:
            s += "; Ø Kursziel %s %s (%s%.1f %% zum Kurs)" % (fmt(tg["mean"]), currency or "", "+" if tg["upside_pct"] >= 0 else "", tg["upside_pct"])
        lines.append(s + ".")
    bullets = [{"title": i["title"], "source": i["source"], "published": i["published"], "link": i["link"], "q": i.get("q")} for i in picked]
    return {"text": lines, "bullets": bullets, "themes": top_t}

def fmt(x):
    return ("%.2f" % x).rstrip("0").rstrip(".") if x is not None else "-"

def actor(rel, title):
    """True, wenn die Firma selbst der Analyst ist (z.B. 'UBS downgrades Pearson')."""
    if not rel: return False
    for m in rel.finditer(title):
        after = title[m.end():m.end() + 30].lower(); before = title[max(0, m.start() - 8):m.start()].lower()
        if re.match(r"\s*(analysts?\s+)?(upgrades?|downgrades?|raises|cuts|lifts|lowers|stuft|initiates?|reiterates?|maintains|erhöht|senkt|sees|says|bleibt)\b", after) or re.search(r"(from|von|by|bei)\s*$", before):
            continue
        return False
    return True

def analyst_news(sym, items, stock=None, limit=5):
    out = []
    rel = relevance_re(stock) if stock else None
    for i in items:
        if sym in (i.get("symbols") or []) and (i.get("q") or 0) >= 2 and ANALYST_RE.search(i["title"]) and (not rel or rel.search(i["title"])) and not actor(rel, i["title"]):
            out.append({"title": i["title"], "source": i["source"], "published": i["published"], "link": i["link"]})
            if len(out) >= limit: break
    return out
