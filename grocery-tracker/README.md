# 🛒 Latvia Grocery Price Tracker

Compare grocery prices across Rimi, Maxima, Mego, Elvi, Lidl, Lats, and Top — 
with automated daily scraping and a REST API.

---

## Architecture

```
grocery-tracker/
├── scrapers/
│   ├── rimi_scraper.py       # Scrapes rimi.lv
│   ├── maxima_scraper.py     # Scrapes maxima.lv
│   ├── run_scrapers.py       # Master runner + DB writer
│   └── requirements.txt
├── api/
│   ├── main.py               # FastAPI backend
│   ├── prices.db             # SQLite database (auto-created)
│   └── requirements.txt
├── frontend/
│   ├── index.html            # Full app (works standalone + with API)
│   └── prices.json           # Auto-exported by scraper (for static hosting)
└── .github/
    └── workflows/
        └── scrape.yml        # Runs scrapers daily via GitHub Actions
```

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/grocery-tracker.git
cd grocery-tracker

# Install scraper deps
pip install -r scrapers/requirements.txt

# Install API deps
pip install -r api/requirements.txt
```

### 2. Run the scrapers

```bash
cd scrapers

# Scrape all stores
python run_scrapers.py

# Scrape only Rimi
python run_scrapers.py --stores rimi

# Test without saving (dry run)
python run_scrapers.py --dry-run
```

This creates `api/prices.db` and exports `frontend/prices.json`.

### 3. Start the API

```bash
cd api
uvicorn main:app --reload --port 8000
```

API docs available at: **http://localhost:8000/docs**

### 4. Open the frontend

Just open `frontend/index.html` in your browser.  
It auto-connects to the API at `localhost:8000`.  
If the API isn't running, it falls back to built-in demo data.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Status, store list, last scrape time |
| GET | `/products` | All products with prices (filterable) |
| GET | `/products/{name}/history` | Price history for one product |
| GET | `/categories` | Category list with counts |
| GET | `/stores/stats` | Per-store stats (wins, avg price) |
| GET | `/compare?items=milk,bread` | Basket comparison across stores |

### Query parameters for `/products`

| Param | Type | Example |
|-------|------|---------|
| `category` | string | `?category=dairy` |
| `store` | string | `?store=rimi` |
| `search` | string | `?search=milk` |
| `min_price` | float | `?min_price=1.00` |
| `max_price` | float | `?max_price=5.00` |
| `sort` | enum | `?sort=savings` |
| `limit` | int | `?limit=50` |
| `offset` | int | `?offset=100` |

---

## Automated Scraping (GitHub Actions)

Prices update automatically every day at **08:00 Riga time**.

### Setup

1. Push the repo to GitHub
2. GitHub Actions picks up `.github/workflows/scrape.yml` automatically
3. After each run, `frontend/prices.json` is committed back to the repo

### Manual trigger

Go to **Actions → Scrape grocery prices → Run workflow** in GitHub.  
You can specify which stores to scrape and enable dry-run mode.

### On failure

If a scrape fails, a GitHub Issue is auto-created with a link to the failed run.

---

## Adding a New Store

1. Create `scrapers/newstore_scraper.py` following the pattern in `rimi_scraper.py`
2. Add it to `SCRAPERS` in `run_scrapers.py`:
   ```python
   from newstore_scraper import scrape_all as scrape_newstore
   SCRAPERS = {
       ...
       "newstore": scrape_newstore,
   }
   ```
3. Add its colour to `STORE_COLORS` in `frontend/index.html`

---

## Deployment

### API — Railway / Render / Fly.io

```bash
# Render: add a render.yaml
# Railway: just connect the repo, set start command:
uvicorn api.main:app --host 0.0.0.0 --port $PORT
```

### Frontend — GitHub Pages

Enable GitHub Pages in repo settings, pointing to the `frontend/` folder.  
The `prices.json` file (committed by the scraper) means the app works  
even without the API running.

---

## Legal note

Web scraping is generally legal for publicly available price information,  
but always review each store's Terms of Service. Scrape politely:  
use delays between requests, identify your bot with a User-Agent, and  
don't hammer servers. If a store asks you to stop, stop.
