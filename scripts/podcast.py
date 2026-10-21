#!/usr/bin/env python3
"""Baut data/podcast.json: ein durchgehender deutscher Podcast ueber alle Aktien, OHNE zusaetzliche KI-Aufrufe.
Segmente = vorlesetext aus data/ai.json (nur Gesammeltes, nichts erfunden). Audio: vorhandene Gemini-MP3 je Aktie
(data/audio/index.json), nur wenn sie genau zum aktuellen Text passt; sonst liest die App mit der Geraetestimme."""
import json, os, re, sys, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(p, d):
    try: return json.load(open(os.path.join(ROOT, p), encoding="utf-8"))
    except Exception: return d
def thash(voice, t): return hashlib.sha1((voice + "|" + t).encode()).hexdigest()[:16]
def with_name(name, text):
    """Namen am Anfang und in laengeren Texten in der Mitte nochmals nennen."""
    t = text.strip()
    if not t.lower().startswith(name.lower()): t = name + ": " + t
    sents = [x for x in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ„\"])", t) if x.strip()] or [t]
    if len(t.split()) > 150 and len(sents) > 5 and "zurück zu " + name.lower() not in t.lower():
        mid = len(sents) // 2
        sents[mid] = "Zurück zu " + name + ": " + sents[mid].strip()
        t = " ".join(x.strip() for x in sents)
    return re.sub(r"\s+", " ", t)
def main():
    wl = load("watchlist.json", {}); ai = load("data/ai.json", {}); au = load("data/audio/index.json", {})
    st = ai.get("stocks") or {}; voice = au.get("voice") or "Kore"; aus = au.get("stocks") or {}
    segs = []
    for s in wl.get("stocks", []):
        a = st.get(s["symbol"])
        if not a or not a.get("vorlesetext"): continue
        txt = a["vorlesetext"]; name = s.get("name") or s["symbol"]
        seg = {"symbol": s["symbol"], "name": name, "text": with_name(name, txt), "id": a.get("id"), "generated_at": a.get("generated_at")}
        x = aus.get(s["symbol"])
        if x and x.get("hash") == thash(x.get("voice") or voice, txt) and os.path.exists(os.path.join(ROOT, "data", "audio", x["file"])):
            seg["audio"] = {"file": x["file"], "hash": x["hash"], "dur": x.get("dur")}
        segs.append(seg)
    g = time.gmtime(); mon = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"]
    day = "%d. %s %d" % (g.tm_mday, mon[g.tm_mon - 1], g.tm_year)
    doc = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "intro": "Willkommen beim Aktien-Radar, deinem Überblick über die neuesten Meldungen. Heute geht es um %d Aktien aus deiner Liste. Alles stammt aus den gesammelten Meldungen und Analystendaten, nichts ist erfunden. Keine Anlageberatung." % len(segs),
           "outro": "Das war der Aktien-Radar-Überblick. Die Quellen und Details findest du in der App bei jeder Aktie. Keine Anlageberatung.",
           "segments": segs, "with_audio": sum(1 for x in segs if x.get("audio"))}
    with open(os.path.join(ROOT, "data", "podcast.json"), "w", encoding="utf-8") as f: json.dump(doc, f, ensure_ascii=False, indent=1)
    print("Podcast: %d Segmente, %d mit Gemini-Stimme" % (len(segs), doc["with_audio"]))
if __name__ == "__main__": main()
