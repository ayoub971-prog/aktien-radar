"""Insider-Geschaefte aus SEC Form 4 (EDGAR, kostenlos). Nur US-gelistete Firmen mit CIK.
Pro Einreichung einmal geladen und in data/insider.json zwischengespeichert. Routine (Optionsausuebung, Steuer-Einbehalt,
Zuteilung, Schenkung) wird gekennzeichnet; echte Kaeufe (P) und Verkaeufe (S) sind die relevanten."""
import json, os, re, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import timedelta
CODES = {"P": ("Kauf", True), "S": ("Verkauf", True), "M": ("Optionsausübung", False), "X": ("Optionsausübung", False),
         "F": ("Steuer-Einbehalt (Aktien zur Steuerzahlung abgegeben)", False), "A": ("Zuteilung (Vergütung)", False),
         "G": ("Schenkung", False), "C": ("Umwandlung", False), "D": ("Rückgabe an die Firma", False)}
def _t(e, path):
    x = e.find(path); return (x.text or "").strip() if x is not None and x.text else ""
def role(rel):
    t = _t(rel, "officerTitle"); r = []
    tl = t.lower()
    if re.fullmatch(r"(president,? (and|&) )?(chief executive officer|ceo)(,? (and|&) president)?", tl): r.append("Chef (CEO)")
    elif re.fullmatch(r"chairman,? (and|&) (ceo|chief executive officer)", tl): r.append("Präsident und Chef (CEO)")
    elif re.search(r"chief financial officer", tl) or tl == "cfo": r.append("Finanzchef (CFO)")
    elif t and tl not in ("see remarks", "see remarks below"): r.append(t)
    elif _t(rel, "isOfficer") in ("1", "true"): r.append("Manager")
    if _t(rel, "isDirector") in ("1", "true"): r.append("Verwaltungsrat")
    if _t(rel, "isTenPercentOwner") in ("1", "true"): r.append("Grossaktionär (über 10 %)")
    return ", ".join(r) or "Insider"
def name_fmt(n):
    p = n.split()
    if len(p) >= 2: p = p[1:] + p[:1]   # SEC: "COOK TIMOTHY D" -> "Timothy D Cook"
    return " ".join(w.capitalize() if w.isupper() and len(w) > 1 else w for w in p)
def parse(xml):
    root = ET.fromstring(xml)
    own = root.find("reportingOwner")
    who = name_fmt(_t(own, "reportingOwnerId/rptOwnerName")) if own is not None else "?"
    rl = role(own.find("reportingOwnerRelationship")) if own is not None and own.find("reportingOwnerRelationship") is not None else "Insider"
    plan = _t(root, "aff10b5One") in ("1", "true") or "10b5-1" in xml
    agg = {}
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        c = _t(tx, "transactionCoding/transactionCode")
        try: sh = float(_t(tx, "transactionAmounts/transactionShares/value") or 0)
        except ValueError: sh = 0
        try: pr = float(_t(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError: pr = 0
        d = _t(tx, "transactionDate/value")[:10]
        a = agg.setdefault(c, {"code": c, "shares": 0, "value": 0, "date": d})
        a["shares"] += sh; a["value"] += sh * pr; a["date"] = max(a["date"], d)
    out = []
    for c, a in agg.items():
        lab, rel = CODES.get(c, ("Sonstiges (%s)" % c, False))
        out.append({"wer": who, "rolle": rl, "art": lab, "code": c, "relevant": rel, "aktien": int(round(a["shares"])),
                    "wert": int(round(a["value"])), "datum": a["date"], "plan_10b5_1": bool(plan and c == "S")})
    return out
def run(stocks, subs, path, now, log=print, max_new=80):
    """subs: {sym: (cik, recent)} aus official.sec_items"""
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    try: cache = json.load(open(path, encoding="utf-8"))
    except Exception: cache = {}
    forms = cache.get("forms", {}); res = {}; new = 0
    cutoff = (now - timedelta(days=120)).strftime("%Y-%m-%d")
    for s in stocks:
        sym = s["symbol"]
        if sym not in subs: continue
        cik, rc = subs[sym]; lst = []; n = 0
        for i in range(len(rc["form"])):
            if rc["filingDate"][i] < cutoff: break
            if rc["form"][i] != "4": continue
            n += 1
            if n > 25: break
            acc = rc["accessionNumber"][i]
            if acc not in forms:
                if new >= max_new or "@" not in ua: continue
                doc = re.sub(r"^xsl[^/]*/", "", rc["primaryDocument"][i])
                url = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (cik, acc.replace("-", ""), doc)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
                    with urllib.request.urlopen(req, timeout=25) as r: forms[acc] = {"tx": parse(r.read().decode("utf-8", "replace")), "filed": rc["filingDate"][i]}
                except Exception as e:
                    log("Insider FEHLER %s %s" % (sym, str(e)[:80])); forms[acc] = {"tx": [], "filed": rc["filingDate"][i], "err": 1}
                new += 1; time.sleep(0.12)
            link = "https://www.sec.gov/Archives/edgar/data/%d/%s/" % (cik, acc.replace("-", ""))
            for t in forms[acc]["tx"]: lst.append(dict(t, link=link, gemeldet=forms[acc]["filed"]))
        lst.sort(key=lambda t: (t["datum"], t["relevant"]), reverse=True)
        res[sym] = lst[:30]
    keep = {a for a in forms if forms[a].get("filed", "") >= cutoff}
    cache = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "SEC EDGAR Form 4", "forms": {a: forms[a] for a in keep}}
    with open(path, "w", encoding="utf-8") as f: json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    log("Insider: %d neue Form-4, %d Aktien" % (new, len(res)))
    return res
