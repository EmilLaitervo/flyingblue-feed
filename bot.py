#!/usr/bin/env python3
# Flying Blue XP Bot — J-only, 4+ segments, robust timeouts, near-miss logging
import os, csv, time, random, logging, requests, datetime as dt

# ========= Instellingen =======================================================
# Vertrekluchthavens (je kunt later alle 9 aanzetten; begin compact voor snelheid)
ORIGINS = ["AMS","BRU","DUS","CGN","NRN","RTM","EIN","GRQ","MST"]

# Kansrijke EU-bestemmingen (hubs + goedkope J-runs). Vul gerust aan.
DESTS = [
  "CDG","ORY","LYS","NCE","MRS",
  "OSL","TRF","BGO","SVG","CPH","ARN","GOT","HEL","TLL","RIX","VNO",
  "ATH","SKG","LCA","MLA","IST","SAW","TLV",
  "BCN","MAD","AGP","PMI","LIS","OPO","FAO",
  "DUB","BFS","EDI","GLA","BHX","MAN","BRS","NCL",
  "WAW","KRK","GDN","PRG","BUD","ZAG","SPU","DBV","TIA","SOF","OTP","CLJ","IAS",
  "VIE","ZRH","GVA","MXP","LIN","FCO","NAP","PSA","FLR","CAG","CTA","RHO","HER","CFU","SKP"
]

DAYS_AHEAD   = 60              # zoek 60 dagen vooruit
DAY_STEP     = 2               # dichter raster dan voorheen
STAY_NIGHTS  = [0,1,2]         # same-day/overnight/2 nachten
CURRENCY     = "EUR"
THRESHOLD    = 10.0            # alleen < €10/XP publiceren
USE_TEST_API = False           # productie!

# Cabin-keuze: nu J-only om kans op < €10/XP te maximaliseren
CABIN_CLASSES = ["BUSINESS"]

# Minimaal aantal segmenten per retour (intra-EU J=15 XP/segment → 4 seg = 60 XP)
MIN_SEGMENTS = 4

# Near-miss logging (alleen loggen tussen 10–12 €/XP, niet publiceren)
NEAR_MISS_LOW, NEAR_MISS_HIGH = 10.0, 12.0

# Anti-hang en limieten
REQUEST_TIMEOUT = 12           # sec per API-call
MAX_RETRIES     = 2
BACKOFF_SEC     = 2.5
MAX_QUERIES     = 200          # harde cap per run
EARLY_STOP_AT   = 10           # stop zodra 10 hits zijn gevonden
DEADLINE_MIN    = 10           # safety stop ~10 min

# SkyTeam/FB-eligible carriers
SKYTEAM      = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}
FB_MARKETING = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ========= API helpers ========================================================
def base_url() -> str:
    return "https://api.amadeus.com" if not USE_TEST_API else "https://test.api.amadeus.com"

def get_token() -> str:
    r = requests.post(
        f"{base_url()}/v1/security/oauth2/token",
        data={"grant_type":"client_credentials",
              "client_id":os.getenv("AMADEUS_API_KEY"),
              "client_secret":os.getenv("AMADEUS_API_SECRET")},
        timeout=REQUEST_TIMEOUT
    )
    r.raise_for_status()
    return r.json()["access_token"]

def get_with_retries(url: str, params: dict, headers: dict):
    for i in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == MAX_RETRIES:
                raise
            sleep = BACKOFF_SEC * (i + 1)
            logging.warning(f"Retry {i+1}/{MAX_RETRIES} in {sleep:.1f}s: {e}")
            time.sleep(sleep)

def search_offers(tok: str, origin: str, dest: str, dep: dt.date, ret: dt.date, travel_class: str | None):
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": 1,
        "currencyCode": CURRENCY,
        "max": 60,
        "nonStop": "false"
    }
    if travel_class:
        params["travelClass"] = travel_class
    r = get_with_retries(f"{base_url()}/v2/shopping/flight-offers", params, {"Authorization": f"Bearer {tok}"})
    return r.json().get("data", [])

# ========= Business intra-EU XP logic ========================================
def eligible(offer: dict) -> bool:
    # elk segment moet: FB-marketed + SkyTeam-operated
    for itin in offer.get("itineraries", []):
        for s in itin.get("segments", []):
            mk = s.get("carrierCode")                           # marketing
            op = (s.get("operating") or {}).get("carrierCode", mk)  # operating
            if mk not in FB_MARKETING or op not in SKYTEAM:
                return False
    return True

def xp_intra_europe(cabin: str | None) -> int:
    # EU-heuristic: J=15, PE=10, Y=5 per segment
    c = (cabin or "ECONOMY").upper()
    if c.startswith("BUS"): return 15
    if c.startswith("PRE"): return 10
    return 5

def summarize(offer: dict) -> dict | None:
    price = float(offer["price"]["grandTotal"])
    segs, xp, cabins = 0, 0, []
    for it in offer.get("itineraries", []):
        for s in it.get("segments", []):
            segs += 1
            cab = s.get("cabin","ECONOMY")
            cabins.append(cab)
            xp += xp_intra_europe(cab)
    if segs < MIN_SEGMENTS:
        return None  # dwing 4+ segmenten af voor betere €/XP
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

# ========= Main loop ==========================================================
def main():
    start = time.time()
    tok = get_token()
    today = dt.date.today()
    hits, queries = [], 0
    total_offers, eligible_offers = 0, 0

    # Random volgorde per run
    random.seed(int(time.time()))
    o_list = ORIGINS[:]; d_list = DESTS[:]
    random.shuffle(o_list); random.shuffle(d_list)

    for origin in o_list:
        for dest in d_list:
            day_offsets = list(range(1, DAYS_AHEAD + 1, DAY_STEP))
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
                    for tclass in CABIN_CLASSES:  # nu alleen BUSINESS
                        if (time.time() - start) > DEADLINE_MIN * 60 or queries >= MAX_QUERIES:
                            break
                        queries += 1
                        logging.info(f"[{queries}] {origin}->{dest} {dep}/{ret} class={tclass}")
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
                            if not row:
                                continue
                            eurxp = row["eur_per_xp"]
                            if eurxp < THRESHOLD:
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
                            elif NEAR_MISS_LOW <= eurxp <= NEAR_MISS_HIGH:
                                logging.info(f"Near miss {row['itinerary']} {row['cabin']} "
                                             f"{row['segments']}seg {row['xp_total']}XP "
                                             f"€{row['price_eur']} ({eurxp}/XP)")
                        if len(hits) >= EARLY_STOP_AT:
                            break
                if len(hits) >= EARLY_STOP_AT:
                    break
            if len(hits) >= EARLY_STOP_AT:
                break

    # Sorteren en schrijven (ook als 0 hits: lege CSV met header)
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

    logging.info(f"Klaar. Queries: {queries}, total_offers: {total_offers}, "
                 f"eligible_offers: {eligible_offers}, hits: {len(hits)}, "
                 f"duur: {int(time.time()-start)}s")

if __name__ == "__main__":
    main()
