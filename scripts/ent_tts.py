#!/usr/bin/env python3
"""Entdecken-Audio: pro Eintrag und Liste ein kurzes deutsches Skript (nur aus den abgerufenen Daten in data/entdecken.json,
nichts erfunden) + je Liste eine kurze Lern-Erklaerung. MP3 per edge-tts (de-CH-LeniNeural) nach data/audio/ent/.
Neu erzeugt wird nur bei geaendertem Text (Hash in data/audio/ent/index.json). Schreibt "say"/"audio" in entdecken.json."""
import hashlib, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENT = os.path.join(ROOT, "data", "entdecken.json")
DIR = os.path.join(ROOT, "data", "audio", "ent"); IDX = os.path.join(DIR, "index.json")
VOICE = os.environ.get("EDGE_VOICE", "de-CH-LeniNeural")
def th(t): return hashlib.sha1((VOICE + "|" + t).encode()).hexdigest()[:16]

# ---- Zahlen in deutschen Worten ----
E = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf",
     "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
Z = ["", "", "zwanzig", "dreissig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig"]
def w99(n):
    if n < 20: return E[n]
    e, z = n % 10, n // 10
    return (("ein" if e == 1 else E[e]) + "und" if e else "") + Z[z]
def w999(n):
    h, r = divmod(n, 100)
    return (("ein" if h == 1 else E[h]) + "hundert" if h else "") + (w99(r) if r or not h else "")
def words(n):
    n = int(n)
    if n < 0: return "minus " + words(-n)
    if n < 1000: return w999(n)
    if n < 10**6:
        t, r = divmod(n, 1000)
        return ("ein" if t == 1 else w999(t)) + "tausend" + (w999(r) if r else "")
    m, r = divmod(n, 10**6)
    return ("eine Million" if m == 1 else words(m) + " Millionen") + (" " + words(r) if r else "")
def dec(x, nd=1):
    """12.3 -> zwölf Komma drei"""
    x = round(abs(x), nd); i = int(x); f = int(round((x - i) * 10**nd))
    s = words(i)
    if i == 1 and not f: s = "eins"
    if f: s += " Komma " + " ".join(E[int(c)] for c in ("%0*d" % (nd, f)).rstrip("0"))
    return s
def pct(x): return ("plus " if x > 0 else "minus " if x < 0 else "") + dec(x) + " Prozent"
def dollar(x):
    x = round(x, 2); d = int(x); c = int(round((x - d) * 100))
    s = ("ein" if d == 1 else words(d)) + " Dollar"
    return s + (" und " + words(c) + " Cent" if c else "")
MON = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
ORD = {1: "ersten", 3: "dritten", 7: "siebten", 8: "achten"}
def datum(ts):
    d = datetime.fromtimestamp(ts, timezone.utc)
    o = ORD.get(d.day) or (w99(d.day) + ("sten" if d.day >= 20 else "ten"))
    return "am " + o + " " + MON[d.month - 1]
def clean(n): return re.sub(r"\s*,?\s*\b(Inc|Corp|Corporation|Co|Ltd|plc|N\.V|S\.A|SE|AG|Incorporated|Holdings?|Company)\b\.?", "", n).strip(" ,.") or n

INTRO = {
 "potenzial": "Entdecken, Liste Grösstes Potenzial. Kurz zum Lernen: Analysten von Banken setzen für eine Aktie ein Kursziel, also den Preis, den sie in etwa zwölf Monaten erwarten. Hier siehst du, wie weit der heutige Kurs unter dem Durchschnitt dieser Kursziele liegt, plus frische Hoch- oder Abstufungen. Ein Kursziel ist eine Meinung, keine Garantie. Alle Beträge in Dollar. Zum Lernen, keine Anlageberatung.",
 "wachstum": "Entdecken, Liste Stärkstes Wachstum. Kurz zum Lernen: Hier zählt, wie stark der Kurs in den letzten drei Monaten gestiegen ist. Das zeigt, was gerade gefragt ist, sagt aber nichts über die Zukunft. Nach starken Anstiegen kann es auch wieder fallen. Alle Beträge in Dollar. Zum Lernen, keine Anlageberatung.",
 "zahlen": "Entdecken, Liste Frische Zahlen. Kurz zum Lernen: Firmen veröffentlichen jedes Quartal ihre Zahlen. Wichtig ist der Gewinn je Aktie im Vergleich zur Erwartung der Analysten. Liegt er darüber, spricht man von einer positiven Überraschung, liegt er darunter, von einer Enttäuschung. Alle Beträge in Dollar. Zum Lernen, keine Anlageberatung.",
 "gegenteil": "Entdecken, Liste Gegenteil. Kurz zum Lernen: Hier stehen Aktien, die negativ aufgefallen sind, mit starken Kursverlusten im letzten Monat, Zahlen unter der Erwartung oder Abstufungen durch Analysten. Das heisst nicht automatisch, dass die Firma schlecht ist. Alle Beträge in Dollar. Zum Lernen, keine Anlageberatung.",
}
def changes(n, d, only=None):
    out = []
    for c in (d.get("changes") or [])[:2]:
        if only and c["a"] != only: continue
        out.append("%s hat %s %s %s%s." % (c.get("firm") or "Ein Analysehaus", n, datum(c["t"]), "hochgestuft" if c["a"] == "up" else "abgestuft", (" auf " + c["to"]) if c.get("to") else ""))
    return " ".join(out)
def earn(n, d):
    e = d.get("earn")
    if not e: return ""
    bm = "über" if e["act"] > e["est"] else ("unter" if e["act"] < e["est"] else "genau bei")
    s = "%s hat %s Quartalszahlen veröffentlicht. Der Gewinn je Aktie lag %s der Erwartung der Analysten" % (n, datum(e["t"]), bm)
    k = 1.0 if e.get("cur") == "USD" else e.get("fx")
    if k: s += ": %s statt erwartet %s" % (dollar(e["act"] * k), dollar(e["est"] * k))
    if e.get("sur") is not None: s += ". Das ist eine Abweichung von %s" % pct(e["sur"])
    return s + "."
def perf(n, d):
    p = []
    if d.get("m1") is not None: p.append("im letzten Monat um %s" % pct(d["m1"]))
    if d.get("m3") is not None: p.append("in drei Monaten um %s" % pct(d["m3"]))
    return ("Der Kurs von %s veränderte sich %s." % (n, " und ".join(p))) if p else ""
def script(k, x):
    n, d = clean(x["name"]), x.get("d") or {}
    parts = ["Zur Aktie %s." % n, "%s kostet im Moment %s." % (n, dollar(x["price_usd"]))]
    if k == "potenzial":
        if d.get("target_usd"): parts.append("Das durchschnittliche Kursziel von %s Analysten für %s liegt bei %s. Bis dahin wären es %s." % (words(d["analysts"]), n, dollar(d["target_usd"]), pct(d["upside"])))
        parts += [changes(n, d), perf(n, d)]
    elif k == "wachstum":
        parts += [perf(n, d)]
        if d.get("target_usd"): parts.append("Zum Vergleich: Das durchschnittliche Kursziel der Analysten für %s liegt bei %s." % (n, dollar(d["target_usd"])))
        parts.append(changes(n, d))
    elif k == "zahlen":
        parts.append(earn(n, d))
        if x.get("ai"): parts.append("Eine KI fasst die Schlagzeilen zu %s so zusammen: %s" % (n, x["ai"]))
        parts.append(perf(n, d))
    else:
        parts += [perf(n, d), earn(n, d) if (d.get("earn") and d["earn"]["act"] < d["earn"]["est"]) else "", changes(n, d, "down")]
    if x.get("mine"): parts.append("%s ist schon auf deiner Liste." % n)
    parts.append("Das war die Aktie %s." % n)
    t = " ".join(p for p in parts if p)
    t = re.sub(r"\bUSD\b", "Dollar", t).replace("ß", "ss").replace("%", " Prozent")
    return re.sub(r"\s+", " ", t).strip()

# ---- Nachrichten: je Meldung (Aktien der Liste, neueste zuerst) ein kurzer Text aus Titel/Quelle/Datum ----
NEWS_N = int(os.environ.get("NEWS_AUDIO_N", "120"))
CUR = {"€": "EUR", "eur": "EUR", "euro": "EUR", "chf": "CHF", "franken": "CHF", "£": "GBP", "gbp": "GBP", "pfund": "GBP", "yen": "JPY", "¥": "JPY"}
MULT = {"mrd": 1e9, "milliarden": 1e9, "milliarde": 1e9, "mio": 1e6, "millionen": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "mn": 1e6}
def num(t):
    t = t.strip()
    if re.fullmatch(r"\d{1,3}([.’']\d{3})+", t): return float(re.sub(r"[.’']", "", t))
    return float(t.replace(",", "."))
def big(v):
    if v >= 1e9: return dec(v / 1e9) + (" Milliarde" if round(v / 1e9, 1) == 1 else " Milliarden")
    if v >= 1e6: return dec(v / 1e6) + (" Million" if round(v / 1e6, 1) == 1 else " Millionen")
    return dec(v, 2 if v < 100 and v != int(v) else 0)
def money(title, fx):
    """Betraege -> Dollar in Worten; Fremdwaehrung mit EZB-Kurs umgerechnet ("rund ... Dollar")."""
    N_ = r"(\d[\d.,’']*)"; M_ = r"(?:\s*(Mrd\.?|Milliarden?|Mio\.?|Millionen|Million|bn|mn)\b)?"
    def conv(v, m, cur):
        v *= MULT.get((m or "").lower().rstrip("."), 1)
        if cur != "USD":
            r = fx.get(cur)
            if not r: return None
            return "rund " + big(v / r) + " Dollar"
        return big(v) + " Dollar"
    def rep(cur_of):
        def f(mo):
            g = mo.groupdict(); cur = cur_of(g)
            try: out = conv(num(g["n"]), g.get("m"), cur)
            except Exception: out = None
            return out if out else mo.group(0)
        return f
    t = re.sub(r"(?P<c>US\$|\$|€|£|CHF)\s?(?P<n>\d[\d.,’']*)(?:\s*(?P<m>Mrd|Milliarden?|Mio|Millionen|Million|bn|mn)\b\.?)?",
               rep(lambda g: "USD" if "$" in g["c"] else CUR.get(g["c"].lower(), g["c"].upper())), title)
    t = re.sub(r"(?P<n>\d[\d.,’']*)(?:\s*(?P<m>Mrd|Milliarden?|Mio|Millionen|Million|bn|mn)\b\.?)?\s*(?P<c>US-Dollar|Dollar|USD|Euro|EUR|€|CHF|Franken|Pfund|GBP|£|Yen|JPY)\b",
               rep(lambda g: "USD" if g["c"] in ("US-Dollar", "Dollar", "USD") else CUR.get(g["c"].lower(), g["c"].upper())), t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*(%|Prozent)", lambda m: dec(float(m.group(1).replace(",", "."))) + " Prozent", t)
    t = re.sub(r"\b\d{1,3}(?:[.’']\d{3})+\b|\b\d+(?:,\d+)?\b", lambda m: dec(num(m.group(0)), 2) if not re.fullmatch(r"(19|20)\d\d", m.group(0)) else m.group(0), t)
    return t
def news_script(it, names, fx):
    syms = [s for s in it.get("symbols") or [] if s in names]
    n = clean(names[syms[0]]) if syms else "deinem Markt"
    title = re.sub(r"\s+-\s+[\w.\- ]+$", "", (it.get("title_de") or it.get("title") or "").strip()).replace("ß", "ss")
    title = re.sub(r"^(ROUNDUP|ANALYSE|KORREKTUR|EILMELDUNG|WDH)\s*\d*\s*[:/]\s*", "", title)
    pub = datetime.strptime(it["published"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() if it.get("published") else None
    t = "Zur Aktie %s. %s meldet%s: %s." % (n, it.get("source") or "Eine Quelle", (" " + datum(pub)) if pub else "", money(title, fx).rstrip(". "))
    if len(syms) > 1: t += " Die Meldung betrifft auch " + " und ".join(clean(names[s]) for s in syms[1:3]) + "."
    t += " Das war eine Meldung zu %s." % n
    return re.sub(r"\s+", " ", t)
MARKT_N = int(os.environ.get("MARKT_AUDIO_N", "60"))
def markt_items():
    try:
        wl = json.load(open(os.path.join(ROOT, "watchlist.json"))); nw = json.load(open(os.path.join(ROOT, "data", "news.json")))
        fx = json.load(open(os.path.join(ROOT, "data", "fx.json"))).get("per_usd") or {}
    except Exception: return {}
    lab = {t["topic"]: t["label"] for t in wl.get("market_topics", [])}
    its = [x for x in nw.get("items") or [] if x.get("id") and x.get("topic")]
    its.sort(key=lambda x: x.get("published") or "", reverse=True)
    out = {}
    for it in its[:MARKT_N]:
        tl = lab.get(it["topic"], it["topic"])
        title = re.sub(r"\s+-\s+[\w.\- ]+$", "", (it.get("title_de") or it.get("title") or "").strip()).replace("ß", "ss")
        pub = datetime.strptime(it["published"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() if it.get("published") else None
        t = "Zum Thema %s. %s meldet%s: %s. Das war eine Meldung zum Thema %s." % (tl, it.get("source") or "Eine Quelle", (" " + datum(pub)) if pub else "", money(title, fx).rstrip(". "), tl)
        out[it["id"]] = {"say": re.sub(r"\s+", " ", t)}
    return out
def news_items():
    try:
        wl = json.load(open(os.path.join(ROOT, "watchlist.json"))); nw = json.load(open(os.path.join(ROOT, "data", "news.json")))
        fx = json.load(open(os.path.join(ROOT, "data", "fx.json"))).get("per_usd") or {}
    except Exception: return {}
    names = {s["symbol"]: s["name"] for s in wl.get("stocks", []) if not s["symbol"].startswith("^") and "=" not in s["symbol"]}
    its = [x for x in nw.get("items") or [] if x.get("id") and any(s in names for s in x.get("symbols") or [])]
    its.sort(key=lambda x: x.get("published") or "", reverse=True)
    return {x["id"]: {"say": news_script(x, names, fx)} for x in its[:NEWS_N]}

def edge_mp3(text, out):
    import asyncio, subprocess, edge_tts
    raw = out + ".edge.mp3"
    async def go(): await edge_tts.Communicate(text, VOICE, rate="-5%").save(raw)
    for i in range(3):
        try: asyncio.run(go()); break
        except Exception:
            if i == 2: raise
            time.sleep(3)
    tmp = out + ".tmp.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "24k", tmp], check=True)
    os.replace(tmp, out); os.unlink(raw)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    return round(float(d or 0), 1)
def fname(k, s): return k + "_" + re.sub(r"[^A-Za-z0-9.\-]", "_", s) + ".mp3"

def main():
    doc = json.load(open(ENT)); os.makedirs(DIR, exist_ok=True)
    try: idx = json.load(open(IDX))
    except Exception: idx = {"files": {}}
    jobs, want = [], {}
    for k, items in (doc.get("lists") or {}).items():
        it = {"say": INTRO[k]} if k in INTRO else None
        doc.setdefault("intros", {})[k] = it
        todo = ([("_intro", it)] if it else []) + [(x["symbol"], x) for x in items]
        for s, x in todo:
            if s != "_intro": x["say"] = script(k, x)
            f = fname(k, s); want[f] = x
            e = idx["files"].get(f)
            if not (e and e.get("h") == th(x["say"]) and os.path.exists(os.path.join(DIR, f))): jobs.append((f, x))
    doc["news"] = news_items()
    for i_, x in doc["news"].items():
        f = "news_" + re.sub(r"[^A-Za-z0-9]", "_", i_) + ".mp3"; want[f] = x
        e = idx["files"].get(f)
        if not (e and e.get("h") == th(x["say"]) and os.path.exists(os.path.join(DIR, f))): jobs.append((f, x))
    doc["markt"] = markt_items()
    for i_, x in doc["markt"].items():
        f = "markt_" + re.sub(r"[^A-Za-z0-9]", "_", i_) + ".mp3"; want[f] = x
        e = idx["files"].get(f)
        if not (e and e.get("h") == th(x["say"]) and os.path.exists(os.path.join(DIR, f))): jobs.append((f, x))
    print("Entdecken-Audio: %d Texte, %d neu" % (len(want), len(jobs)))
    ok = True
    try: import edge_tts  # noqa
    except Exception: print("edge-tts fehlt, nur Texte"); ok = False
    def run(j):
        f, x = j
        try: return f, edge_mp3(x["say"], os.path.join(DIR, f))
        except Exception as ex: print("Fehler", f, str(ex)[:120]); return f, None
    if ok and jobs:
        with ThreadPoolExecutor(4) as ex:
            for f, dur in ex.map(run, jobs):
                if dur: idx["files"][f] = {"h": th(want[f]["say"]), "dur": dur}
    for f in list(idx["files"]):
        if f not in want: idx["files"].pop(f); 
    for f in os.listdir(DIR):
        if f.endswith(".mp3") and f not in idx["files"]: os.unlink(os.path.join(DIR, f))
    for f, x in want.items():
        e = idx["files"].get(f)
        if e and e["h"] == th(x["say"]): x["audio"] = {"file": "ent/" + f, "hash": e["h"], "dur": e["dur"], "engine": "edge"}
        else: x.pop("audio", None)
    idx["voice"] = VOICE; idx["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    json.dump(idx, open(IDX, "w"), indent=0)
    json.dump(doc, open(ENT, "w"), ensure_ascii=False, indent=0)
    print("fertig: %d MP3" % len(idx["files"]))
if __name__ == "__main__":
    try: main()
    except Exception as e: print("Entdecken-Audio Fehler:", str(e)[:200]); sys.exit(0)
