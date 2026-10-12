"""Titel automatisch ins Deutsche (Google-Translate-Web-Endpunkt, ohne Schluessel). Cache in data/translations.json.
Faellt die Uebersetzung aus, bleibt der Originaltitel."""
import json, os, time, urllib.request, urllib.parse
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def _batch(texts):
    data = urllib.parse.urlencode([("q", t) for t in texts]).encode()
    req = urllib.request.Request("https://translate.googleapis.com/translate_a/t?client=gtx&sl=auto&tl=de&format=text", data=data,
                                 headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read())
    out = []
    for x in res:
        if isinstance(x, list): out.append((x[0], x[1] if len(x) > 1 else None))
        else: out.append((x, None))
    if len(out) != len(texts): raise RuntimeError("Antwortlaenge passt nicht")
    return out

def translate_all(texts, path, log=print):
    cache = {}
    try:
        with open(path, encoding="utf-8") as f: cache = json.load(f)
    except Exception: pass
    todo = [t for t in dict.fromkeys(texts) if t and t not in cache]
    ok = fail = 0; i = 0; bs = 40
    while i < len(todo):
        chunk = todo[i:i + bs]
        try:
            for src, (de, lang) in zip(chunk, _batch(chunk)):
                cache[src] = src if lang == "de" else de; ok += 1
        except Exception as e:
            fail += len(chunk); log("Uebersetzung FEHLER: %s" % e)
            if fail > 200: break
            time.sleep(2)
        i += bs; time.sleep(0.4)
    keep = set(texts)
    cache = {k: v for k, v in cache.items() if k in keep}
    with open(path, "w", encoding="utf-8") as f: json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    log("Uebersetzung: %d neu, %d Fehler, %d im Cache" % (ok, fail, len(cache)))
    return cache
