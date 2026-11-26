"""Je Titel: Eulerpool-Daten holen, auswerten, auf Plausibilität prüfen."""

import logging
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger("depot_daten.titles")

# Yahoo-Symbol → ISIN. Unbekannte Titel löst die App per Eulerpool-Suche auf.
ISIN = {
    "NVDA": "US67066G1040", "MSFT": "US5949181045", "AAPL": "US0378331005", "AMZN": "US0231351067",
    "TSLA": "US88160R1014", "NET": "US18915M1071", "INTC": "US4581401001", "BKNG": "US09857L1089",
    "SAP.DE": "DE0007164600", "HEI.DE": "DE0006047004", "BAYN.DE": "DE000BAY0017",
    "MSTR": "US5949724083", "GOOGL": "US02079K3059", "GOOG": "US02079K1079", "BRK-B": "US0846707026",
    "NKE": "US6541061031", "RKLB": "US7731211089", "META": "US30303M1027",
}
# Ohne Eulerpool-Daten: nicht börsennotiert oder kein Aktien-Titel
SKIP = {"ANT": "nicht börsennotiert", "SPCX": "nicht börsennotiert", "WTIC.DE": "Rohstoff-ETC"}

STALE_DAYS = 120
# US-ADR deutscher Titel (Ersatz, wenn das Kursziel der Heimatbörse veraltet ist)
ADR_TICKER = {"SAP.DE": "SAP", "BAYN.DE": "BAYRY", "HEI.DE": "HDELY", "SIE.DE": "SIEGY", "ALV.DE": "ALIZY",
              "BAS.DE": "BASFY", "DTE.DE": "DTEGY", "MBG.DE": "MBGYY", "BMW.DE": "BMWYY", "VOW3.DE": "VWAGY",
              "IFX.DE": "IFNNY", "ADS.DE": "ADDYY", "RHM.DE": "RNMBY", "MUV2.DE": "MURGY"}
CUR_SIGN = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF"}


# ---------- kleine Helfer ----------

def to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 1e11 else v
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v)
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN raus


def lst(data, key=None):
    if isinstance(data, dict) and key:
        data = data.get(key)
    return data if isinstance(data, list) else []


def de(x, nd=0):
    """Zahl deutsch formatiert."""
    if x is None:
        return "–"
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, nd=0, sign=True):
    if x is None:
        return "–"
    s = de(abs(x), nd)
    if not sign:
        return s
    return ("+" if x >= 0 else "−") + s


def ddmm(d):
    return d.strftime("%d.%m.") if d else "–"


def ddmmyy(d):
    return d.strftime("%d.%m.%y") if d else "–"


def listing_currency(isin, fallback):
    if isin.startswith("US"):
        return "USD"
    if isin[:2] in ("DE", "FR", "NL", "IT", "ES", "AT", "FI", "BE", "IE"):
        return "EUR"
    return fallback or "USD"


# ---------- Auswertung der einzelnen Abrufe ----------

def latest_reco(recs):
    rows = [r for r in lst(recs) if isinstance(r, dict) and to_date(r.get("period"))]
    rows.sort(key=lambda r: to_date(r["period"]), reverse=True)
    return rows[0] if rows else None, rows[1] if len(rows) > 1 else None


def consensus(r):
    if not r:
        return None
    sb, b, h, s, ss = (int(num(r.get(k)) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
    n = sb + b + h + s + ss
    if not n:
        return None
    score = (5 * sb + 4 * b + 3 * h + 2 * s + 1 * ss) / n
    label = ("Starker Kauf" if score >= 4.5 else "Kaufen" if score >= 3.5 else
             "Halten" if score >= 2.5 else "Verkaufen")
    return {"label": label, "score": round(score, 2), "anzahl": n,
            "stark_kaufen": sb, "kaufen": b, "halten": h, "verkaufen": s, "stark_verkaufen": ss,
            "monat": str(r.get("period"))[:7]}


def main_target(t):
    """Median ist robuster gegen Ausreißer als der Durchschnitt."""
    if not t:
        return None
    return t.get("median") or t.get("mean")


def target_from(pt, reco):
    """Kursziel aus price-target, sonst aus recommendations."""
    t = {}
    if isinstance(pt, dict) and num(pt.get("target_mean")):
        t = {"mean": num(pt.get("target_mean")), "median": num(pt.get("target_median")),
             "high": num(pt.get("target_high")), "low": num(pt.get("target_low")),
             "anzahl": int(num(pt.get("num_analysts")) or 0) or None, "stand": to_date(pt.get("last_updated"))}
    elif reco and num(reco.get("targetMean")):
        t = {"mean": num(reco.get("targetMean")), "median": num(reco.get("targetMedian")),
             "high": num(reco.get("targetHigh")), "low": num(reco.get("targetLow")),
             "anzahl": None, "stand": to_date(reco.get("lastUpdated") or reco.get("period"))}
    return t or None


def quotes_info(q):
    rows = [(to_date(r.get("timestamp")), num(r.get("price"))) for r in lst(q) if isinstance(r, dict)]
    rows = [(d, p) for d, p in rows if d and p]
    if not rows:
        return {}
    rows.sort()
    last_d, last_p = rows[-1]
    year = [p for d, p in rows if d >= last_d - timedelta(days=365)]
    return {"kurs": last_p, "kurs_stand": last_d, "hoch_52w": max(year), "tief_52w": min(year)}


def eps_info(est, cal, today):
    out = {}
    # Erwarteter Gewinn: Geschäftsjahresende = Monat/Tag der fernsten Schätzung
    rows = [r for r in lst(est) if isinstance(r, dict) and to_date(r.get("period"))]
    if rows:
        far = max(to_date(r["period"]) for r in rows)
        annual = sorted((r for r in rows if to_date(r["period"]).strftime("%m-%d")[:2] == far.strftime("%m")),
                        key=lambda r: to_date(r["period"]))
        nxt = [r for r in annual if to_date(r["period"]) > today and num(r.get("epsEstimate"))]
        if nxt:
            r = nxt[0]
            # Endet das laufende Geschäftsjahr in < 3 Monaten, das folgende nehmen
            if (to_date(r["period"]) - today).days < 90 and len(nxt) > 1:
                r = nxt[1]
            out["eps_erwartet"] = num(r.get("epsEstimate"))
            out["eps_erwartet_gj"] = to_date(r["period"]).year
            out["eps_analysten"] = int(num(r.get("epsAnalysts")) or 0) or None
            out["umsatz_erwartet"] = num(r.get("revenueEstimate"))
    # Quartale: letzte vier Ist-Werte, nächster Termin
    q = [r for r in lst(cal) if isinstance(r, dict) and to_date(r.get("date"))]
    q.sort(key=lambda r: to_date(r["date"]))
    done = [r for r in q if num(r.get("epsActual")) is not None and to_date(r["date"]) <= today]
    # Eulerpool führt manche Quartale doppelt (z. B. vorläufig + endgültig): rückwärts nur Termine
    # nehmen, die mindestens 60 Tage auseinanderliegen
    quarters = []
    for r in reversed(done):
        if not quarters or (to_date(quarters[-1]["date"]) - to_date(r["date"])).days >= 60:
            quarters.append(r)
        if len(quarters) == 4:
            break
    if len(quarters) == 4 and (to_date(quarters[0]["date"]) - to_date(quarters[3]["date"])).days <= 400:
        out["eps_ttm"] = sum(num(r["epsActual"]) for r in quarters)
    if done:
        r = done[-1]
        act, est_ = num(r.get("epsActual")), num(r.get("epsEstimate"))
        out["letzte_zahlen"] = {
            "datum": to_date(r["date"]).isoformat(), "eps": act, "eps_erwartet": est_,
            "ueberraschung_pct": round((act / est_ - 1) * 100, 1) if act is not None and est_ else None}
    upcoming = [r for r in q if to_date(r["date"]) >= today]
    if upcoming:
        r = upcoming[0]
        out["naechste_zahlen"] = to_date(r["date"]).isoformat()
        out["naechste_zahlen_eps_erwartet"] = num(r.get("epsEstimate"))
    return out


def short_info(si, fl):
    rows = [r for r in lst(si) if isinstance(r, dict) and to_date(r.get("settlement_date") or r.get("settlementDate"))]
    if not rows:
        return {}
    rows.sort(key=lambda r: to_date(r.get("settlement_date") or r.get("settlementDate")), reverse=True)
    r = rows[0]
    shares = num(r.get("short_shares") or r.get("shortShares"))
    out = {"short_stand": to_date(r.get("settlement_date") or r.get("settlementDate")).isoformat(),
           "short_aktien": shares,
           "short_tage": num(r.get("days_to_cover") or r.get("daysToCover")),
           "short_aenderung_pct": num(r.get("change_pct") or r.get("changePct"))}
    flt = None
    if isinstance(fl, dict):
        flt = num((fl.get("latest") or {}).get("float_shares"))
    if shares and flt:
        out["short_quote_pct"] = round(shares / flt * 100, 2)
    return out


def insider_us(data, today):
    rows = lst(data, "data")
    cut = today - timedelta(days=90)
    buys = sells = 0
    vol = 0.0
    last = []
    for r in rows:
        d = to_date(r.get("transactionDate") or r.get("filingDate"))
        if not d or d < cut:
            continue
        sh = num(r.get("shares")) or 0
        v = num(r.get("volume")) or 0
        if sh > 0:
            buys += 1
        elif sh < 0:
            sells += 1
        vol += v
        last.append((d, f"{ddmm(d)} {r.get('name', '?')}: {'Kauf' if sh > 0 else 'Verkauf'} {de(abs(v) / 1e6, 1)} Mio."))
    last.sort(reverse=True)
    return {"insider_kaeufe_90t": buys, "insider_verkaeufe_90t": sells,
            "insider_saldo_90t_mio": round(vol / 1e6, 2), "insider_letzte": [s for _, s in last[:3]]}


def insider_eu(data, today):
    rows = lst(data)
    cut = today - timedelta(days=90)
    buys = sells = 0
    last = []
    for r in rows:
        d = to_date(r.get("transaction_date") or r.get("publication_date"))
        if not d or d < cut:
            continue
        t = str(r.get("transaction_type") or "").lower()
        is_buy = any(w in t for w in ("kauf", "buy", "purchase", "erwerb")) and "verkauf" not in t
        is_sell = any(w in t for w in ("verkauf", "sell", "sale", "veräußer"))
        if is_buy:
            buys += 1
        elif is_sell:
            sells += 1
        vol = num(r.get("volume"))
        last.append((d, f"{ddmm(d)} {r.get('person_name', '?')} ({r.get('position', '')}): "
                        f"{'Kauf' if is_buy else 'Verkauf' if is_sell else t or '?'}"
                        + (f" {de(vol / 1e6, 2)} Mio." if vol else "")))
    last.sort(reverse=True)
    return {"insider_kaeufe_90t": buys, "insider_verkaeufe_90t": sells, "insider_letzte": [s for _, s in last[:3]]}


def grades_info(data, today):
    rows = [r for r in lst(data) if isinstance(r, dict) and to_date(r.get("date"))]
    rows.sort(key=lambda r: to_date(r["date"]), reverse=True)
    cut = today - timedelta(days=30)
    recent = [r for r in rows if to_date(r["date"]) >= cut]
    up = sum(1 for r in recent if str(r.get("action")).lower() == "upgrade")
    down = sum(1 for r in recent if str(r.get("action")).lower() == "downgrade")
    words = {"upgrade": "hoch", "downgrade": "runter", "initialise": "neu", "init": "neu", "maintain": "bestätigt",
             "reiterated": "bestätigt", "reit": "bestätigt"}
    last = [f"{ddmm(to_date(r['date']))} {r.get('grading_company', '?')}: "
            f"{words.get(str(r.get('action')).lower(), r.get('action', ''))} → {r.get('new_grade', '')}"
            for r in rows[:5]]
    return {"hochstufungen_30t": up, "herabstufungen_30t": down, "einstufungen_letzte": last}


def dividends_info(data, price, today):
    rows = [(to_date(r.get("payDate") or r.get("period")), num(r.get("dividend")), r.get("currency"))
            for r in lst(data) if isinstance(r, dict)]
    rows = [r for r in rows if r[0] and r[1]]
    if not rows:
        return {}
    rows.sort()
    cut = today - timedelta(days=365)
    ttm = sum(v for d, v, _ in rows if cut <= d <= today)
    out = {"dividende_12m": round(ttm, 4) if ttm else None, "letzte_dividende": rows[-1][0].isoformat()}
    if ttm and price:
        out["dividendenrendite_pct"] = round(ttm / price * 100, 2)
    return out


def splits_info(data):
    rows = [(to_date(r.get("date")), num(r.get("fromFactor")), num(r.get("toFactor"))) for r in lst(data)
            if isinstance(r, dict)]
    rows = [r for r in rows if r[0] and r[1] and r[2] and r[1] != r[2]]
    if not rows:
        return None
    rows.sort()
    d, a, b = rows[-1]
    return {"datum": d, "text": f"{ddmmyy(d)} ({de(a)}:{de(b)})"}


def returns_info(pc):
    rows = lst(pc, "data")
    if not rows or not isinstance(rows[0], dict):
        return {}
    r = rows[0]
    return {k_out: round(num(r.get(k_in)), 1) for k_in, k_out in
            (("1M", "1M"), ("3M", "3M"), ("1Y", "1J"), ("3Y", "3J"), ("5Y", "5J"), ("YTD", "lfd_Jahr"))
            if num(r.get(k_in)) is not None}


# ---------- Hauptfunktion je Titel ----------

def resolve_isin(api, t, cache, overrides):
    sym = t.get("symbol") or ""
    if sym in overrides:
        return overrides[sym]
    if sym in ISIN:
        return ISIN[sym]
    if sym in cache:
        return cache[sym]
    base = sym.split(".")[0]
    want = (t.get("long_name") or t.get("name") or "").split(" ")[0].lower()
    st, data = api.get("equity/search", q=base)
    for r in lst(data, "results"):
        if r.get("type") == "stock" and want and str(r.get("name", "")).lower().startswith(want[:5]):
            if sym.endswith(".DE") and not str(r.get("isin", "")).startswith("DE"):
                continue
            cache[sym] = r.get("isin")
            return cache[sym]
    cache[sym] = None
    return None


def adr_target(api, t, cache):
    """Für Nicht-US-Titel mit veraltetem Kursziel: Kursziel-Abstand der US-ADR."""
    key = "ADR:" + (t.get("symbol") or "")
    isin = cache.get(key, "?")
    if isin == "?":
        isin = None
        adr = ADR_TICKER.get(t.get("symbol") or "")
        queries = ([adr] if adr else []) + [(t.get("long_name") or t.get("name") or "").split(" ")[0]]
        for qy in queries:
            _, data = api.get("equity/search", q=qy)
            for r in lst(data, "results"):
                if r.get("currency") == "USD" and str(r.get("isin", "")).startswith("US") and (
                        (adr and str(r.get("ticker", "")).upper() == adr) or "ADR" in str(r.get("name", "")).upper()):
                    isin = r.get("isin")
                    break
            if isin:
                break
        cache[key] = isin
    if not isin:
        return None
    _, pt = api.get(f"equity/price-target/{isin}")
    _, rc = api.get(f"research/recommendations/{isin}")
    _, q = api.get(f"equity/quotes/{isin}")
    reco, prev = latest_reco(rc)
    tg = target_from(pt, reco)
    qi = quotes_info(q)
    if not tg or not qi.get("kurs") or not tg.get("stand"):
        return None
    tg["upside"] = (main_target(tg) / qi["kurs"] - 1) * 100
    tg["ratio"] = {k: (tg[k] / qi["kurs"]) if tg.get(k) else None for k in ("mean", "median", "high", "low")}
    tg["reco"], tg["reco_prev"] = reco, prev
    tg["isin"] = isin
    return tg


def collect(api, t, isin, today):
    """Alle Abrufe für einen Titel. t: dict mit entity, name, symbol, price, currency."""
    us = isin.startswith("US")
    raw = {}
    for key, path in (("pt", f"equity/price-target/{isin}"), ("reco", f"research/recommendations/{isin}"),
                      ("grades", f"equity/analyst-grades/{isin}"), ("est", f"equity/estimates/{isin}"),
                      ("cal", f"equity-extended/earnings-calendar/{isin}"), ("quotes", f"equity/quotes/{isin}"),
                      ("pc", f"equity/price-change/{isin}"), ("div", f"equity/dividends/{isin}"),
                      ("splits", f"equity/splits/{isin}")):
        raw[key] = api.get(path)[1]
    if us:
        raw["ins"] = api.get(f"equity/insider-trades/{isin}")[1]
        raw["si"] = api.get(f"equity-extended/short-interest/{isin}")[1]
        raw["fl"] = api.get(f"equity/shares-float/{isin}")[1]
    else:
        raw["ins"] = api.get(f"equity/insider-trades-eu/{isin}")[1]
    return raw


def evaluate(api, t, isin, raw, cache, today):
    cur = listing_currency(isin, t.get("currency"))
    sign = CUR_SIGN.get(cur, cur)
    qi = quotes_info(raw.get("quotes"))
    ha_price = num(t.get("price")) if (t.get("currency") or cur) == cur else None
    price = ha_price or qi.get("kurs")
    hints = []

    reco, reco_prev = latest_reco(raw.get("reco"))
    cons = consensus(reco)
    tg = target_from(raw.get("pt"), reco)
    tq = "Eulerpool"

    # Kursziel veraltet? → US-ADR als Ersatz (Abstand in %, unabhängig vom ADR-Verhältnis)
    stale = bool(tg and tg.get("stand") and (today - tg["stand"]).days > STALE_DAYS)
    upside = None
    if tg and price:
        upside = (main_target(tg) / price - 1) * 100
    if (stale or not tg) and not isin.startswith("US"):
        adr = adr_target(api, t, cache)
        if adr and (today - adr["stand"]).days <= STALE_DAYS:
            upside = adr["upside"]
            r = adr["ratio"]
            tg = {k: (price * r[k] if price and r.get(k) else None) for k in ("mean", "median", "high", "low")}
            tg.update(anzahl=adr.get("anzahl"), stand=adr["stand"])
            tq = "Eulerpool (US-ADR, umgerechnet)"
            stale = False
            if adr.get("reco"):
                cons = consensus(adr["reco"])
                reco_prev = adr.get("reco_prev")
    if stale:
        hints.append(f"Kursziel veraltet (Stand {ddmmyy(tg['stand'])})")
    info = []
    ret1m = num(((lst(raw.get("pc"), "data") or [{}])[0] or {}).get("1M"))
    if upside is not None and (upside > 80 or upside < -40):
        if ret1m is not None and ((upside > 80 and ret1m < -20) or (upside < -40 and ret1m > 25)):
            info.append(f"Kursziel {pct(upside)} %: Kurs {pct(ret1m)} % in einem Monat, Ziele hinken hinterher")
        else:
            hints.append(f"Kursziel {pct(upside)} % vom Kurs – prüfen")

    sp = splits_info(raw.get("splits"))
    if sp and (today - sp["datum"]).days <= 365:
        if not tg or not tg.get("stand") or tg["stand"] <= sp["datum"] + timedelta(days=30):
            hints.append(f"Split am {sp['text']} – Kursziel prüfen")

    if ha_price and qi.get("kurs") and abs(qi["kurs"] / ha_price - 1) > 0.25:
        hints.append(f"Kurs Eulerpool {de(qi['kurs'], 2)} vs. HA {de(ha_price, 2)} – Split oder falscher Titel?")

    e = eps_info(raw.get("est"), raw.get("cal"), today)
    kgv = fkgv = None
    if price and e.get("eps_ttm") is not None:
        kgv = price / e["eps_ttm"] if e["eps_ttm"] > 0 else None
    if price and e.get("eps_erwartet"):
        fkgv = price / e["eps_erwartet"] if e["eps_erwartet"] > 0 else None
    if kgv and kgv > 500:
        kgv = None
    if fkgv and fkgv > 500:
        fkgv = None

    out = {
        "titel": t["name"], "symbol": t.get("symbol"), "isin": isin, "waehrung": cur,
        "kurs": price, "kurs_quelle": "HA (Yahoo)" if ha_price else "Eulerpool",
        "kursziel": round(main_target(tg), 2) if main_target(tg) else None,
        "kursziel_durchschnitt": round(tg["mean"], 2) if tg and tg.get("mean") else None,
        "kursziel_hoch": round(tg["high"], 2) if tg and tg.get("high") else None,
        "kursziel_tief": round(tg["low"], 2) if tg and tg.get("low") else None,
        "kursziel_analysten": tg.get("anzahl") if tg else None,
        "kursziel_stand": tg["stand"].isoformat() if tg and tg.get("stand") else None,
        "kursziel_quelle": tq,
        "abstand_pct": round(upside, 1) if upside is not None else None,
        "konsens": cons["label"] if cons else None, "konsens_score": cons["score"] if cons else None,
        "analysten": cons, "konsens_vormonat": (consensus(reco_prev) or {}).get("label"),
        "kgv": round(kgv, 1) if kgv else None, "fkgv": round(fkgv, 1) if fkgv else None,
        "verlust": bool(e.get("eps_ttm") is not None and e["eps_ttm"] <= 0),
        "hoch_52w": qi.get("hoch_52w"), "tief_52w": qi.get("tief_52w"),
        "abstand_hoch_pct": round((price / qi["hoch_52w"] - 1) * 100, 1) if price and qi.get("hoch_52w") else None,
        "rendite_pct": returns_info(raw.get("pc")),
        "letzter_split": sp["text"] if sp else None,
    }
    out.update(e)
    out.update(short_info(raw.get("si"), raw.get("fl")))
    out.update(insider_us(raw.get("ins"), today) if isin.startswith("US") else insider_eu(raw.get("ins"), today))
    out.update(grades_info(raw.get("grades"), today))
    out.update(dividends_info(raw.get("div"), price, today))
    if cons and cons.get("monat"):
        try:
            cm = date.fromisoformat(cons["monat"] + "-01")
            if (today - cm).days > STALE_DAYS + 31:
                cons["alt"] = True
                info.append(f"Analysten-Konsens vom {cm.strftime('%m/%y')} (alt)")
        except ValueError:
            pass
    if stale and tg and tg.get("stand"):
        out["kursziel_alt"] = True
    out["hinweise"] = hints + info
    out["pruefen"] = bool(hints)
    out["kennzahlen"] = kennzahlen_line(out, sign, today)
    return out


def kennzahlen_line(o, sign, today):
    parts = []
    if o.get("kgv"):
        parts.append(f"KGV {de(o['kgv'])}")
    elif o.get("verlust"):
        parts.append("KGV n. a. (Verlust)")
    if o.get("fkgv"):
        parts.append(f"fKGV {de(o['fkgv'])}")
    if o.get("kursziel"):
        alt = f" alt {date.fromisoformat(o['kursziel_stand']).strftime('%m/%y')}" if o.get("kursziel_alt") else ""
        parts.append(f"Ziel {de(o['kursziel'])} {sign} ({pct(o.get('abstand_pct'))} %){alt}")
    if o.get("konsens"):
        a = o["analysten"]
        alt = f", alt {date.fromisoformat(a['monat'] + '-01').strftime('%m/%y')}" if a.get("alt") else ""
        parts.append(f"Konsens {o['konsens']} ({a['anzahl']}{alt})")
    if o.get("short_quote_pct") is not None:
        parts.append(f"Short {de(o['short_quote_pct'], 1)} %")
    if o.get("naechste_zahlen"):
        parts.append(f"Zahlen {ddmm(date.fromisoformat(o['naechste_zahlen']))}")
    if o.get("pruefen"):
        parts.append("⚠ prüfen")
    parts.append("Quelle Eulerpool")
    parts.append(f"Stand {ddmm(today)}")
    line = " · ".join(parts)
    return line[:255]
