#!/usr/bin/env python3
"""Sendung: taegliche Morgen-Episode (werktags) und Wochen-Episode (Samstag) als MP3-Kapitel.
Nur aus gesammelten Daten (Yahoo Finance, SEC EDGAR, Schlagzeilen). Optional 1 Gemini-Aufruf (Gratis-Kontingent) zum Formulieren;
ohne Kontingent: Vorlage aus den Daten. Alle Betraege in Dollar, in Worten."""
import json, os, re, sys, time, hashlib
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
import ent_tts as T
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "audio", "sendung")
OUT = os.path.join(ROOT, "data", "sendung.json")
ZH = ZoneInfo("Europe/Zurich")
KEEP = 14
WT = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
PROD = r"produkt|launch|lanc|vorgestellt|stellt .* vor|neue[nrs]? |unveil|introduc|release|partner|kooperat|zusammenarbeit|deal|vertrag|auftrag|contract|order|übernahm|übernimmt|acqui|merger|projekt|pipeline|studie|trial|zulassung|fda|approval|chip|modell|plattform|software|fabrik|werk|ausbau|invest|kapazit|lizenz|patent|rechenzentr|data center|reaktor|medikament"
NOISE = r"aktie news:|am (montag|dienstag|mittwoch|donnerstag|freitag)(vormittag|nachmittag|abend)?|gefragt|verliert|legt zu|notiert|so (viel|entwickelt)|kurs aktuell|most active|stocks to watch|top stocks|should you buy|is it time"
LERN = [
 ("Kursziel", "Ein Kursziel ist der Preis, den eine Analystin oder ein Analyst einer Bank für eine Aktie in etwa zwölf Monaten erwartet. Es ist eine Meinung, keine Garantie. Spannend wird es, wenn mehrere Banken ihr Kursziel in die gleiche Richtung ändern."),
 ("Gewinn je Aktie", "Der Gewinn je Aktie, auf Englisch E P S, ist der Gewinn der Firma geteilt durch die Zahl ihrer Aktien. Bei Quartalszahlen vergleicht man ihn mit der Erwartung der Analysten. Liegt er darüber, ist das eine positive Überraschung."),
 ("Umsatz", "Der Umsatz ist alles Geld, das eine Firma mit ihren Produkten einnimmt, bevor Kosten abgezogen werden. Wächst der Umsatz schnell, verkauft die Firma mehr. Ob sie damit auch Geld verdient, zeigt erst der Gewinn."),
 ("Marge", "Die Marge sagt, wie viel vom Umsatz als Gewinn übrig bleibt. Eine Marge von zwanzig Prozent heisst: von hundert Dollar Umsatz bleiben zwanzig Dollar Gewinn. Steigende Margen gelten als gutes Zeichen."),
 ("Kurs-Gewinn-Verhältnis", "Das Kurs-Gewinn-Verhältnis, kurz K G V, teilt den Aktienkurs durch den Gewinn je Aktie. Ein K G V von dreissig heisst: Anleger zahlen dreissig Dollar für einen Dollar Jahresgewinn. Hohe Werte zeigen hohe Erwartungen an das Wachstum."),
 ("Prognose", "Viele Firmen geben bei den Quartalszahlen eine Prognose, auf Englisch Guidance, für die nächsten Monate. Oft bewegt die Prognose den Kurs stärker als die Zahlen selbst, weil die Börse in die Zukunft schaut."),
 ("Marktkapitalisierung", "Die Marktkapitalisierung ist der Börsenwert einer Firma: Aktienkurs mal Zahl der Aktien. Sie zeigt, wie gross eine Firma an der Börse ist, nicht wie viel sie verdient."),
 ("Hochstufung und Abstufung", "Wenn eine Bank ihre Empfehlung verbessert, zum Beispiel von Halten auf Kaufen, heisst das Hochstufung. Das Gegenteil ist eine Abstufung. Solche Änderungen bewegen den Kurs oft am gleichen Tag."),
 ("Dividende", "Eine Dividende ist ein Teil des Gewinns, den die Firma an ihre Aktionäre auszahlt, meist pro Quartal oder einmal im Jahr. Wachstumsfirmen zahlen oft keine Dividende, weil sie das Geld wieder investieren."),
 ("Volatilität", "Volatilität beschreibt, wie stark ein Kurs schwankt. Eine volatile Aktie kann an einem Tag zehn Prozent steigen oder fallen. Mehr Schwankung heisst mehr Chance, aber auch mehr Risiko."),
 ("Insiderkauf", "Wenn Chefs oder Verwaltungsräte eigene Aktien ihrer Firma kaufen, nennt man das Insiderkauf. In den USA müssen sie das bei der Börsenaufsicht S E C melden. Käufe gelten oft als Zeichen von Vertrauen."),
 ("Zinsen", "Die Notenbank, in den USA die Fed, bestimmt den Leitzins. Sinken die Zinsen, wird Geld billiger, und Wachstumsaktien profitieren oft. Steigen sie, wird es für teure Aktien schwieriger."),
 ("Freier Cashflow", "Der freie Cashflow ist das Geld, das nach allen Ausgaben und Investitionen wirklich übrig bleibt. Damit kann eine Firma Schulden abbauen, Aktien zurückkaufen oder Dividenden zahlen."),
 ("Aktienrückkauf", "Bei einem Aktienrückkauf kauft die Firma eigene Aktien an der Börse zurück. Dadurch gibt es weniger Aktien, und der Gewinn verteilt sich auf weniger Stücke. Das stützt oft den Kurs."),
]

def J(p, d=None):
    try: return json.load(open(os.path.join(ROOT, p)))
    except Exception: return d if d is not None else {}
def ts(s):
    try: return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception: return None
def tag(d): return "%s, %s" % (WT[d.weekday()], T.datum(d.timestamp())[3:])
def usd(v, cur, fx):
    if v is None: return None
    if cur in (None, "USD"): return v
    r = fx.get(cur) if cur != "GBp" else (fx.get("GBP") and fx["GBP"] * 100)
    return v / r if r else None
def big(v):
    a = abs(v)
    if a >= 1e9: return T.dec(a / 1e9) + " Milliarden Dollar"
    if a >= 1e6: return T.dec(a / 1e6) + " Millionen Dollar"
    return T.dollar(a)
def title_of(x): return re.sub(r"\s+-\s+[\w.\- ]+$", "", (x.get("title_de") or x.get("title") or "").strip()).replace("ß", "ss")
def sx(t): return re.sub(r"\s+", " ", t.replace("ß", "ss")).strip()

def earn_info(syms, now):
    """Naechste Quartalszahlen + Erwartung (Yahoo calendarEvents)."""
    out = {}
    try:
        from insights import Yahoo, raw
        y = Yahoo(); y.login()
    except Exception as e:
        print("Yahoo-Login fehlgeschlagen:", e); return out
    for s in syms:
        try:
            import urllib.parse
            u = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/%s?modules=calendarEvents,price&crumb=%s" % (urllib.parse.quote(s, safe=""), urllib.parse.quote(y.crumb))
            r = json.loads(y.get(u))["quoteSummary"]["result"][0]
            e = (r.get("calendarEvents") or {}).get("earnings") or {}
            ds = [raw(d) for d in e.get("earningsDate") or [] if raw(d)]
            if not ds: continue
            out[s] = {"t": min(ds), "eps": raw(e.get("earningsAverage")), "rev": raw(e.get("revenueAverage")),
                      "cur": (r.get("price") or {}).get("currency"), "fcur": (r.get("price") or {}).get("financialCurrency")}
            time.sleep(0.3)
        except Exception as ex:
            print("Termin fehlt", s, ex)
    return out

def earn_chapter(E, names, fx, a, b, title):
    rows = sorted([(v["t"], s, v) for s, v in E.items() if a <= v["t"] < b])
    if not rows:
        return {"name": title, "say": title + ". In diesem Zeitraum sind für deine Aktien keine Quartalszahlen angekündigt, soweit die Daten von Yahoo Finance das zeigen."}
    t = [title + ". Diese Firmen aus deiner Liste melden ihre Quartalszahlen."]
    for tt, s, v in rows:
        n = names[s]; d = datetime.fromtimestamp(tt, ZH)
        p = "Zur Aktie %s: Zahlen %s, %s." % (n, WT[d.weekday()], T.datum(tt))
        cur = v.get("fcur") or v.get("cur")
        eps = usd(v.get("eps"), cur, fx); rev = usd(v.get("rev"), cur, fx)
        if eps is not None: p += " Die Analysten erwarten im Schnitt einen Gewinn je Aktie von %s%s." % ("minus " if eps < 0 else "", T.dollar(abs(eps)))
        if rev: p += " Beim Umsatz erwarten sie rund %s." % big(rev)
        if eps is None and not rev: p += " Eine Erwartung der Analysten fehlt in den Daten."
        t.append(p)
    return {"name": title, "say": " ".join(t)}

def gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key: print("Gemini: kein Schluessel, Vorlage"); return None
    import ai_summary as A
    for m in A.MODELS:
        try:
            o, u = A.call(m, prompt, key); print("Gemini OK", m, u.get("totalTokenCount")); return o
        except Exception as e:
            print("Gemini Fehler", m, A.err_text(e) if hasattr(A, "err_text") else e)
    return None

PROMPT = """Du schreibst Sprechtexte fuer einen deutschsprachigen Aktien-Podcast (Schweiz: schreibe korrekte Umlaute ä ö ü, aber "ss" statt "ß"). Zuhoerer ist Anfaenger.
Regeln: Verwende NUR die Fakten aus den Schlagzeilen unten. Nichts erfinden, keine eigenen Zahlen, keine Kursziele, keine Prognosen.
Schwerpunkt: Produkte, Markteinfuehrungen, Partner, Auftraege, Projekte, Pipeline. Kursmeldungen ohne Firmenbezug weglassen.
Pro Aktie 3 bis 6 kurze Saetze, beginne mit "Zur Aktie NAME." und nenne den Namen mindestens dreimal. Englische Schlagzeilen auf Deutsch zusammenfassen.
Sage am Ende in einem Satz vorsichtig, ob die Meldungen die Firma eher staerken, eher schwaechen oder ob es unklar ist ("koennte staerken"), mit kurzer Begruendung aus den Meldungen.
Wenn die Schlagzeilen zu duenn sind, sag das ehrlich. Zahlen nur genau so, wie sie in den Schlagzeilen stehen.
Antworte als JSON: {{"SYMBOL": {{"text": "...", "wirkung": "staerkt|schwaecht|unklar"}}}}
Daten:
{data}"""

def stock_block(s, n, news, fx, wk, ins, q, ai):
    """Vorlage ohne KI (nur Daten)."""
    p = ["Zur Aktie %s." % n]
    for x in news[:3]:
        d = ts(x.get("published"))
        p.append("%s meldet%s: %s." % (x.get("source") or "Eine Quelle", (" " + T.datum(d.timestamp())) if d else "", T.money(title_of(x), fx).rstrip(". ")))
    if not news: p.append("Zu %s gibt es in diesem Zeitraum keine Meldung zu Produkten oder Projekten in den Daten." % n)
    else: p.append("Ob diese Meldungen %s stärken oder schwächen, lässt sich aus den Schlagzeilen allein nicht sicher sagen." % n)
    return p

def week_extra(s, n, q, ins, fx, now):
    p = []
    sp = (q or {}).get("spark_5d") or []
    pr = usd((q or {}).get("price"), (q or {}).get("currency"), fx)
    if sp and sp[0]:
        ch = (sp[-1] / sp[0] - 1) * 100
        p.append("Der Kurs von %s veränderte sich in den letzten fünf Handelstagen um %s%s." % (n, T.pct(ch), (" auf " + T.dollar(pr)) if pr else ""))
    elif pr: p.append("%s kostet %s. Die Wochenveränderung fehlt in den Daten." % (n, T.dollar(pr)))
    an = (ins or {}).get("analyst") or {}
    cut = now - timedelta(days=7)
    chs = [c for c in an.get("changes") or [] if ts(c.get("date") or "") and ts(c["date"]) >= cut]
    cur = (q or {}).get("currency")
    for c in chs[:4]:
        t = "%s %s" % (c.get("firm") or "Eine Bank", c.get("action") or "äusserte sich")
        if c.get("to"): t += ", Empfehlung %s" % c["to"]
        if c.get("pt"):
            v = usd(c["pt"], cur, fx)
            if v:
                t += ", Kursziel %s" % T.dollar(v)
                if c.get("pt_prior") and c["pt_prior"] != c["pt"]:
                    w = usd(c["pt_prior"], cur, fx); t += " nach vorher %s" % T.dollar(w) if w else ""
        p.append(t + ".")
    if not chs: p.append("Diese Woche gab es zu %s keine neuen Bewertungen von Banken in den Daten." % n)
    tg = an.get("target") or {}
    if tg.get("mean"):
        v = usd(tg["mean"], cur, fx)
        if v: p.append("Das durchschnittliche Kursziel für %s liegt bei %s." % (n, T.dollar(v)))
    return p

def build(kind, now):
    wl = J("watchlist.json"); Q = J("data/quotes.json").get("quotes", {}); N = J("data/news.json").get("items", [])
    I = J("data/insights.json").get("stocks", {}); AI = J("data/ai.json").get("stocks", {}); fx = J("data/fx.json").get("per_usd", {})
    names = {s["symbol"]: re.sub(r"\s+(PLC|plc|Group|Markets|Technology|Platforms)$", "", T.clean(s["name"])) or T.clean(s["name"]) for s in wl.get("stocks", []) if not s["symbol"].startswith("^") and "=" not in s["symbol"]}
    loc = now.astimezone(ZH)
    hours = 24 * 7 if kind == "woche" else (72 if loc.weekday() == 0 else 30)
    cut = now - timedelta(hours=hours)
    per = {}
    for x in N:
        d = ts(x.get("published") or "")
        if not d or d < cut: continue
        t = (x.get("title") or "") + " " + (x.get("title_de") or "")
        if re.search(NOISE, t, re.I) and not x.get("official"): continue
        for s in (x.get("symbols") or [])[:2]:
            if s in names and (x.get("official") or re.search(r"\b(%s|%s)" % (re.escape(names[s].split()[0][:6]), re.escape(s.split(".")[0])), t, re.I)): per.setdefault(s, []).append(x)
    for s in per:
        seen = set(); L = []
        for x in sorted(per[s], key=lambda x: (bool(re.search(PROD, (x.get("title") or "") + (x.get("title_de") or ""), re.I)), x.get("q") or 0, x.get("published") or ""), reverse=True):
            k = title_of(x).lower()[:50]
            if k in seen: continue
            seen.add(k); L.append(x)
        per[s] = L
    prod = {s: L for s, L in per.items() if any(re.search(PROD, (x.get("title") or "") + (x.get("title_de") or ""), re.I) for x in L[:4])}
    chapters = []
    ep_title = ("Wochenrückblick, " if kind == "woche" else "Morgen-Sendung, ") + tag(loc)
    # Kapitel 1: Begruessung
    if kind == "woche":
        intro = "Willkommen zum Wochenrückblick vom Aktien-Radar, heute %s. Wir gehen deine Aktien einzeln durch: Kurs der Woche in Dollar, neue Bewertungen von Banken und die wichtigsten Firmen-Meldungen. Danach der Kalender der Quartalszahlen für nächste Woche und ein Begriff zum Lernen." % tag(loc)
    else:
        intro = "Guten Morgen und willkommen zur Sendung vom Aktien-Radar, heute %s. Zuerst ein kurzer Blick auf den Markt, dann die Firmen aus deiner Liste mit neuen Meldungen zu Produkten, Partnern und Projekten, danach die Quartalszahlen dieser Woche und zum Schluss ein Begriff zum Lernen." % tag(loc)
    intro += " Kurz vorweg: Alles stammt aus gesammelten Daten und Schlagzeilen, Beträge nenne ich in Dollar. Das ist keine Anlageberatung."
    chapters.append({"name": "Begrüssung", "say": intro})
    # Kapitel 2: Markt
    if kind != "woche":
        m = ["Der Markt kurz."]
        sp = Q.get("^GSPC")
        if sp and sp.get("change_pct") is not None: m.append("Der S und P fünfhundert, der Index der fünfhundert grossen US-Firmen, stand zuletzt bei %s gegenüber dem Vortag." % T.pct(sp["change_pct"]))
        mv = sorted([(v.get("change_pct"), s) for s, v in Q.items() if s in names and v.get("change_pct") is not None])
        if mv:
            up = [x for x in mv[::-1][:3] if x[0] > 0]; dn = [x for x in mv[:2] if x[0] < 0]
            if up: m.append("In deiner Liste am stärksten: " + ", ".join("%s mit %s" % (names[s], T.pct(c)) for c, s in up) + ".")
            if dn: m.append("Am schwächsten: " + ", ".join("%s mit %s" % (names[s], T.pct(c)) for c, s in dn) + ".")
        mk = sorted([x for x in N if x.get("topic") and ts(x.get("published") or "") and ts(x["published"]) >= now - timedelta(hours=hours)], key=lambda x: (x.get("q") or 0, x.get("published") or ""), reverse=True)[:2]
        for x in mk: m.append("Zum Thema %s meldet %s: %s." % (x["topic"], x.get("source") or "eine Quelle", T.money(title_of(x), fx).rstrip(". ")))
        chapters.append({"name": "Markt kurz", "say": " ".join(m)})
    # Aktien-Kapitel
    if kind == "woche":
        order = sorted(names, key=lambda s: -len(per.get(s, [])))
        pick = order[:16]
    else:
        pick = sorted(prod, key=lambda s: -len(prod[s]))[:10]
    data = {s: {"name": names[s], "schlagzeilen": [{"quelle": x.get("source"), "datum": (x.get("published") or "")[:10], "titel": title_of(x), "original": x.get("title")} for x in per.get(s, [])[:5]]} for s in pick if per.get(s)}
    g = gemini(PROMPT.format(data=json.dumps(data, ensure_ascii=False))) if data else None
    src_nums = {s: set(re.findall(r"\d+", json.dumps(data.get(s, {}), ensure_ascii=False))) for s in pick}
    used_ai = 0
    for s in pick:
        n = names[s]; txt = None
        o = (g or {}).get(s) if isinstance(g, dict) else None
        if o and isinstance(o, dict) and o.get("text"):
            t = sx(o["text"])
            bad = [d for d in re.findall(r"\d+", t) if d not in src_nums[s]]
            if not bad and t.count(n.split()[0]) >= 2:
                w = {"staerkt": "Meine Einordnung aus diesen Meldungen: Sie könnten %s eher stärken." % n, "schwaecht": "Meine Einordnung aus diesen Meldungen: Sie könnten %s eher schwächen." % n}.get(o.get("wirkung"), "Ob das %s stärkt oder schwächt, ist aus den Meldungen noch unklar." % n)
                if re.search(r"stärk|schwäch|unklar", t[-160:]): w = ""
                txt = [T.money(t, fx), w] if w else [T.money(t, fx)]; used_ai += 1
            else: print("KI-Text verworfen", s, bad[:3])
        if not txt: txt = stock_block(s, n, per.get(s, []), fx, kind == "woche", I.get(s), Q.get(s), AI.get(s))
        if kind == "woche":
            txt = [txt[0] if txt[0].startswith("Zur Aktie") else "Zur Aktie %s." % n] + week_extra(s, n, Q.get(s), I.get(s), fx, now) + (txt[1:] if txt[0].startswith("Zur Aktie") and len(txt) > 1 else txt if not txt[0].startswith("Zur Aktie") else [])
        txt.append("Das war %s." % n)
        chapters.append({"name": n, "sym": s, "say": sx(" ".join(txt))})
    if not pick: chapters.append({"name": "Firmen", "say": "Heute gibt es in den Daten keine neuen Meldungen zu Produkten, Partnern oder Projekten deiner Firmen."})
    # Quartalszahlen
    E = earn_info(list(names), now)
    if kind == "woche":
        st = (loc + timedelta(days=(7 - loc.weekday()) % 7 or 7)).replace(hour=0, minute=0, second=0)
        chapters.append(earn_chapter(E, names, fx, st.timestamp(), (st + timedelta(days=7)).timestamp(), "Quartalszahlen nächste Woche"))
    else:
        st = loc.replace(hour=0, minute=0, second=0); en = st + timedelta(days=7 - loc.weekday())
        chapters.append(earn_chapter(E, names, fx, st.timestamp(), en.timestamp(), "Quartalszahlen diese Woche"))
    w, l = LERN[(loc.timetuple().tm_yday + (7 if kind == "woche" else 0)) % len(LERN)]
    chapters.append({"name": "Begriff: " + w, "say": "Zum Lernen, der Begriff des Tages: %s. %s" % (w, l)})
    chapters.append({"name": "Schluss", "say": "Das war %s vom Aktien-Radar. Die Quellen findest du in der App bei jeder Aktie, den ganzen Text über den Knopf Als Text. Bis %s." % ("der Wochenrückblick" if kind == "woche" else "die Sendung", "nächste Woche" if kind == "woche" else "morgen")})
    for c in chapters: c["say"] = sx(c["say"])
    eid = loc.strftime("%Y-%m-%d") + ("-w" if kind == "woche" else "-t")
    return {"id": eid, "kind": kind, "date": loc.strftime("%Y-%m-%d"), "title": ep_title, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "writer": "Gemini (Gratis-Kontingent) %d Firmen, Rest Vorlage" % used_ai if used_ai else "Vorlage aus den Daten", "chapters": chapters}

def main():
    now = datetime.now(timezone.utc); loc = now.astimezone(ZH)
    kind = os.environ.get("SENDUNG_KIND") or ("woche" if loc.weekday() >= 5 else "tag")
    ep = build(kind, now)
    os.makedirs(DIR, exist_ok=True)
    doc = J("data/sendung.json", {"episodes": []})
    idx = J("data/audio/sendung/index.json", {"files": {}})
    jobs = []
    for i, c in enumerate(ep["chapters"]):
        f = "%s_%02d.mp3" % (ep["id"], i); c["audio"] = {"file": "sendung/" + f, "hash": T.th(c["say"])}
        e = idx["files"].get(f)
        if not (e and e.get("h") == c["audio"]["hash"] and os.path.exists(os.path.join(DIR, f))): jobs.append((f, c))
        else: c["audio"]["dur"] = e.get("dur")
    print("Sendung %s: %d Kapitel, %d Woerter, %d neu" % (ep["id"], len(ep["chapters"]), sum(len(c["say"].split()) for c in ep["chapters"]), len(jobs)))
    def run(j):
        f, c = j
        try:
            d = T.edge_mp3(c["say"], os.path.join(DIR, f)); idx["files"][f] = {"h": c["audio"]["hash"], "dur": d}; c["audio"]["dur"] = d
        except Exception as ex:
            print("TTS Fehler", f, ex); c.pop("audio", None)
    with ThreadPoolExecutor(4) as ex: list(ex.map(run, jobs))
    ep["dur"] = round(sum((c.get("audio") or {}).get("dur") or 0 for c in ep["chapters"]), 1)
    eps = [e for e in doc.get("episodes", []) if e["id"] != ep["id"]] + [ep]
    eps = sorted(eps, key=lambda e: e["id"], reverse=True)[:KEEP]
    keep = {c["audio"]["file"][8:] for e in eps for c in e["chapters"] if c.get("audio")}
    for f in list(idx["files"]):
        if f not in keep: idx["files"].pop(f, None)
    for f in os.listdir(DIR):
        if f.endswith(".mp3") and f not in keep: os.unlink(os.path.join(DIR, f))
    doc.update({"episodes": eps, "generated_at": ep["generated_at"], "voice": T.VOICE,
                "source": "Yahoo Finance, SEC EDGAR, Schlagzeilen (Google News u.a.); Text: Gemini Gratis-Kontingent oder Vorlage"})
    json.dump(idx, open(os.path.join(DIR, "index.json"), "w"), indent=1)
    json.dump(doc, open(OUT, "w"), ensure_ascii=False)
    print("Episode %s: %.0f s" % (ep["id"], ep["dur"]))

if __name__ == "__main__":
    main()
