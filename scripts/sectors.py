"""Zuordnung Yahoo-/GICS-Sektoren zu den Sektoren der App."""
def map_sector(sector, industry="", quote_type=""):
    s = (sector or "").lower(); i = (industry or "").lower(); q = (quote_type or "").upper()
    if q in ("ETF", "INDEX", "MUTUALFUND"):
        return "ETFs/Indizes"
    if "semiconductor" in i or "computer hardware" in i or "electronic component" in i or "communication equipment" in i or "technology hardware" in i:
        return "Halbleiter/Hardware"
    if s in ("technology", "information technology"):
        return "Software/KI"
    if s in ("communication services", "consumer cyclical", "consumer defensive", "consumer discretionary", "consumer staples"):
        return "Konsum/Internet"
    if s in ("energy", "utilities"):
        return "Energie"
    if s == "industrials":
        return "Industrie/Luftfahrt"
    if s in ("financial services", "financials"):
        return "Finanzen"
    if s in ("basic materials", "materials"):
        return "Rohstoffe/Gold"
    if s in ("healthcare", "health care"):
        return "Gesundheit"
    return "Sonstige"
