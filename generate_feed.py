#!/usr/bin/env python3
# Generate RSS feed (feed.xml) from deals.csv
import csv, datetime as dt, xml.etree.ElementTree as ET

# Bestanden
CSV_FILE = "deals.csv"
XML_FILE = "feed.xml"

# Huidige UTC-tijd voor metadata
now_utc = dt.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

# RSS-structuur opbouwen
rss = ET.Element("rss", version="2.0")
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = "Flying Blue XP Deals (< €11/XP)"
ET.SubElement(channel, "link").text = "https://emillaitervo.github.io/flyingblue-feed/feed.xml"
ET.SubElement(channel, "description").text = "Automatisch gegenereerde feed met Flying Blue deals onder €11 per XP"
ET.SubElement(channel, "language").text = "nl"
ET.SubElement(channel, "lastBuildDate").text = now_utc

# Deals lezen en toevoegen aan feed
try:
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = row.get("title", "Onbekende deal")
            ET.SubElement(item, "link").text = f"https://www.google.com/search?q={row.get('itinerary','')}"
            desc = (
                f"{row.get('itinerary','')} | {row.get('cabin','')} | "
                f"{row.get('segments','')} seg | {row.get('xp_total','')} XP | "
                f"€{row.get('price_eur','')} | €{row.get('eur_per_xp','')}/XP | "
                f"{row.get('travel_dates','')} | {row.get('carrier','')} | "
                f"{row.get('notes','')}"
            )
            ET.SubElement(item, "description").text = desc
            pubdate = row.get("pubdate_utc") or now_utc
            ET.SubElement(item, "pubDate").text = pubdate
except FileNotFoundError:
    print("⚠️ deals.csv niet gevonden – geen feed bijgewerkt.")

# XML opslaan
tree = ET.ElementTree(rss)
tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)
print(f"✅ Feed bijgewerkt ({XML_FILE}) op {now_utc}")
