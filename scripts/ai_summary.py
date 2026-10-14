"""Neutrale, journalistische KI-Zusammenfassung pro Aktie mit Google Gemini (Gratis-Kontingent).
Nur Standardbibliothek. Schluessel aus env GEMINI_API_KEY (wird nie ausgegeben).
Regeneriert nur, wenn sich die Eingabe (Meldungen/Analysten) geaendert hat; Ergebnisse in data/ai.json gecacht.
Bei Fehlern/Quota bleibt der letzte Stand stehen, die App zeigt sonst die extraktive Zusammenfassung."""
import json, os, re, time, hashlib, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

API = "https://generativelanguage.googleapis.com/v1beta"
# Bevorzugte Gratis-Modelle (laut ai.google.dev/pricing "Free of charge" im Free Tier), erstes verfuegbares gewinnt
MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash"]
MAX_CALLS = int(os.environ.get("AI_MAX_CALLS", "12"))     # pro Lauf (Lauf alle 20 Min)
MIN_AGE_H = float(os.environ.get("AI_MIN_AGE_H", "2"))    # fruehestens nach x Std neu, auch wenn neue Meldungen
SLEEP_S = 6                                               # ~10 Anfragen/Min, unter dem Free-RPM

# Kurzbeschreibungen bekannter Quellen (fuer Modell und App)
SOURCES = {
    "reuters": "internationale Nachrichtenagentur", "bloomberg": "US-Finanznachrichtendienst", "cnbc": "US-Wirtschaftssender",
    "wall street journal": "US-Wirtschaftszeitung", "wsj": "US-Wirtschaftszeitung", "financial times": "britische Wirtschaftszeitung",
    "barron's": "US-Finanzmagazin", "marketwatch": "US-Finanznachrichtenportal", "handelsblatt": "deutsche Wirtschaftszeitung",
    "nzz": "Schweizer Tageszeitung", "finanz und wirtschaft": "Schweizer Finanzzeitung", "handelszeitung": "Schweizer Wirtschaftszeitung",
    "cash": "Schweizer Finanzportal", "awp": "Schweizer Finanznachrichtenagentur", "dpa": "deutsche Nachrichtenagentur",
    "associated press": "US-Nachrichtenagentur", "welt": "deutsche Tageszeitung", "spiegel": "deutsches Nachrichtenmagazin",
    "faz": "deutsche Tageszeitung", "frankfurter allgemeine": "deutsche Tageszeitung", "nikkei": "japanische Wirtschaftszeitung",
    "the globe and mail": "kanadische Tageszeitung", "morningstar": "Fondsanalyse- und Researchhaus", "investor's business daily": "US-Börsenzeitung",
    "the economist": "britisches Wirtschaftsmagazin", "forbes": "US-Wirtschaftsmagazin", "fortune": "US-Wirtschaftsmagazin",
    "yahoo finanzen": "Finanzportal, bündelt Meldungen verschiedener Anbieter", "yahoo": "Yahoo Finance, Finanzportal, bündelt Meldungen und Analystenbewertungen",
    "finanzen.ch": "Schweizer Finanzportal", "finanzen.net": "deutsches Finanzportal", "finanzen.at": "österreichisches Finanzportal",
    "tradingview": "Chart- und Börsenplattform", "investing.com": "Finanzportal", "wallstreet online": "deutsches Börsenportal",
    "wallstreet-online": "deutsches Börsenportal", "seeking alpha": "US-Plattform mit Anlegerbeiträgen", "marketscreener": "Finanzportal",
    "aol": "Nachrichtenportal, übernimmt Agenturmeldungen", "traders union": "Trading-Ratgeberportal", "ndtv profit": "indischer Wirtschaftssender",
    "economic times": "indische Wirtschaftszeitung", "business today": "indisches Wirtschaftsmagazin", "boerse.de": "deutsches Börsenportal",
    "barchart": "US-Börsendatenportal", "der aktionär": "deutsches Börsenmagazin", "finanznachrichten": "deutsches Finanznachrichtenportal",
    "börse online": "deutsches Börsenmagazin", "seoul economic daily": "südkoreanische Wirtschaftszeitung", "stock titan": "Portal für Firmenmitteilungen",
    "t-online": "deutsches Nachrichtenportal", "thestreet": "US-Finanzportal", "livemint": "indische Wirtschaftszeitung",
    "moneycontrol": "indisches Finanzportal", "stock3": "deutsches Börsenportal", "chosunbiz": "südkoreanisches Wirtschaftsportal",
    "korea joongang daily": "südkoreanische Tageszeitung", "pr newswire": "Verbreiter von Firmenmitteilungen",
    "globenewswire": "Verbreiter von Firmenmitteilungen", "business wire": "Verbreiter von Firmenmitteilungen",
    "streetinsider": "US-Börsennachrichtendienst", "quartz": "US-Wirtschaftsnachrichtenportal", "smh.com.au": "australische Tageszeitung",
    "fxstreet": "Devisen- und Börsenportal", "techcrunch": "US-Technologieportal", "the verge": "US-Technologieportal",
    "sec.gov": "US-Börsenaufsicht SEC (offizielle Pflichtmeldung)",
}
def describe(source, official=None):
    if official == "sec": return "Pflichtmeldung bei der US-Börsenaufsicht SEC"
    if official: return "Mitteilung der Firma selbst"
    s = (source or "").lower()
    for k in sorted(SOURCES, key=len, reverse=True):
        if k in s: return SOURCES[k]
    return None

PROMPT = """Du bist eine neutrale Wirtschaftsjournalistin. Schreibe auf Deutsch (Schweizer Rechtschreibung, also "ss" statt "ß") eine Zusammenfassung zur Aktie {name} ({sym}).
Strenge Regeln:
- Verwende NUR die unten gelieferten Meldungen und Analystendaten. Erfinde nichts, keine Zahlen, die nicht in den Daten stehen.
- Jede Aussage nennt ihre Quelle mit Namen und kurzer Beschreibung, z.B. "Laut Reuters, einer internationalen Nachrichtenagentur, ...". Nutze die mitgelieferte Beschreibung ("desc"). Fehlt sie, beschreibe die Quelle nur, wenn sie eindeutig bekannt ist, sonst nur den Namen.
- Bei Widersprüchen beide Seiten neutral: "X berichtet ..., Y dagegen ...". Keine Seite bevorzugen.
- Keine eigene Meinung, keine Wertung, keine Empfehlung, keine Prognose.
- Nur Schlagzeilen sind bekannt: formuliere vorsichtig ("berichtet", "meldet"), nicht als Tatsache.
- Risiken und Negatives zuerst prüfen: Klagen, Ermittlungen, Bussen, Regulierung/Recht, Herabstufungen, gesenkte Prognosen, Kursrückgänge.
Antworte NUR mit JSON in genau dieser Form:
{{"kurzueberblick":[{{"text":"...","quelle":"Name","nr":1}}],
 "risiken":[{{"text":"...","quelle":"Name","nr":3,"rechtlich":true|false}}],
 "widersprueche":[{{"thema":"...","seiten":[{{"quelle":"Name","text":"...","nr":4}},{{"quelle":"Name","text":"...","nr":7}}]}}],
 "analysten":[{{"text":"...","quelle":"Name"}}],
 "vorlesetext":"..."}}
- "nr" ist die Nummer der verwendeten Meldung (Feld "nr"), bei Analystendaten weglassen.
- kurzueberblick: 2-4 wichtigste Punkte. risiken: leer [], wenn nichts Negatives in den Meldungen steht. widersprueche: leer [], wenn sich keine Quellen widersprechen.
- analysten: aus den Analystendaten (Quelle "Yahoo Finance") und Analysten-Meldungen.
- vorlesetext: natürlich gesprochenes Deutsch, 140-220 Wörter (60-90 Sekunden), ganze Sätze, keine Listen, keine Abkürzungen wie "Mio." oder "%" (schreibe "Prozent", "Millionen"), Quellen beim Namen nennen. Reihenfolge: kurzer Überblick, dann Risiken und Rechtliches (falls keine: "In den vorliegenden Meldungen wurden keine Risiken oder rechtlichen Probleme gefunden."), dann Widersprüche, dann Analysten. Letzter Satz genau: "Keine Anlageberatung."

DATEN (JSON):
{data}"""

def _post(url, body, key, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def call(model, prompt, key):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2, "maxOutputTokens": 2500}}
    d = _post("%s/models/%s:generateContent" % (API, model), body, key)
    parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    txt = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    m = re.search(r"\{.*\}", txt, re.S)
    if not m: raise ValueError("keine JSON-Antwort")
    return json.loads(m.group(0)), (d.get("usageMetadata") or {})

def err_text(e):
    if isinstance(e, urllib.error.HTTPError):
        try: msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception: msg = ""
        return "HTTP %s %s" % (e.code, msg[:160])
    return str(e)[:200]

def build_input(stock, items, analyst, analyst_news, rel_re, now):
    sym = stock["symbol"]; cutoff = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mine = [i for i in items if sym in (i.get("symbols") or []) and i["published"] >= cutoff and (i.get("q") or 0) >= 1
            and (i.get("official") or not rel_re or rel_re.search(i["title"]))]
    mine.sort(key=lambda i: ((1 if i.get("official") else 0), i.get("q") or 0, i["published"]), reverse=True)
    seen, news = set(), []
    for i in mine:
        k = re.sub(r"\W+", "", (i.get("title_de") or i["title"]).lower())[:60]
        if k in seen: continue
        seen.add(k)
        n = {"nr": len(news) + 1, "quelle": i["source"], "desc": describe(i["source"], i.get("official")), "datum": i["published"][:16].replace("T", " "),
             "titel": i["title"]}
        if i.get("title_de") and i["title_de"] != i["title"]: n["titel_de"] = i["title_de"]
        if i.get("desc"): n["inhalt"] = i["desc"][:300]
        news.append(n)
        if len(news) >= 25: break
    a = analyst or {}
    ad = {k: a[k] for k in ("consensus", "target", "next_earnings") if a.get(k)}
    if a.get("changes"): ad["aenderungen"] = a["changes"][:6]
    return {"aktie": stock.get("name"), "symbol": sym, "meldungen": news, "analystendaten_yahoo_finance": ad,
            "analysten_meldungen": [{"quelle": x["source"], "titel": x.get("title_de") or x["title"]} for x in (analyst_news or [])]}

def clean(o, inp=None):
    by = {m["nr"]: m["titel"] for m in (inp or {}).get("meldungen", [])}
    def tit(e, r):
        try: n = int(e.get("nr"))
        except Exception: return
        if n in by: r["titel"] = by[n]
    def lst(x): return x if isinstance(x, list) else []
    out = {"kurzueberblick": [], "risiken": [], "widersprueche": [], "analysten": []}
    for k in ("kurzueberblick", "risiken", "analysten"):
        for e in lst(o.get(k)):
            if isinstance(e, dict) and e.get("text"):
                r = {"text": str(e["text"]).strip(), "quelle": str(e.get("quelle") or "").strip()}
                d = describe(r["quelle"]) if r["quelle"] else None
                if r["quelle"].lower().startswith(("mitteilung", "firma", "unternehmen")): d = "Mitteilung der Firma selbst"
                if d: r["desc"] = d
                tit(e, r)
                if k == "risiken": r["rechtlich"] = bool(e.get("rechtlich"))
                out[k].append(r)
    for w in lst(o.get("widersprueche")):
        if isinstance(w, dict):
            s = []
            for x in lst(w.get("seiten")):
                if isinstance(x, dict) and x.get("text"):
                    r = {"quelle": str(x.get("quelle") or ""), "text": str(x.get("text") or ""), "desc": describe(x.get("quelle"))}
                    tit(x, r); s.append(r)
            if len(s) >= 2: out["widersprueche"].append({"thema": str(w.get("thema") or ""), "seiten": s})
    v = str(o.get("vorlesetext") or "").strip().replace("ß", "ss")
    if v and not v.rstrip().endswith("Keine Anlageberatung."): v = v.rstrip() + " Keine Anlageberatung."
    out["vorlesetext"] = v
    for k in ("kurzueberblick", "risiken", "analysten"):
        for e in out[k]: e["text"] = e["text"].replace("ß", "ss")
    for w in out["widersprueche"]:
        for s in w["seiten"]: s["text"] = s["text"].replace("ß", "ss")
    if not out["vorlesetext"] or not out["kurzueberblick"]: raise ValueError("unvollstaendige Antwort")
    return out

def run(stocks, items, insights_by_sym, rel_fn, path, now, log=print):
    try: old = json.load(open(path, encoding="utf-8"))
    except Exception: old = {}
    cache = old.get("stocks", {}) if isinstance(old, dict) else {}
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    errors, calls, model_ok = [], 0, old.get("model")
    jobs = []
    for s in stocks:
        sym = s["symbol"]
        if s.get("type") in ("index",) or sym.startswith("^") or sym.endswith("=F"): continue
        ins = insights_by_sym.get(sym) or {}
        inp = build_input(s, items, ins.get("analyst"), ins.get("analyst_news"), rel_fn(s), now)
        if not inp["meldungen"] and not inp["analystendaten_yahoo_finance"]: continue
        h = hashlib.sha1(json.dumps({"n": [m["titel"] for m in inp["meldungen"]], "a": inp["analystendaten_yahoo_finance"].get("consensus")}, sort_keys=True).encode()).hexdigest()[:12]
        c = cache.get(sym)
        if c and c.get("input_hash") == h: continue
        age = 1e9
        if c and c.get("generated_at"):
            age = (now - datetime.strptime(c["generated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 3600
        if age < MIN_AGE_H: continue
        jobs.append((-age, sym, s, inp, h))
    jobs.sort(key=lambda j: j[0])   # aelteste/fehlende zuerst
    if not key:
        log("KI: kein GEMINI_API_KEY, uebersprungen (%d waeren faellig)" % len(jobs))
    models = ([model_ok] if model_ok in MODELS else []) + [m for m in MODELS if m != model_ok]
    for _, sym, s, inp, h in jobs if key else []:
        if calls >= MAX_CALLS: break
        prompt = PROMPT.format(name=s.get("name") or sym, sym=sym, data=json.dumps(inp, ensure_ascii=False))
        done = False
        while models and not done:
            m = models[0]
            try:
                calls += 1
                o, usage = call(m, prompt, key)
                r = clean(o, inp)
                r.update({"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "model": m, "input_hash": h,
                          "n_meldungen": len(inp["meldungen"])})
                r["id"] = hashlib.sha1(r["vorlesetext"].encode()).hexdigest()[:10]
                cache[sym] = r; model_ok = m; done = True
                log("KI OK     %-10s %s, %d Meldungen, %s Tokens" % (sym, m, len(inp["meldungen"]), usage.get("totalTokenCount")))
            except urllib.error.HTTPError as e:
                t = err_text(e)
                log("KI FEHLER %-10s %s %s" % (sym, m, t))
                if e.code in (404, 400) and ("not found" in t.lower() or "not supported" in t.lower() or e.code == 404):
                    models.pop(0); continue          # Modell nicht verfuegbar -> naechstes
                if e.code == 429:
                    if "per day" in t.lower() or "PerDay" in t: models.pop(0); continue   # Tageskontingent -> naechstes Modell
                    time.sleep(30)
                errors.append({"symbol": sym, "what": "ai", "error": t}); break
            except Exception as e:
                log("KI FEHLER %-10s %s %s" % (sym, m, err_text(e)))
                errors.append({"symbol": sym, "what": "ai", "error": err_text(e)}); break
            finally:
                time.sleep(SLEEP_S)
        if not models:
            log("KI: kein Modell mehr verfuegbar, Abbruch"); break
    doc = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "model": model_ok,
           "source": "Google Gemini (Gratis-Kontingent), nur aus den gesammelten Meldungen und Analystendaten",
           "stocks": cache, "errors": errors[-20:], "pending": max(0, len(jobs) - sum(1 for j in jobs if cache.get(j[1], {}).get("input_hash") == j[4])),
           "sources": SOURCES}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    log("KI: %d Aufrufe, %d/%d Aktien mit Zusammenfassung, %d Fehler" % (calls, len(cache), len(stocks), len(errors)))
    return doc
