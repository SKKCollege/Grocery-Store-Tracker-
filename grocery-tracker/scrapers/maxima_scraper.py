"""
Maxima Latvia grocery price scraper
Scrapes product listings from maxima.lv.
Maxima exposes a REST API for its e-store — we target that directly.
"""

import requests
import json
import time
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("maxima_scraper")


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


# Maxima category IDs — discovered by inspecting network requests on maxima.lv
MAXIMA_CATEGORIES = {
    "dairy":    "piena-produkti",
    "bakery":   "maize-konditorejas-izstradajumi",
    "meat":     "gala-produkti",
    "seafood":  "zivis-juras-veltes",
    "produce":  "augti-darzeni",
    "pantry":   "partika",
    "drinks":   "dzerieni",
    "snacks":   "uzkodas-saldie-un-salenie",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "lv,en;q=0.8",
    "Origin": "https://www.maxima.lv",
    "Referer": "https://www.maxima.lv/",
    "x-requested-with": "XMLHttpRequest",
}

BASE_URL = "https://www.maxima.lv"
API_URL = f"{BASE_URL}/api/products"


def fetch_page(category_slug: str, page: int = 1, per_page: int = 60) -> dict:
    """Fetch one page of products from Maxima's product API."""
    params = {
        "category": category_slug,
        "page": page,
        "limit": per_page,
        "sort": "default",
        "lang": "lv",
    }
    try:
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.error(f"Request failed for '{category_slug}' page {page}: {e}")
        return {}


def parse_products(raw: dict, category: str) -> list[Product]:
    """Parse Maxima API response into Product objects."""
    products = []
    # Maxima wraps items under different keys depending on API version
    items = (
        raw.get("items")
        or raw.get("products")
        or raw.get("data", {}).get("items", [])
    )

    for item in items:
        try:
            name = (item.get("title") or item.get("name") or "").strip()
            if not name:
                continue

            # Maxima price is usually a float in EUR
            price_raw = (
                item.get("price")
                or item.get("currentPrice")
                or item.get("regularPrice")
                or 0
            )
            if isinstance(price_raw, str):
                price = float(price_raw.replace(",", ".").replace("€", "").strip())
            else:
                price = float(price_raw)

            if price <= 0:
                continue

            unit = (
                item.get("unit")
                or item.get("salesUnit")
                or item.get("quantityUnit")
                or "unit"
            ).strip()

            image = ""
            imgs = item.get("images") or item.get("image") or []
            if isinstance(imgs, list) and imgs:
                image = imgs[0].get("url", "") if isinstance(imgs[0], dict) else imgs[0]
            elif isinstance(imgs, str):
                image = imgs

            slug = item.get("url") or item.get("slug") or item.get("link") or ""
            url = f"{BASE_URL}{slug}" if slug.startswith("/") else (slug or BASE_URL)

            products.append(Product(
                store="maxima",
                name=name,
                price=round(price, 2),
                unit=unit,
                category=category,
                image_url=image or None,
                product_url=url,
                scraped_at=datetime.utcnow().isoformat(),
            ))
        except (ValueError, KeyError, TypeError) as e:
            log.warning(f"Skipping malformed product: {e}")

    return products


def scrape_category(category: str, slug: str, max_pages: int = 5) -> list[Product]:
    """Scrape all paginated results for one category."""
    all_products = []
    for page in range(1, max_pages + 1):
        log.info(f"  Maxima › {category} › page {page}")
        raw = fetch_page(slug, page=page)
        if not raw:
            break
        products = parse_products(raw, category)
        if not products:
            log.info(f"  No more products at page {page}.")
            break
        all_products.extend(products)
        time.sleep(1.0)
    return all_products


def scrape_all(max_pages_per_category: int = 5) -> list[dict]:
    """Scrape all Maxima categories."""
    results = []
    for category, slug in MAXIMA_CATEGORIES.items():
        log.info(f"Scraping Maxima category: {category}")
        products = scrape_category(category, slug, max_pages=max_pages_per_category)
        log.info(f"  → {len(products)} products from {category}")
        results.extend([asdict(p) for p in products])
        time.sleep(2.0)
    log.info(f"Maxima scrape complete. Total products: {len(results)}")
    return results


if __name__ == "__main__":
    import sys
    output_file = sys.argv[1] if len(sys.argv) > 1 else "maxima_products.json"
    data = scrape_all(max_pages_per_category=3)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(data)} products to {output_file}")
