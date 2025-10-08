#!/usr/bin/env python3
import os, csv, requests, datetime as dt

# ------ Instellingen ---------------------------------------------------------
ORIGINS = ["AMS","RTM","EIN","GRQ","MST","BRU","DUS","CGN","NRN"]

# Kansrijke EU-bestemmingen (hubs + goedkope XP-routes); voeg gerust toe
DESTS = [
  "CDG","ORY","LYS","NCE","MRS",       # Frankrijk / AF-hubs
  "OSL","TRF","BGO","SVG","CPH","ARN","GOT","HEL","TLL","RIX",
  "ATH","SKG","TLV","IST","SAW","LCA","MLA","BCN","MAD","AGP","PMI",
  "LIS","OPO","FAO","DUB","BFS","EDI","GLA","BHX","MAN","BRS","NCL",
  "WAW","KRK","GDN","PRG","BUD","ZAG","SPU","DBV","TIA",
  "VIE","ZRH","GVA","MXP","LIN","FCO","NAP","PSA","FLR","CAG","CTA",
  "RHO","HER","CFU","SKP","SOF","VAR","BUH","CLJ","IAS",
  "VNO","KUN","PLQ",
]

DAYS_AHEAD   = 60                 # zoek 60 dagen vooruit
STAY_NIGHTS  = [1,2,3]            # 1-3 nachten (pas aan naar smaak)
CURRENCY     = "EUR"
THRESHOLD    = 10.0               # alleen < €10/XP
USE_TEST_API = False              # *** productie aan ***

# SkyTeam operated + FB-marketed (codes die XP posten via Flying Blue)
SKYTEAM      = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}
FB_MARKETING = {"KL","AF","DL","AZ","KE","AM","CI","MU","RO","SV","KQ","GA","ME"}

# ------ Helpers --------------------------------------------------------------
def base_url():
    return "https://test.api.amadeus.com" if USE_TEST_API else "https://api.amadeus.com"

def get_token():
    r = requests.post(
        f"{base_url()}/v1/security/oauth2/token",
        data={
          "grant_type":"client_credentials",
          "client_id":os.getenv("AMADEUS_API_KEY"),
          "client_secret":os.getenv("AMADEUS_API_SECRET"),
        },
        timeout=25
    )
    r.raise_for_status()
    return r.json()["access_token"]

def search_offers(tok, origin, dest, dep, ret):
    params = {
      "originLocationCode": origin,
      "destinationLocationCode": dest,
      "departureDate": dep.isoformat(),
      "returnDate": ret.isoformat(),
      "adults": 1,
      "currencyCode": CURRENCY,
      "max": 50,                 # houd bescheiden; je kan dit later verhogen
    }
    r = requests.get(
      f"{base_url()}/v2/shopping/flight-offers",
      params=params,
      headers={"Authorization": f"Bearer {tok}"},
      timeout=45
    )
    r.raise_for_status()
    return r.json().get("data", [])

def eligible(offer):
    # elk segment: operated door SkyTeam + marketed door FB-eligible carrier
    for itin in offer.get("itineraries", []):
        for s in itin.get("segments", []):
            mk = s.get("carrierCode")                           # marketing
            op = (s.get("operating") or {}).get("carrierCode", mk)  # operating
            if mk not in FB_MARKETING or op not in SKYTEAM:
                return False
    return True

def xp_intra_europe(cabin):
    # eenvoudige maar effectieve EU-regel: J=15, PE=10, Y=5 per segment
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
    cabin = ("Business" if any(c.upper().startswith("BUS") for c in cabins)
             else "Premium Economy" if any(c.upper().startswith("PRE") for c in cabins)
             else "Economy")
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

# ------ Main --------------------------------------------------------------
def main():
    tok   = get_token()
    today = dt.date.today()
    hits  = []

    for origin in ORIGINS:
        for dest in DESTS:
            for d in range(1, DAYS_AHEAD+1, 3):   # om de 3 dagen vertrek testen
                dep = today + dt.timedelta(days=d)
                for stay in STAY_NIGHTS:
                    ret = dep + dt.timedelta(days=stay)
                    try:
                        offers = search_offers(tok, origin, dest, dep, ret)
                    except requests.HTTPError:
                        continue
                    for off in offers:
                        if not eligible(off):
                            continue
                        row = summarize(off)
                        if row["eur_per_xp"] < THRESHOLD:
                            row.update({
                              "link": "",  # optioneel deeplink; leeg laten kan ook
                              "travel_dates": f"{dep} to {ret}",
                              "carrier": "SkyTeam",
                              "book_code": "",
                              "notes": "auto-bot",
                              "pubdate_utc": dt.datetime.utcnow().isoformat(timespec="seconds")+"Z"
                            })
                            hits.append(row)

    # sorteren en top 10 bewaren
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

if __name__ == "__main__":
    main()
