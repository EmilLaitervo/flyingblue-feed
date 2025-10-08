#!/usr/bin/env python3
import os, csv, time, random, logging, requests, datetime as dt

# ====== Snellere/robuustere settings =========================================
ORIGINS = ["AMS","BRU","DUS"]               # begin compact; later uitbreiden
DESTS   = ["CDG","OSL","CPH","ARN","HEL","BCN","LIS","MAD","DUB","VIE","PRG"]
DAYS_AHEAD   = 45                            # 60 kan, maar 45 is sneller
DAY_STEP     = 5                             # i.p.v. elke dag → om de 5 dagen
STAY_NIGHTS  = [2]                           # eenvoudiger raster; later 1/3 erbij
CURRENCY     = "EUR"
THRESHOLD    = 10.0
USE_TEST_API = False                         # productie!

# Limieten / anti-hang
REQUEST_TIMEOUT = 12                         # seconden per API-call
MAX_RETRIES     = 2                          # retries per call
BACKOFF_SEC     = 2.5
MAX_QUERIES     = 120                        # harde cap per run
EARLY_STOP_AT   = 10                         # stop zodra 10 hits < €10/XP
DEADLINE_MIN    = 8                          # run hard stoppen < 10 min step

# SkyTeam + FB-marketing
SKYTEAM      = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}
FB_MARKETING = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def base_url():
    return "https://api.amadeus.com" if not USE_TEST_API else "https://test.api.amadeus.com"

def get_token():
    r = requests.post(
        f"{base_url()}/v1/security/oauth2/token",
        data={"grant_type":"client_credentials",
              "client_id":os.getenv("AMADEUS_API_KEY"),
              "client_secret":os.getenv("AMADEUS_API_SECRET")},
        timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()
    return r.json()["access_token"]

def get_with_retries(url, params, headers):
    for i in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == MAX_RETRIES: raise
            sleep = BACKOFF_SEC * (i+1)
            logging.warning(f"API retry {i+1}/{MAX_RETRIES} in {sleep:.1f}s: {e}")
            time.sleep(sleep)

def search_offers(tok, origin, dest, dep, ret):
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": 1,
        "currencyCode": CURRENCY,
        "max": 40,  # hou t klein
    }
    r = get_with_retries(f"{base_url()}/v2/shopping/flight-offers", params, {"Authorization": f"Bearer {tok}"})
    return r.json().get("data", [])

def eligible(offer):
    for itin in offer.get("itineraries", []):
        for s in itin.get("segments", []):
            mk = s.get("carrierCode")
            op = (s.get("operating") or {}).get("carrierCode", mk)
            if mk not in FB_MARKETING or op not in SKYTEAM:
                return False
    return True

def xp_intra_europe(cabin):
    c = (cabin or "ECONOMY").upper()
    if c.startswith("BUS"): return 15
    if c.startswith("PRE"): return 10
    return 5

def summarize(offer):
    price = float(offer["price"]["grandTotal"])
    segs, xp, cabins = 0, 0, []
    for itin in offer.get("itineraries", []):
        for s in itin.get("segments", []):
            segs += 1
            cab = s.get("cabin","ECONOMY")
            cabins.append(cab)
            xp += xp_intra_europe(cab)
    cabin = "Business" if any(c.upper().startswith("BUS") for c in cabins) \
            else ("Premium Economy" if any(c.upper().startswith("PRE") for c in cabins) else "Economy")
    eur_per_xp = round(price / max(1, xp), 2)
    first = offer["itineraries"][0]["segments"][0]["departure"]["iataCode"]
    last  = offer["itineraries"][0]["segments"][-1]["arrival"]["iataCode"]
    return {
        "title": f"{first}-{last} ({cabin})",
        "itinerary": f"{first}-{last}",
        "cabin": cabin,
        "segments": segs,
        "xp_total": xp,
        "price_eur": round(price,2),
        "eur_per_xp": eur_per_xp
    }

def main():
    start = time.time()
    tok = get_token()
    today = dt.date.today()
    hits, queries = [], 0

    # Shuffle voor variatie per run
    random.seed(int(today.strftime("%Y%m%d")))
    o_list = ORIGINS[:]; d_list = DESTS[:]
    random.shuffle(o_list); random.shuffle(d_list)

    for origin in o_list:
        for dest in d_list:
            day_offsets = list(range(1, DAYS_AHEAD+1, DAY_STEP))
            random.shuffle(day_offsets)
            for d_off in day_offsets:
                dep = today + dt.timedelta(days=d_off)
                for stay in STAY_NIGHTS:
                    if (time.time() - start) > DEADLINE_MIN * 60:
                        logging.warning("Stoppen op deadline-bescherming.")
                        break
                    if queries >= MAX_QUERIES:
                        logging.warning("MAX_QUERIES bereikt, stoppen.")
                        break

                    ret = dep + dt.timedelta(days=stay)
                    queries += 1
                    logging.info(f"[{queries}] Zoek {origin}->{dest} {dep} / terug {ret}")
                    try:
                        offers = search_offers(tok, origin, dest, dep, ret)
                    except Exception as e:
                        logging.error(f"Zoekfout {origin}-{dest} {dep}/{ret}: {e}")
                        continue

                    for off in offers:
                        if not eligible(off): 
                            continue
                        row = summarize(off)
                        if row["eur_per_xp"] < THRESHOLD:
                            row.update({
                                "link": "",
                                "travel_dates": f"{dep} to {ret}",
                                "carrier": "SkyTeam",
                                "book_code": "",
                                "notes": "auto-bot",
                                "pubdate_utc": dt.datetime.utcnow().isoformat(timespec="seconds")+"Z"
                            })
                            hits.append(row)
                            if len(hits) >= EARLY_STOP_AT:
                                logging.info("Early-stop: genoeg geschikte hits gevonden.")
                                break
                    if len(hits) >= EARLY_STOP_AT:
                        break
                if len(hits) >= EARLY_STOP_AT:
                    break
            if len(hits) >= EARLY_STOP_AT:
                break

    hits.sort(key=lambda r: (r["eur_per_xp"], -r["xp_total"]))
    top10 = hits[:10]

    with open("deals.csv","w",newline="",encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title","link","itinerary","cabin","segments","xp_total","price_eur",
                    "eur_per_xp","travel_dates","carrier","book_code","notes","pubdate_utc"])
        for r in top10:
            w.writerow([r["title"], r["link"], r["itinerary"], r["cabin"], r["segments"],
                        r["xp_total"], r["price_eur"], r["eur_per_xp"], r["travel_dates"],
                        r["carrier"], r["book_code"], r["notes"], r["pubdate_utc"]])

    logging.info(f"Klaar. Queries: {queries}, hits: {len(hits)}, duur: {int(time.time()-start)}s")

if __name__ == "__main__":
    main()
