"""Gemini-Vorlesestimme: pro Aktie eine MP3 aus vorlesetext (data/ai.json) -> data/audio/<ticker>.mp3.
Nur Standardbibliothek + ffmpeg. Schluessel aus env GEMINI_API_KEY (wird nie ausgegeben).
Neu erzeugt wird nur, wenn sich der Text geaendert hat (Hash in data/audio/index.json).
Gratis-Limits: Pausen zwischen Aufrufen; bei Kontingentfehler (429) Abbruch, alte Dateien bleiben."""
import base64, hashlib, json, os, re, subprocess, sys, tempfile, time, urllib.request, urllib.error
API = "https://generativelanguage.googleapis.com/v1beta"
MODELS = ["gemini-2.5-flash-preview-tts"]   # pro-tts hat kein Gratis-Kontingent
VOICE = os.environ.get("TTS_VOICE", "Kore")
STYLE = "Lies den folgenden deutschen Text warm, ruhig und natürlich vor, wie ein freundlicher Nachrichtensprecher:\n\n"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUD = os.path.join(ROOT, "data", "audio"); IDX = os.path.join(AUD, "index.json")
def log(*a): print("TTS:", *a, flush=True)
def fname(sym): return re.sub(r"[^A-Za-z0-9.\-]", "_", sym) + ".mp3"
def thash(t): return hashlib.sha1((VOICE + "|" + t).encode()).hexdigest()[:16]
def th(t): return hashlib.sha1(t.encode()).hexdigest()[:16]
# ---- Gratis-Ersatz ohne Schluessel: edge-tts (Microsoft-Neuralstimmen) ----
EDGE_VOICE = os.environ.get("EDGE_VOICE", "de-CH-LeniNeural")
def edge_mp3(text, out):
    import asyncio, edge_tts
    raw = out + ".edge.mp3"
    async def go(): await edge_tts.Communicate(text, EDGE_VOICE, rate="-5%").save(raw)
    for i in range(3):
        try: asyncio.run(go()); break
        except Exception:
            if i == 2: raise
            time.sleep(3)
    tmp = out + ".tmp.mp3"   # mono, 24 kbit/s: klein, fuer Sprache klar genug
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ac", "1", "-ar", "24000", "-codec:a", "libmp3lame", "-b:a", "24k", tmp], check=True)
    os.replace(tmp, out); os.unlink(raw)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    return round(float(d or 0), 1)
def edge_fill(idx, st, extra_texts):
    try: import edge_tts  # noqa
    except Exception: log("edge-tts fehlt"); return 0
    n = 0
    items = [(s, v["vorlesetext"], v.get("id") or v.get("generated_at")) for s, v in st.items() if v.get("vorlesetext")]
    for s, text, vid in items:
        e = idx["stocks"].get(s)
        if e and (e.get("th") == th(text) or e.get("hash") == thash(text)) and os.path.exists(os.path.join(AUD, e["file"])): continue
        try:
            dur = edge_mp3(text, os.path.join(AUD, fname(s)))
            idx["stocks"][s] = {"file": fname(s), "hash": th(EDGE_VOICE + text), "th": th(text), "id": vid, "voice": EDGE_VOICE,
                                "engine": "edge", "dur": dur, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            n += 1; log("%s edge ok (%ss)" % (s, dur))
        except Exception as ex: log("%s edge Fehler: %s" % (s, str(ex)[:150]))
    ex_idx = idx.setdefault("extra", {})
    for k, text in extra_texts.items():
        e = ex_idx.get(k)
        if e and e.get("th") == th(text) and os.path.exists(os.path.join(AUD, e["file"])): continue
        try:
            dur = edge_mp3(text, os.path.join(AUD, "_" + k + ".mp3"))
            ex_idx[k] = {"file": "_" + k + ".mp3", "hash": th(EDGE_VOICE + text), "th": th(text), "voice": EDGE_VOICE, "engine": "edge", "dur": dur}
            n += 1; log("%s edge ok" % k)
        except Exception as e2: log("%s edge Fehler: %s" % (k, str(e2)[:150]))
    return n
def err_text(e):
    if isinstance(e, urllib.error.HTTPError):
        try: msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception: msg = ""
        return e.code, "HTTP %s %s" % (e.code, msg[:200])
    return 0, str(e)[:200]
def tts(model, text, key):
    body = {"contents": [{"parts": [{"text": STYLE + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}}}}
    req = urllib.request.Request("%s/models/%s:generateContent" % (API, model), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=180) as r: d = json.loads(r.read())
    for p in ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
        if p.get("inlineData", {}).get("data"): return base64.b64decode(p["inlineData"]["data"])
    raise ValueError("keine Audiodaten")
def to_mp3(pcm, out):
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f: f.write(pcm); src = f.name
    tmp = out + ".tmp.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", src,
                    "-codec:a", "libmp3lame", "-b:a", "48k", tmp], check=True)
    os.replace(tmp, out); os.unlink(src)
    return round(len(pcm) / 48000.0, 1)
def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    mx = int(os.environ.get("TTS_MAX_CALLS", "3")); pause = float(os.environ.get("TTS_PAUSE", "25"))
    try: ai = json.load(open(os.path.join(ROOT, "data", "ai.json")))
    except Exception: log("keine ai.json"); return
    os.makedirs(AUD, exist_ok=True)
    try: idx = json.load(open(IDX))
    except Exception: idx = {"voice": VOICE, "stocks": {}}
    st = ai.get("stocks") or {}
    jobs = [s for s, v in st.items() if v.get("vorlesetext") and
            (idx["stocks"].get(s, {}).get("hash") != thash(v["vorlesetext"]) or not os.path.exists(os.path.join(AUD, fname(s))))]
    jobs = [s for s in jobs if not (idx["stocks"].get(s, {}).get("th") == th(st[s]["vorlesetext"]) and os.path.exists(os.path.join(AUD, fname(s))))]
    log("%d faellig, max %d Gemini-Aufrufe" % (len(jobs), mx))
    if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode: log("ffmpeg fehlt"); return
    calls, model, status = 0, None, idx.get("status", "")
    if not key: log("kein GEMINI_API_KEY"); jobs = []
    elif time.time() < idx.get("quota_until", 0): log("Gemini-Kontingent-Pause bis", time.strftime("%H:%MZ", time.gmtime(idx["quota_until"]))); jobs = []
    for s in jobs:
        if calls >= mx: break
        v = st[s]; text = v["vorlesetext"]; ok = False
        for m in ([model] if model else MODELS):
            if calls: time.sleep(pause)
            calls += 1
            try:
                dur = to_mp3(tts(m, text, key), os.path.join(AUD, fname(s)))
                idx["stocks"][s] = {"file": fname(s), "hash": thash(text), "th": th(text), "engine": "gemini", "id": v.get("id") or v.get("generated_at"),
                                    "voice": VOICE, "model": m, "dur": dur, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                model, ok, status = m, True, "ok"; log("%s ok (%s, %ss)" % (s, m, dur)); break
            except Exception as e:
                code, t = err_text(e); log("%s %s: %s" % (s, m, t))
                if code == 429: status = "quota: " + t; idx["quota_until"] = time.time() + 3600; break
        if not ok and status.startswith("quota"): log("Kontingent erschoepft, Abbruch (alte Audios bleiben)"); break
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import podcast
    ne = edge_fill(idx, st, {"intro": podcast.intro_text(podcast.count_segments()), "outro": podcast.OUTRO})
    log("edge-tts: %d neu" % ne)
    idx.update({"voice": VOICE, "status": status, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    for s in list(idx["stocks"]):
        if s not in st: idx["stocks"].pop(s)
    json.dump(idx, open(IDX, "w"), ensure_ascii=False, indent=1)
    log("fertig: %d Aufrufe, %d Audios vorhanden" % (calls, len(idx["stocks"])))
if __name__ == "__main__":
    try: main()
    except Exception as e: log("Fehler:", str(e)[:200]); sys.exit(0)
