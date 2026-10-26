"""Redakteur-KI (v35): macht aus Entwuerfen klare, vollstaendige deutsche Podcast-Saetze
und prueft sie danach gegen die Quelldaten (Faktencheck). Ein Aufruf bearbeitet viele Texte.
Cache data/redakteur.json: Hash(Entwurf+Fakten) -> fertiger Text. Kontingent leer -> letzter
guter Text derselben ID (nur wenn erlaubt), sonst der Entwurf (ein ganzer Satz-Template).
Den Schluessel liest das Skript nur aus der Umgebung (GEMINI_API_KEY)."""
import os, re, json, time, hashlib, urllib.request, urllib.error
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "redakteur.json")
API = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash"]
VERSION = 1
MAX_CALLS = int(os.environ.get("RED_MAX_CALLS", "60"))
BUDGET = float(os.environ.get("RED_BUDGET", "420"))
T0 = time.time()
STATE = {"calls": 0, "models": list(MODELS), "dead": False, "log": []}

P_EDIT = """Du bist Redakteur:in eines Schweizer Börsen-Podcasts (Hochdeutsch für die Schweiz).
Schreibe jeden ENTWURF zu einem gut hörbaren Podcast-Text um:
- klare, vollständige deutsche Sätze; keine Stichworte, keine abgebrochenen Überschriften, keine Aufzählungszeichen
- erkläre kurz den Zusammenhang (wer, was, warum es für die Aktie wichtig sein kann), aber NUR mit Inhalt aus QUELLE und ENTWURF
- englische Überschriften sinngemäss ins Deutsche übersetzen; keine englischen Reste (Firmen- und Produktnamen bleiben)
- Zahlen als Ziffern schreiben (z.B. 4,5 Prozent, 120 Millionen Dollar, 2026); keine Zahl erfinden, keine Zahl weglassen, die im Entwurf wichtig ist
- echte Umlaute ä ö ü, niemals ß (immer ss), keine Emojis, kein Markdown
- keine Anlageempfehlung, keine Spekulation über Kurse
- Länge ähnlich wie der Entwurf (höchstens 30 Prozent länger)
Antworte NUR mit JSON: {{"t": {{"<id>": "<Text>", ...}}}}
TEXTE:
{items}"""

P_CHECK = """Du bist Faktenprüfer:in. Vergleiche jeden TEXT Satz für Satz mit seiner QUELLE.
- Jede Zahl, jedes Datum, jeder Name und jede Behauptung muss in der QUELLE stehen oder direkt daraus folgen.
- Falsches korrigieren, Unbelegtes streichen. Stil, Satzbau und Länge sonst beibehalten. Vollständige Sätze, niemals ß.
- Ist ein Text grundsätzlich falsch, setze "ok": false.
Antworte NUR mit JSON: {{"t": {{"<id>": {{"ok": true, "text": "<geprüfter Text>"}}, ...}}}}
TEXTE:
{items}"""

def _load():
    try:
        with open(CACHE, encoding="utf-8") as f: c = json.load(f)
        if c.get("v") == VERSION: return c
    except Exception: pass
    return {"v": VERSION, "h": {}, "last": {}}
def _save(c):
    now = time.time()
    c["h"] = {k: v for k, v in c["h"].items() if now - v.get("at", 0) < 5 * 86400}
    c["last"] = {k: v for k, v in c["last"].items() if now - v.get("at", 0) < 10 * 86400}
    with open(CACHE, "w", encoding="utf-8") as f: json.dump(c, f, ensure_ascii=False, indent=0)

def digits(s):
    return set(re.sub(r"[.,'’ ](?=\d)", "", m) for m in re.findall(r"\d[\d.,'’ ]*\d|\d", s or ""))
def guard(text, src):
    """Numerischer Schutz: jede Zahl im Ergebnis muss in Quelle/Entwurf vorkommen."""
    have = digits(src) | {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
    return not [d for d in digits(text) if d not in have]
def _clean(t):
    t = re.sub(r"[*_#•]+", " ", str(t or "")).replace("ß", "ss").replace("ẞ", "SS")
    return re.sub(r"\s+", " ", t).strip()

def _call(prompt, key):
    while STATE["models"] and not STATE["dead"]:
        if STATE["calls"] >= MAX_CALLS or time.time() - T0 > BUDGET: STATE["dead"] = True; STATE["log"].append("Budget erreicht"); break
        m = STATE["models"][0]; STATE["calls"] += 1
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.25, "maxOutputTokens": 16000}}
        req = urllib.request.Request("%s/models/%s:generateContent" % (API, m), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: d = json.loads(r.read())
            parts = (((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            txt = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            mm = re.search(r"\{.*\}", txt, re.S)
            time.sleep(4)
            if mm:
                raw = mm.group(0)
                try: return (json.loads(raw, strict=False).get("t") or {})
                except ValueError:
                    raw = re.sub(r'\\(u[0-9a-fA-F]{4}|["\\/bfnrt])|\\', lambda x: x.group(0) if x.group(1) else '', raw)
                    return (json.loads(raw, strict=False).get("t") or {})
            STATE["log"].append("%s: kein JSON" % m)
        except urllib.error.HTTPError as e:
            try: msg = json.loads(e.read()).get("error", {}).get("message", "")
            except Exception: msg = ""
            STATE["log"].append("%s HTTP %s %s" % (m, e.code, msg[:100]))
            if e.code in (404, 400): STATE["models"].pop(0); continue
            if e.code == 429:
                if "per day" in msg.lower() or "PerDay" in msg: STATE["models"].pop(0); continue
                time.sleep(20); continue
            time.sleep(5)
        except Exception as e:
            STATE["log"].append("%s %s" % (m, str(e)[:100])); time.sleep(5)
    STATE["dead"] = True
    return None

def _fmt(rows, field):
    return "\n\n".join("### id: %s\nQUELLE: %s\n%s: %s" % (r["id"], r["src"], field, r[field]) for r in rows)

def edit(items, key=None, batch=12, keep_last=True, conv=None):
    """items: [{id, src, draft}] -> {id: text}. conv: Funktion fuer Zahlen->Worte (z.B. ent_tts.money)."""
    key = key if key is not None else os.environ.get("GEMINI_API_KEY", "")
    c = _load(); out = {}; todo = []; now = time.time()
    for it in items:
        h = hashlib.sha1(("%d|%s|%s" % (VERSION, it["draft"], it.get("src", ""))).encode()).hexdigest()[:16]
        it["h"] = h
        if h in c["h"]: c["h"][h]["at"] = now; out[it["id"]] = c["h"][h]["t"]
        else: todo.append(it)
    stat = {"cache": len(out), "neu": 0, "fallback": 0, "verworfen": 0}
    groups, cur, size = [], [], 0
    for it in todo:
        n = len(it["draft"]) + len(it.get("src", ""))
        if cur and (len(cur) >= batch or size + n > 14000): groups.append(cur); cur, size = [], 0
        cur.append(it); size += n
    if cur: groups.append(cur)
    for rows in groups:
        if not key or STATE["dead"]: break
        r1 = _call(P_EDIT.format(items=_fmt(rows, "draft").replace("draft:", "ENTWURF:")), key)
        if not r1: break
        chk = [dict(r, text=_clean(r1.get(r["id"]))) for r in rows if r1.get(r["id"])]
        r2 = _call(P_CHECK.format(items=_fmt(chk, "text").replace("text:", "TEXT:")), key) if chk else {}
        if r2 is None: break
        for r in chk:
            v = r2.get(r["id"]); t = r["text"]
            if isinstance(v, dict):
                if v.get("ok") is False: stat["verworfen"] += 1; continue
                t = _clean(v.get("text") or t)
            elif r2: continue   # nicht geprueft -> nicht uebernehmen
            if len(t) < 25 or not guard(t, r["src"] + " " + r["draft"]): stat["verworfen"] += 1; continue
            t = conv(t) if conv else t
            t = _clean(t)
            c["h"][r["h"]] = {"t": t, "at": now}; out[r["id"]] = t; stat["neu"] += 1
    for it in items:
        if it["id"] in out: c["last"][it["id"]] = {"t": out[it["id"]], "at": now}; continue
        stat["fallback"] += 1
        l = c["last"].get(it["id"]) if it.get("keep", keep_last) else None
        fb = it.get("fb", it["draft"])
        out[it["id"]] = l["t"] if l else _clean(conv(fb) if conv else fb)
    _save(c)
    print("Redakteur: %s, Aufrufe %d %s" % (stat, STATE["calls"], "; ".join(STATE["log"][-3:])))
    return out
