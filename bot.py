#!/usr/bin/env python3
import os, csv, time, random, logging, requests, datetime as dt

# ====== Instellingen =========================================================
# Vergroot origins rustig als dit stabiel draait
ORIGINS = ["AMS","BRU","DUS","CGN","NRN","RTM","EIN","GRQ","MST"]

# Veel EU-bestemmingen (hubs + goedkope routes). Voeg gerust toe.
DESTS = [
  "CDG","ORY","LYS","NCE","MRS",
  "OSL","TRF","BGO","SVG","CPH","ARN","GOT","HEL","TLL","RIX","VNO",
  "ATH","SKG","LCA","MLA","IST","SAW","TLV",
  "BCN","MAD","AGP","PMI","LIS","OPO","FAO",
  "DUB","BFS","EDI","GLA","BHX","MAN","BRS","NCL","LHR","LGW","LCY",
  "WAW","KRK","GDN","PRG","BUD","ZAG","SPU","DBV","TIA","SOF","OTP","CLJ","IAS",
  "VIE","ZRH","GVA","MXP","LIN","FCO","NAP","PSA","FLR","CAG","CTA","RHO","HER","CFU","SKP"
]

DAYS_AHEAD   = 60         # 60 dagen vooruit
DAY_STEP     = 3          # dichter raster dan 5
STAY_NIGHTS  = [0,1,2,3]  # ook same-day/overnight proberen
CURRENCY     = "EUR"
THRESHOLD    = 10.0       # strikt < €10/XP
USE_TEST_API = False      # productie!

# Query-beperkingen (anti-hang)
REQUEST_TIMEOUT = 12
MAX_RETRIES     = 2
BACKOFF_SEC     = 2.5
MAX_QUERIES     = 200      # iets ruimer dan 120
EARLY_STOP_AT   = 10       # stop zodra 10 hits
DEADLINE_MIN    = 10       # hard stop na ~10 min compute

# SkyTeam / FB-marketing
SKYTEAM      = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}
FB_MARKETING = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}

# Cabines: None = “alle”, plus geforceerde cabin-searches
CABIN_CLASSES = [None, "ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"]

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def base_url():
    return "https://api.amadeus.com"

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
            if i == MAX_RETRIES:
                raise
            time.sleep(BACKOFF_SEC * (i+1))
            logging.warning(f"Retry {i+1}/{MAX_RETRIES}: {e}")

def search_offers(tok, origin, dest, dep, ret, travel_class=None):
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": 1,
        "currencyCode": CURRENCY,
        "max": 60,                 # iets hoger, maar nog veilig
        "nonStop": "false"         # expliciet met overstap oké
    }
    if travel_class:
        params["travelClass"] = travel_class
    r = get_with_retries(f"{base_url()}/v2/shopping/flight-offers", params, {"Authorization": f"Bearer {tok}"})
    return r.json().get("data", [])

def eligible(offer):
    for itin in offer.get("itineraries", []):
        for s in itin.get("segments", []):
            mk = s.get("carrierCode")                           # marketing
            op = (s.get("operating") or {}).get("carrierCode", mk)  # operating
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
    for it in offer.get("itineraries", []):
        for s in it.get("segments", []):
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
    total_offers, eligible_offers = 0, 0

    # randomize volgorde per run
    random.seed(int(time.time()))
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
                    for tclass in CABIN_CLASSES:
                        if (time.time() - start) > DEADLINE_MIN * 60 or queries >= MAX_QUERIES:
                            break
                        queries += 1
                        logging.info(f"[{queries}] {origin}->{dest} {dep}/{ret} class={tclass or 'ANY'}")
                        try:
                            offers = search_offers(tok, origin, dest, dep, ret, travel_class=tclass)
                        except Exception as e:
                            logging.error(f"Zoekfout {origin}-{dest} {dep}/{ret} class={tclass}: {e}")
                            continue

                        total_offers += len(offers)
                        for off in offers:
                            if not eligible(off):
                                continue
                            eligible_offers += 1
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
                                    logging.info("Early-stop: genoeg geschikte hits.")
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

    logging.info(f"Klaar. Queries: {queries}, total_offers: {total_offers}, eligible_offers: {eligible_offers}, hits: {len(hits)}, duur: {int(time.time()-start)}s")

if __name__ == "__main__":
    main()
