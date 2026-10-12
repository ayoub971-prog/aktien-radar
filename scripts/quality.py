"""Quellen-Qualitaet: 3 = seriös/Primärquelle, 2 = solide Finanzportale, 1 = unbekannt, 0 = aussortieren."""
import re
TOP = ["reuters", "bloomberg", "cnbc", "wall street journal", "wsj", "financial times", "ft.com", "handelszeitung",
       "finews", "finanz und wirtschaft", "fuw", "nzz", "neue zürcher", "barron", "marketwatch", "handelsblatt",
       "associated press", "ap news", "the economist", "pr newswire", "prnewswire", "globenewswire", "business wire",
       "businesswire", "sec.gov", "investor's business daily", "morningstar", "cash", "awp", "srf", "tages-anzeiger",
       "frankfurter allgemeine", "faz", "spiegel", "nikkei", "the information", "axios", "new york times", "nytimes",
       "the verge", "techcrunch", "fortune", "forbes", "dpa", "welt", "süddeutsche", "boerse-frankfurt", "six group",
       "the globe and mail", "investrends", "agefi", "le temps", "bilanz"]
MID = ["yahoo", "finanzen.ch", "finanzen.net", "finanzen.at", "marketscreener", "investing.com", "der aktionär",
       "börse online", "onvista", "thestreet", "seeking alpha", "boerse.de", "finanznachrichten", "ariva",
       "wallstreet online", "wallstreet-online", "marketbeat", "barchart", "fxstreet", "aol", "economic times",
       "livemint", "moneycontrol", "smh.com.au", "euronews", "asia times", "tradingview", "extraetf", "stock3",
       "investmentweek", "business insider", "the motley"]  # 'the motley' wird unten vorher aussortiert
BAD = ["motley fool", "fool.com", "investorplace", "zacks", "benzinga", "simply wall", "stocktwits", "insider monkey",
       "24/7 wall", "ad-hoc-news", "ad hoc news", "finanztrends", "börse express", "aktien.news", "börse global",
       "kapitalmarktexperten", "tradingkey", "tikr", "vietnam.vn", "laodong", "biggo", "pluang", "facebook",
       "crypto", "coin", "tokenpost", "beincrypto", "okx", "gurufocus", "kalkine", "invezz", "bbn times", "techi",
       "startup fortune", "briefs finance", "twelfth magpie", "stocks down under", "tipranks", "moomoo", "富途",
       "hdfc sky", "markets.com", "tmgm", "sharewise", "dark side of the boom", "unisba", "tech-insider",
       "techgraph", "inkl", "beinsure", "dwn", "deutsche wirtschaftsnachrichten", "foreign policy journal",
       "kapitalmarkt", "aktiencheck", "4investors", "chartanalyse", "penny", "ainvest", "247wallst", "kiplinger",
       "nasdaq.com", "investorsobserver", "marketbeat", "newsbreak", "msn"]
# Clickbait-Titel
BAIT = re.compile(r"(\b(should you|is it too late|buy now|millionaire|could make you|\d+ (stocks?|reasons)|"
                  r"no-brainer|forever|soar \d+%|before it|retire|passive income|jetzt kaufen|kaufen\?!|"
                  r"geheimtipp|vervielfach|explodier|rakete|kursrakete|turbo|millionär|unglaublich|schock)\b)", re.I)
JUNK = re.compile(r"stock price, news, quote|interactive stock chart|advanced charts|research & ratings|holdings list|"
                  r"\b(put|call) \([A-Z0-9]+\)|\(acc\)|kurs \| dividende|stock forecasts|tokenized stock|"
                  r"return on assets|stock quote|price history|best stock to|stocks to (own|buy)|little-known|"
                  r"\binvestors? (who|with) (lost|losses)|class action|deadline:|urges .* investors|law firm|"
                  r"(rosen|pomerantz|bronstein|levi & korsinsky|faruqi|schall)", re.I)
NONLATIN = re.compile(r"[\u0400-\u04ff\u0590-\u06ff\u0e00-\u0e7f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")

def source_quality(src):
    s = (src or "").lower()
    if any(b in s for b in BAD):
        return 0
    if any(t in s for t in TOP):
        return 3
    if any(m in s for m in MID):
        return 2
    return 1

def item_quality(item):
    t = item.get("title") or ""
    if NONLATIN.search(t) or NONLATIN.search(item.get("source") or ""):
        return 0
    q = source_quality(item.get("source"))
    if q and (BAIT.search(t) or JUNK.search(t)):
        return 0
    return q
