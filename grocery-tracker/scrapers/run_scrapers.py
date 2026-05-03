"""
run_scrapers.py — Master scraper runner
Runs all store scrapers, deduplicates results, and writes to SQLite database.
Also exports a fresh prices.json for the frontend.

Usage:
    python run_scrapers.py                   # run all scrapers
    python run_scrapers.py --stores rimi     # run specific stores
    python run_scrapers.py --dry-run         # scrape but don't save
"""

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from rimi_scraper import scrape_all as scrape_rimi
from maxima_scraper import scrape_all as scrape_maxima

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("run_scrapers")

DB_PATH = Path("../api/prices.db")
EXPORT_PATH = Path("../frontend/prices.json")

SCRAPERS = {
    "rimi": scrape_rimi,
    "maxima": scrape_maxima,
    # Add new stores here:
    # "mego": scrape_mego,
    # "elvi": scrape_elvi,
    # "lidl": scrape_lidl,
}


def init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            store       TEXT NOT NULL,
            name        TEXT NOT NULL,
            price       REAL NOT NULL,
            unit        TEXT,
            category    TEXT,
            image_url   TEXT,
            product_url TEXT,
            scraped_at  TEXT NOT NULL,
            UNIQUE(store, name)
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            store       TEXT NOT NULL,
            name        TEXT NOT NULL,
            price       REAL NOT NULL,
            recorded_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_products_store    ON products(store);
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
        CREATE INDEX IF NOT EXISTS idx_history_store     ON price_history(store);
        CREATE INDEX IF NOT EXISTS idx_history_name      ON price_history(name);
    """)
    conn.commit()


def upsert_products(conn: sqlite3.Connection, products: list[dict]):
    """Insert or update products, recording price changes in history."""
    inserted, updated, unchanged = 0, 0, 0

    for p in products:
        existing = conn.execute(
            "SELECT price FROM products WHERE store = ? AND name = ?",
            (p["store"], p["name"]),
        ).fetchone()

        if existing is None:
            conn.execute(
                """INSERT INTO products (store, name, price, unit, category,
                   image_url, product_url, scraped_at)
                   VALUES (:store, :name, :price, :unit, :category,
                   :image_url, :product_url, :scraped_at)""",
                p,
            )
            inserted += 1
        elif abs(existing[0] - p["price"]) > 0.001:
            conn.execute(
                """UPDATE products
                   SET price=:price, unit=:unit, image_url=:image_url,
                       product_url=:product_url, scraped_at=:scraped_at
                   WHERE store=:store AND name=:name""",
                p,
            )
            # Log the price change
            conn.execute(
                "INSERT INTO price_history (store, name, price, recorded_at) VALUES (?,?,?,?)",
                (p["store"], p["name"], p["price"], p["scraped_at"]),
            )
            updated += 1
        else:
            unchanged += 1

    conn.commit()
    return inserted, updated, unchanged


def export_json(conn: sqlite3.Connection, path: Path):
    """Export current prices to a JSON file for the frontend."""
    rows = conn.execute(
        "SELECT store, name, price, unit, category, image_url, product_url, scraped_at "
        "FROM products ORDER BY category, name"
    ).fetchall()

    cols = ["store", "name", "price", "unit", "category", "image_url", "product_url", "scraped_at"]
    products = [dict(zip(cols, row)) for row in rows]

    # Group by product name for easy comparison view
    grouped: dict[str, dict] = {}
    for p in products:
        key = p["name"]
        if key not in grouped:
            grouped[key] = {
                "name": p["name"],
                "unit": p["unit"],
                "category": p["category"],
                "prices": {},
                "image_url": p["image_url"],
            }
        grouped[key]["prices"][p["store"]] = p["price"]

    output = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_products": len(grouped),
        "stores": list({p["store"] for p in products}),
        "products": list(grouped.values()),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"Exported {len(grouped)} products to {path}")


def run(stores: list[str], dry_run: bool = False):
    start = time.time()
    all_products = []

    for store_name in stores:
        if store_name not in SCRAPERS:
            log.warning(f"Unknown store: {store_name}, skipping.")
            continue
        log.info(f"=== Starting scrape: {store_name} ===")
        try:
            products = SCRAPERS[store_name]()
            log.info(f"=== {store_name}: {len(products)} products scraped ===")
            all_products.extend(products)
        except Exception as e:
            log.error(f"Scraper failed for {store_name}: {e}", exc_info=True)

    log.info(f"Total products scraped: {len(all_products)}")

    if dry_run:
        log.info("Dry run — not saving to database.")
        print(json.dumps(all_products[:5], indent=2, ensure_ascii=False))
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    inserted, updated, unchanged = upsert_products(conn, all_products)
    log.info(f"DB: {inserted} inserted, {updated} updated, {unchanged} unchanged")

    export_json(conn, EXPORT_PATH)
    conn.close()

    elapsed = round(time.time() - start, 1)
    log.info(f"All done in {elapsed}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run grocery price scrapers")
    parser.add_argument(
        "--stores", nargs="+", default=list(SCRAPERS.keys()),
        help="Which stores to scrape (default: all)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()
    run(args.stores, dry_run=args.dry_run)
