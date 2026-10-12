"""Offizielle Quellen: SEC-EDGAR-Einreichungen und Firmen-Medienmitteilungen (Google-News-Index der Firmen-Domain).
Kostenlos, ohne Schluessel. SEC verlangt einen User-Agent mit Kontakt-E-Mail: Umgebungsvariable SEC_USER_AGENT."""
import json, os, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

CIK = {"TSM": 1046179, "ASML": 937966, "ARM": 1973239, "MSFT": 789019, "AVGO": 1730168, "INTC": 50863, "PLTR": 1321655,
       "IBM": 51143, "NOW": 1373715, "META": 1326801, "AMZN": 1018724, "MRVL": 1835632, "GLW": 24741, "AMAT": 6951,
       "HOOD": 1783879, "BE": 1664703, "HYLN": 1759631, "OKLO": 1849056, "GEV": 1996810, "GE": 40545, "BRK-B": 1067983,
       "013A.F": 1549802, "UBSG.SW": 1610520}
FORMS = {"8-K": "Wichtige Mitteilung (8-K)", "10-Q": "Quartalsbericht (10-Q)", "10-K": "Jahresbericht (10-K)",
         "6-K": "Mitteilung ausländischer Firma (6-K)", "20-F": "Jahresbericht ausländischer Firma (20-F)",
         "8-K/A": "Wichtige Mitteilung, korrigiert (8-K/A)", "10-Q/A": "Quartalsbericht, korrigiert (10-Q/A)"}
ITEMS_8K = {"1.01": "wichtiger Vertrag", "2.02": "Geschäftszahlen", "2.01": "Kauf/Verkauf von Firmenteilen", "5.02": "Wechsel im Management",
            "7.01": "Information an Investoren", "8.01": "sonstige wichtige Ereignisse", "5.07": "Abstimmung Generalversammlung",
            "2.05": "Restrukturierung", "1.02": "Vertrag beendet", "2.03": "neue Finanzierung/Schulden", "3.02": "Aktienverkauf", "5.03": "Statutenänderung"}
IR = {"TSM": "pr.tsmc.com", "UBSG.SW": "ubs.com/global/en/media", "ASML": "asml.com/en/news/press-releases",
      "BKW.SW": "bkw.ch/de/ueber-uns/aktuell/medien", "005930.KS": "news.samsung.com/global", "MSFT": "news.microsoft.com",
      "AVGO": "investors.broadcom.com/news-releases", "INTC": "intc.com/news-events/press-releases", "PLTR": "investors.palantir.com/news-details",
      "IBM": "newsroom.ibm.com", "NOW": "newsroom.servicenow.com", "META": "about.fb.com/news", "AMZN": "aboutamazon.com/news/company-news",
      "MRVL": "investor.marvell.com/news-events/press-releases", "SFTBY": "group.softbank/en/news/press", "GLW": "investor.corning.com/news-releases",
      "AMAT": "ir.appliedmaterials.com/news-releases", "ARM": "newsroom.arm.com/news", "HOOD": "newsroom.aboutrobinhood.com",
      "BE": "investor.bloomenergy.com/press-releases", "HYLN": "investors.hyliion.com/news-releases",
      "SMEGF": "siemens-energy.com/global/en/home/press-releases", "OKLO": "oklo.com/newsroom", "RYCEY": "rolls-royce.com/media/press-releases",
      "GEV": "gevernova.com/news/press-releases", "GE": "geaerospace.com/news/press-releases", "013A.F": "ir.jd.com/news-releases",
      "BRK-B": "berkshirehathaway.com/news", "HY9H.MU": "news.skhynix.com"}
import re as _re
JUNK = _re.compile(r"career|\bjobs?\b|engineer|manager|specialist|technician|intern|co-op|archives?|page \d+ of|products? >|"
                   r"\b(shop|deals?|off plus|% off)\b|^investor relations$|^news( releases)?$|^press releases?$|^newsroom|all the latest news|"
                   r"^tag >|^events\b|details$|cookie|privacy|contact us|in [A-Z][a-z]+, [A-Z][a-z]+, (United States|Vereinigte)", _re.I)

def iso(dt): return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def sec_items(stocks, now, log=print):
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        return [], [{"symbol": "*", "what": "official", "error": "SEC_USER_AGENT fehlt (SEC verlangt Kontakt-E-Mail)"}]
    out, errs = [], []
    cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    for s in stocks:
        sym = s["symbol"]; cik = CIK.get(sym)
        if not cik: continue
        try:
            req = urllib.request.Request("https://data.sec.gov/submissions/CIK%010d.json" % cik, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=25) as r: d = json.loads(r.read())
            rc = d["filings"]["recent"]; n = 0
            for i in range(len(rc["form"])):
                f = rc["form"][i]
                if rc["filingDate"][i] < cutoff: break
                if f not in FORMS: continue
                acc = rc["accessionNumber"][i]; doc = rc["primaryDocument"][i]
                t = rc.get("acceptanceDateTime", [""] * 99)[i] or rc["filingDate"][i] + "T12:00:00.000Z"
                dt = datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                label = FORMS[f]
                its = [ITEMS_8K[x.strip()] for x in (rc.get("items", [""] * 99)[i] or "").split(",") if x.strip() in ITEMS_8K]
                desc = (rc.get("primaryDocDescription", [""] * 99)[i] or "").strip()
                title = "%s: %s" % (s.get("name", sym), label) + (" – " + ", ".join(dict.fromkeys(its)) if its else "")
                link = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (cik, acc.replace("-", ""), doc)
                out.append({"title": title, "title_de": title, "link": link, "source": "SEC EDGAR", "published": iso(dt),
                            "via": "sec", "symbols": [sym], "official": "sec", "form": f, "desc": desc})
                n += 1
                if n >= 6: break
            log("SEC        %-10s %d Einreichungen" % (sym, n))
        except Exception as e:
            errs.append({"symbol": sym, "what": "official", "error": "SEC: %s" % e}); log("SEC FEHLER %-10s %s" % (sym, e))
        time.sleep(0.15)   # SEC: max. 10 Anfragen/Sek.
    return out, errs

def ir_items(stocks, gnews, log=print):
    out, errs = [], []
    for s in stocks:
        sym = s["symbol"]; dom = IR.get(sym)
        if not dom: continue
        try:
            items = gnews("site:" + dom, "en", "30d")
            host = dom.split("/")[0]
            n = 0
            for i in sorted(items, key=lambda x: x["published"], reverse=True):
                src = (i.get("source") or "")
                t = i["title"]
                if "|" in t and len(t.split("|")[0].strip()) >= 20: t = t.split("|")[0].strip(); i = dict(i); i["title"] = t
                if len(t) < 20 or JUNK.search(t) or "career" in src.lower(): continue
                i = dict(i); i.update({"via": "ir", "symbols": [sym], "official": "ir", "source": src or host})
                out.append(i); n += 1
                if n >= 6: break
            log("IR         %-10s %d Mitteilungen (%s)" % (sym, n, dom))
        except Exception as e:
            errs.append({"symbol": sym, "what": "official", "error": "IR %s: %s" % (dom, e)})
    return out, errs
