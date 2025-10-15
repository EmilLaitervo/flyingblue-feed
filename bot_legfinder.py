#!/usr/bin/env python3
# Leg Finder — windowed search for best EUR/XP on specific routes & dates
import os, csv, time, logging, requests, datetime as dt
from itertools import product

# ====== Config: pas alleen dit blok aan ======================================
ORIGINS = ["AMS","DUS"]          # jouw vertrekhavens
DESTS   = ["HEL","TKU"]          # jouw bestemmingen (Helsinki / Turku)

OUT_DATE_TARGET = "2025-11-27"   # gewenste heendatum
OUT_WINDOW_DAYS = 2              # venster ±dagen om OUT_DATE_TARGET
RET_DATE_TARGET = "2025-12-05"   # gewenste retourdatum
RET_WINDOW_DAYS = 2              # venster ±dagen om RET_DATE_TARGET

CURRENCY   = "EUR"
THRESHOLD  = 12.0                # laat alles < €12/XP door (pas later terug naar 10)
MIN_SEGMENTS = 2                 # minimaal 2 (heen+terug); zet 4 als je J-runs wil snipen
CABIN_CLASSES = ["BUSINESS","PREMIUM_ECONOMY","ECONOMY"]  # zoek in alle cabines

REQUEST_TIMEOUT = 12
MAX_RETRIES     = 2
BACKOFF_SEC     = 2.5
EARLY_STOP_AT   = 10             # genoeg resultaten? dan stoppen

# SkyTeam / Flying Blue
SKYTEAM      = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}
FB_MARKETING = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}

USE_TEST_API = False  # productie
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def base_url(): return "https://api.amadeus.com" if not USE_TEST_API else "https://test.api.amadeus.com"

def get_token():
    r = requests.post(
        f"{base_url()}/v1/security/oauth2/token",
        data={"grant_type":"client_credentials",
              "client_id":os.getenv("AMADEUS_API_KEY"),
              "client_secret":os.getenv("AMADEUS_API_SECRET")},
        timeout=REQUEST_TIMEOUT
    ); r.raise_for_status()
    return r.json()["access_token"]

def get_with_retries(url, params, headers):
    for i in range(MAX_RETRIES+1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status(); return r
        except Exception as e:
            if i == MAX_RETRIES: raise
            time.sleep(BACKOFF_SEC*(i+1))
            logging.warning(f"Retry {i+1}/{MAX_RETRIES}: {e}")

def search_offers(tok, origin, dest, dep, ret, tclass=None):
    p = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": 1,
        "currencyCode": CURRENCY,
        "max": 60,
        "nonStop": "false",
    }
    if tclass: p["travelClass"] = tclass
    r = get_with_retries(f"{base_url()}/v2/shopping/flight-offers", p, {"Authorization": f"Bearer {tok}"})
    return r.json().get("data", [])

def eligible(off):
    for it in off.get("itineraries", []):
        for s in it.get("segments", []):
            mk = s.get("carrierCode")
            op = (s.get("operating") or {}).get("carrierCode", mk)
            if mk not in FB_MARKETING or op not in SKYTEAM:
                return False
    return True

def xp_intra_eu(cabin):
    c = (cabin or "ECONOMY").upper()
    if c.startswith("BUS"): return 15
    if c.startswith("PRE"): return 10
    return 5

def summarize(off):
    price = float(off["price"]["grandTotal"])
    segs, xp, cabins = 0, 0, []
    for it in off.get("itineraries", []):
        segs += len(it.get("segments", []))
        for s in it.get("segments", []):
            cabins.append(s.get("cabin","ECONOMY"))
            xp += xp_intra_eu(s.get("cabin"))
    if segs < MIN_SEGMENTS: return None
    cabin = "Business" if any(c.upper().startswith("BUS") for c in cabins) else ("Premium Economy" if any(c.upper().startswith("PRE") for c in cabins) else "Economy")
    eurxp = round(price / max(1, xp), 2)
    first = off["itineraries"][0]["segments"][0]["departure"]["iataCode"]
    last  = off["itineraries"][0]["segments"][-1]["arrival"]["iataCode"]
    return {"title":f"{first}-{last} ({cabin})","itinerary":f"{first}-{last}","cabin":cabin,
            "segments":segs,"xp_total":xp,"price_eur":round(price,2),"eur_per_xp":eurxp}

def date_range(center_str, window):
    c = dt.date.fromisoformat(center_str)
    return [c + dt.timedelta(days=d) for d in range(-window, window+1)]

def main():
    tok = get_token()
    out_dates = date_range(OUT_DATE_TARGET, OUT_WINDOW_DAYS)
    ret_dates = date_range(RET_DATE_TARGET, RET_WINDOW_DAYS)

    results = []
    queries = 0

    for origin, dest in product(ORIGINS, DESTS):
        for dep in out_dates:
            for ret in ret_dates:
                if ret <= dep: continue  # retour na heen
                for tclass in CABIN_CLASSES:
                    queries += 1
                    logging.info(f"[{queries}] {origin}->{dest} {dep}/{ret} class={tclass}")
                    try:
                        offers = search_offers(tok, origin, dest, dep, ret, tclass)
                    except Exception as e:
                        logging.error(f"Zoekfout {origin}-{dest} {dep}/{ret} class={tclass}: {e}")
                        continue
                    for off in offers:
                        if not eligible(off): continue
                        row = summarize(off)
                        if not row: continue
                        if row["eur_per_xp"] < THRESHOLD:
                            row.update({
                                "link": "",
                                "travel_dates": f"{dep} to {ret}",
                                "carrier": "SkyTeam",
                                "book_code": "",
                                "notes": "legfinder",
                                "pubdate_utc": dt.datetime.utcnow().isoformat(timespec="seconds")+"Z"
                            })
                            results.append(row)
                            if len(results) >= EARLY_STOP_AT:
                                logging.info("Early stop: genoeg resultaten.")
                                break
                if len(results) >= EARLY_STOP_AT: break
            if len(results) >= EARLY_STOP_AT: break

    results.sort(key=lambda r: (r["eur_per_xp"], -r["xp_total"]))
    top10 = results[:10]

    # schrijf CSV voor jou + feed gebruikt nog steeds deals.csv
    with open("deals.csv","w",newline="",encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title","link","itinerary","cabin","segments","xp_total","price_eur",
                    "eur_per_xp","travel_dates","carrier","book_code","notes","pubdate_utc"])
        for r in top10:
            w.writerow([r["title"], r["link"], r["itinerary"], r["cabin"], r["segments"],
                        r["xp_total"], r["price_eur"], r["eur_per_xp"], r["travel_dates"],
                        r["carrier"], r["book_code"], r["notes"], r["pubdate_utc"]])

    logging.info(f"Klaar. Queried combos: {queries}, hits: {len(results)}")

if __name__ == "__main__":
    main()
