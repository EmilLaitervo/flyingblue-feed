#!/usr/bin/env python3
import csv, sys, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

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
                continue  # only include < €10/XP
            rows.append(row)
    # Sort newest first by pubdate (if present)
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
    ET.SubElement(channel, "link").text = "https://example.github.io/flyingblue-feed/feed.xml"
    ET.SubElement(channel, "description").text = "Automatisch gegenereerde feed met Flying Blue deals onder €10/XP"
    ET.SubElement(channel, "language").text = "nl"
    now = datetime.now(timezone.utc)
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(now)

    for r in items:
        item = ET.SubElement(channel, "item")
        title = r.get("title","(geen titel)")
        link = r.get("link","")
        itinerary = r.get("itinerary","")
        cabin = r.get("cabin","")
        seg = r.get("segments","")
        xp = r.get("xp_total","")
        price = r.get("price_eur","")
        epx = r.get("eur_per_xp","")
        dates = r.get("travel_dates","")
        carrier = r.get("carrier","")
        notes = r.get("notes","")

        desc = f"{itinerary} | {cabin} | {seg} seg | {xp} XP | €{price} | €{epx}/XP"
        if dates: desc += f" | {dates}"
        if carrier: desc += f" | {carrier}"
        if notes: desc += f" | {notes}"

        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "description").text = desc

        # pubDate
        pd = r.get("pubdate_utc","")
        try:
            dt = datetime.fromisoformat(pd.replace("Z","+00:00"))
        except Exception:
            dt = now
        from email.utils import format_datetime
        ET.SubElement(item, "pubDate").text = format_datetime(dt)

    return ET.ElementTree(rss)

def main():
    items = load_deals(CSV_FILE)
    rss = make_rss(items)
    rss.write(OUT_FILE, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {OUT_FILE} with {len(items)} items (< €10/XP).")

if __name__ == "__main__":
    main()
