#!/usr/bin/env python3
# Flying Blue XP Finder – zoekt ALLE vluchten tussen opgegeven luchthavens
# Sorteert op €/XP (laag → hoog), zonder filters
import os, csv, time, logging, requests, datetime as dt
from itertools import product

# =========================
# CONFIGURATIE
# =========================

# 🔹 Vertrekluchthavens
ORIGINS = ["AMS", "DUS"]

# 🔹 Bestemmingen
DESTS = ["HEL", "TKU"]

# 🔹 Heenreis: 25–28 november 2025
OUT_DATE_TARGET = "2025-11-26"
OUT_WINDOW_DAYS = 1.5  # ±1.5 dag → 25–28

# 🔹 Terugreis: 5–6 december 2025
RET_DATE_TARGET = "2025-12-05"
RET_WINDOW_DAYS = 0.5  # ±0.5 dag → 5–6

# 🔹 Cabines en XP-berekening
CABIN_CLASSES = ["BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"]
MIN_SEGMENTS = 2  # minimaal heen en terug
USE_TEST_API = False  # productieomgeving

# 🔹 Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# =========================
# HULPFUNCTIES
# =========================

def base_url():
    return "https://api.amadeus.com" if not USE_TEST_API else "https://test.api.amadeus.com"

def get_token():
    r = requests.post(
        f"{base_url()}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("AMADEUS_API_KEY"),
            "client_secret": os.getenv("AMADEUS_API_SECRET"),
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def get_with_retry(url, params, headers, retries=2):
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == retries:
                raise
            time.sleep(2.5 * (i + 1))
            logging.warning(f"Retry {i+1}/{retries}: {e}")

def search_offers(tok, origin, dest, dep, ret, tclass=None):
    p = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": 1,
        "currencyCode": "EUR",
        "max": 100,
        "nonStop": "false",
    }
    if tclass:
        p["travelClass"] = tclass
    r = get_with_retry(f"{base_url()}/v2/shopping/flight-offers", p, {"Authorization": f"Bearer {tok}"})
    return r.json().get("data", [])

# Flying Blue partners
SKYTEAM = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}
FB_MARKETING = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}

def eligible(offer):
    """Checkt of alle segmenten SkyTeam-operated én Flying Blue-marketed zijn"""
    for it in offer.get("itineraries", []):
        for s in it.get("segments", []):
            mk = s.get("carrierCode")
            op = (s.get("operating") or {}).get("carrierCode", mk)
            if mk not in FB_MARKETING or op not in SKYTEAM:
                return False
    return True

def xp_intra_eu(cabin):
    """XP-berekening per segment voor intra-EU"""
    c = (cabin or "ECONOMY").upper()
    if c.startswith("BUS"): return 15
    if c.startswith("PRE"): return 10
    return 5

def summarize(offer):
    price = float(offer["price"]["grandTotal"])
    segs, xp, cabins = 0, 0, []
    for it in offer.get("itineraries", []):
        segs += len(it.get("segments", []))
        for s in it.get("segments", []):
            cabins.append(s.get("cabin", "ECONOMY"))
            xp += xp_intra_eu(s.get("cabin"))
    if segs < MIN_SEGMENTS:
        return None
    cabin = (
        "Business" if any(c.upper().startswith("BUS") for c in cabins)
        else "Premium Economy" if any(c.upper().startswith("PRE") for c in cabins)
        else "Economy"
    )
    eurxp = round(price / max(1, xp), 2)
    first = offer["itineraries"][0]["segments"][0]["departure"]["iataCode"]
    last = offer["itineraries"][0]["segments"][-1]["arrival"]["iataCode"]
    return {
        "title": f"{first}-{last} ({cabin})",
        "itinerary": f"{first}-{last}",
        "cabin": cabin,
        "segments": segs,
        "xp_total": xp,
        "price_eur": round(price, 2),
        "eur_per_xp": eurxp,
    }

def date_range(center_str, window):
    c = dt.date.fromisoformat(center_str)
    low = int(c.toordinal() - round(window))
    high = int(c.toordinal() + round(window))
    return [dt.date.fromordinal(d) for d in range(low, high + 1)]

# =========================
# MAIN
# =========================

def main():
    tok = get_token()
    out_dates = date_range(OUT_DATE_TARGET, OUT_WINDOW_DAYS)
    ret_dates = date_range(RET_DATE_TARGET, RET_WINDOW_DAYS)

    results = []
    queries = 0

    for origin, dest in product(ORIGINS, DESTS):
        for dep in out_dates:
            for ret in ret_dates:
                if ret <= dep:
                    continue
                for tclass in CABIN_CLASSES:
                    queries += 1
                    logging.info(f"[{queries}] {origin}->{dest} {dep}/{ret} class={tclass}")
                    try:
                        offers = search_offers(tok, origin, dest, dep, ret, tclass)
                    except Exception as e:
                        logging.error(f"Zoekfout {origin}-{dest} {dep}/{ret}: {e}")
                        continue
                    for off in offers:
                        if not eligible(off):
                            continue
                        row = summarize(off)
                        if row:
                            row.update({
                                "travel_dates": f"{dep} to {ret}",
                                "carrier": "SkyTeam",
                                "notes": "unfiltered",
                                "pubdate_utc": dt.datetime.utcnow().isoformat(timespec="seconds")+"Z"
                            })
                            results.append(row)

    # sorteer alle resultaten op €/XP (laag → hoog)
    results.sort(key=lambda r: (r["eur_per_xp"], -r["xp_total"]))

    with open("deals.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "title","itinerary","cabin","segments","xp_total","price_eur",
            "eur_per_xp","travel_dates","carrier","notes","pubdate_utc"
        ])
        for r in results:
            w.writerow([
                r["title"], r["itinerary"], r["cabin"], r["segments"], r["xp_total"],
                r["price_eur"], r["eur_per_xp"], r["travel_dates"], r["carrier"],
                r["notes"], r["pubdate_utc"]
            ])

    logging.info(f"Klaar. Queries: {queries}, resultaten: {len(results)}")

if __name__ == "__main__":
    main()
