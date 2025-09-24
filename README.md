# Flying Blue XP Deals Feed (< €10/XP)

Dit is je **echte feed**. Alles is klaar om op **GitHub Pages** te hosten en via **IFTTT** als e-mail te ontvangen.

## Bestanden
- `deals.csv` – hier plak je deals (1 regel per deal). Alleen regels met **eur_per_xp < 10** komen in de feed.
- `generate_feed.py` – bouwt `feed.xml` vanaf `deals.csv`.
- `feed.xml` – dit is je RSS-feed (output). Gebruik deze URL in IFTTT.
- `.github/workflows/publish.yml` – zorgt dat de feed **2× per dag** wordt gebouwd en gepubliceerd.

## Hoe gebruiken (kort)
1. Maak op GitHub een **public repo** (bv. `flyingblue-feed`).
2. Upload alle bestanden uit deze map naar die repo (zelfde structuur).
3. Zet **GitHub Pages** aan (Settings → Pages → Branch: `main`, Folder: `/ (root)`).
4. Wacht tot je een URL ziet (bv. `https://<jouwnaam>.github.io/flyingblue-feed/feed.xml`). **Dit is je feed-URL**.
5. Ga naar **IFTTT** → maak een applet: RSS **New feed item** → Email **Send me an email**, en plak je feed-URL.

## Hoe je de feed bijwerkt
- Voeg nieuwe regels toe aan `deals.csv` (zorg dat `eur_per_xp` < 10).
- Commit je wijziging → de GitHub Action draait automatisch (08:00 en 18:00 CET/CEST → in UTC: 06:00 en 16:00).
- De feed wordt bijgewerkt en IFTTT mailt nieuwe items.

> Tip: Bewaar alle bedragen als **puntnotatie** (bijv. 9.00, niet 9,00).

