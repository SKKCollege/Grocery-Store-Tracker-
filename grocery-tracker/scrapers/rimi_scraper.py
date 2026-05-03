"""
Rimi Latvia grocery price scraper
Scrapes product listings from rimi.lv using their internal API
and category page structure.
"""

import requests
import json
import time
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("rimi_scraper")


@dataclass
class Product:
    store: str
    name: str
    price: float
    unit: str
    category: str
    image_url: Optional[str]
    product_url: str
    scraped_at: str


# Rimi uses a GraphQL-like internal API for its online store.
# These category slugs map to their site structure.
RIMI_CATEGORIES = {
    "dairy":    "piena-produkti-un-olas",
    "bakery":   "maize-un-konditoreja",
    "meat":     "gala-un-zivis",
    "seafood":  "zivis-un-juras-veltes",
    "produce":  "augti-un-darzeni",
    "pantry":   "pārtika",
    "drinks":   "dzērieni",
    "snacks":   "uzkodas",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html",
    "Accept-Language": "lv-LV,lv;q=0.9,en;q=0.8",
    "Referer": "https://www.rimi.lv/",
}

BASE_URL = "https://www.rimi.lv"
API_URL = f"{BASE_URL}/e-veikals/api/products"


def fetch_category_page(category_slug: str, page: int = 1, page_size: int = 80) -> dict:
    """
    Fetch one page of products from Rimi's internal JSON API.
    Rimi loads products via XHR — we call the same endpoint directly.
    """
    params = {
        "query": "",
        "category": category_slug,
        "page": page,
        "pageSize": page_size,
        "sort": "relevance",
    }
    try:
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.error(f"Request failed for category '{category_slug}' page {page}: {e}")
        return {}


def parse_products(raw: dict, category: str) -> list[Product]:
    """Parse raw API response into Product objects."""
    products = []
    items = raw.get("products", raw.get("items", []))

    for item in items:
        try:
            name = item.get("name", "").strip()
            if not name:
                continue

            # Rimi stores price in cents in some responses; normalise
            price_raw = item.get("price", item.get("priceFormatted", 0))
            if isinstance(price_raw, str):
                price = float(price_raw.replace("€", "").replace(",", ".").strip())
            else:
                price = float(price_raw)

            if price <= 0:
                continue

            unit = item.get("salesUnit", item.get("unit", "")).strip() or "unit"
            image = (item.get("images") or [{}])[0].get("url", "")
            slug = item.get("url", item.get("slug", ""))
            url = f"{BASE_URL}{slug}" if slug.startswith("/") else slug

            products.append(Product(
                store="rimi",
                name=name,
                price=round(price, 2),
                unit=unit,
                category=category,
                image_url=image or None,
                product_url=url,
                scraped_at=datetime.utcnow().isoformat(),
            ))
        except (ValueError, KeyError, TypeError) as e:
            log.warning(f"Skipping malformed product: {e} — {item}")

    return products


def scrape_category(category: str, slug: str, max_pages: int = 5) -> list[Product]:
    """Scrape all pages of a single category."""
    all_products = []
    for page in range(1, max_pages + 1):
        log.info(f"  Rimi › {category} › page {page}")
        raw = fetch_category_page(slug, page=page)
        if not raw:
            break
        products = parse_products(raw, category)
        if not products:
            log.info(f"  No more products found at page {page}, stopping.")
            break
        all_products.extend(products)
        # Polite delay between pages
        time.sleep(1.2)
    return all_products


def scrape_all(max_pages_per_category: int = 5) -> list[dict]:
    """Scrape all categories from Rimi and return as list of dicts."""
    results = []
    for category, slug in RIMI_CATEGORIES.items():
        log.info(f"Scraping Rimi category: {category}")
        products = scrape_category(category, slug, max_pages=max_pages_per_category)
        log.info(f"  → {len(products)} products from {category}")
        results.extend([asdict(p) for p in products])
        # Polite delay between categories
        time.sleep(2.0)
    log.info(f"Rimi scrape complete. Total products: {len(results)}")
    return results


if __name__ == "__main__":
    import sys
    output_file = sys.argv[1] if len(sys.argv) > 1 else "rimi_products.json"
    data = scrape_all(max_pages_per_category=3)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(data)} products to {output_file}")
