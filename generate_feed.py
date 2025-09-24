#!/usr/bin/env python3
import csv, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime  # <-- import HIER en nergens anders

CSV_FILE = "deals.csv"
OUT_FILE = "feed.xml"

def load_deals(csv_file):
    rows = []
    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                eur_per_xp = float(row["eur_per_xp"])
            except:
                continue
            if eur_per_xp >= 10.0:
                continue  # alleen < €10/XP
            rows.append(row)

    def parse_pubdate(r):
        s = r.get("pubdate_utc","")
        try:
            return datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception:
            return datetime.now(timezone.utc)
    rows.sort(key=parse_pubdate, reverse=True)
    return rows

def make_rss(items):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Flying Blue XP Deals (< €10/XP)"
    ET.SubElement(channel, "link").text = "https://<jouwgebruikersnaam>.github.io/flyingblue-feed/feed.xml"
    ET.SubElement(channel, "description").text = "Automatisch gegenereerde feed met Flying Blue deals onder €10/XP"
    ET.SubElement(channel, "language").text = "nl"
    now = datetime.now(timezone.utc)
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(now)

    for r in items:
        item = ET.SubElement(channel, "item")
        desc = f'{r["itinerary"]} | {r["cabin"]} | {r["segments"]} seg | {r["xp_total"]} XP | €{r["price_eur"]} | €{r["eur_per_xp"]}/XP'
        if r.get("travel_dates"): desc += f' | {r["travel_dates"]}'
        if r.get("carrier"): desc += f' | {r["carrier"]}'
        if r.get("notes"): desc += f' | {r["notes"]}'

        ET.SubElement(item, "title").text = r["title"]
        ET.SubElement(item, "link").text = r["link"]
        ET.SubElement(item, "description").text = desc

        pd = r.get("pubdate_utc","")
        try:
            dt = datetime.fromisoformat(pd.replace("Z","+00:00"))
        except Exception:
            dt = now
        ET.SubElement(item, "pubDate").text = format_datetime(dt)

    return ET.ElementTree(rss)

def main():
    items = load_deals(CSV_FILE)
    rss = make_rss(items)
    rss.write(OUT_FILE, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {OUT_FILE} with {len(items)} items (< €10/XP).")

if __name__ == "__main__":
    main()
