"""
FastAPI backend — Latvia Grocery Price Tracker
Serves price data from SQLite, with filtering, search, and price history.

Run locally:
    pip install fastapi uvicorn
    uvicorn main:app --reload --port 8000

Docs auto-generated at: http://localhost:8000/docs
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DB_PATH = Path("prices.db")

app = FastAPI(
    title="Latvia Grocery Price Tracker",
    description="Compare grocery prices across Latvian stores: Rimi, Maxima, Mego, Elvi, Lidl, Lats, Top",
    version="1.0.0",
)

# Allow the frontend (any origin in dev, restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Database helpers ──────────────────────────────────────────────────────────

@contextmanager
def get_db():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database not found. Run the scraper first.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ── Response models ───────────────────────────────────────────────────────────

class StorePrice(BaseModel):
    store: str
    price: float
    scraped_at: str
    product_url: Optional[str] = None


class ProductComparison(BaseModel):
    name: str
    unit: str
    category: str
    image_url: Optional[str]
    prices: list[StorePrice]
    best_store: str
    best_price: float
    worst_price: float
    savings: float


class PriceHistoryPoint(BaseModel):
    store: str
    price: float
    recorded_at: str


class StoreStats(BaseModel):
    store: str
    product_count: int
    avg_price: float
    cheapest_count: int


class ApiStatus(BaseModel):
    status: str
    last_scrape: Optional[str]
    total_products: int
    stores: list[str]
    categories: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", response_model=ApiStatus)
def root():
    """API health check and summary."""
    with get_db() as db:
        total = db.execute("SELECT COUNT(DISTINCT name) FROM products").fetchone()[0]
        stores = [r[0] for r in db.execute("SELECT DISTINCT store FROM products").fetchall()]
        categories = [r[0] for r in db.execute("SELECT DISTINCT category FROM products").fetchall()]
        last = db.execute("SELECT MAX(scraped_at) FROM products").fetchone()[0]
    return ApiStatus(
        status="ok",
        last_scrape=last,
        total_products=total,
        stores=sorted(stores),
        categories=sorted(categories),
    )


@app.get("/products", response_model=list[ProductComparison])
def get_products(
    category: Optional[str] = Query(None, description="Filter by category"),
    store: Optional[str] = Query(None, description="Filter by store"),
    search: Optional[str] = Query(None, description="Search product name"),
    min_price: Optional[float] = Query(None, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, description="Maximum price filter"),
    sort: str = Query("name", enum=["name", "savings", "price_asc", "price_desc"]),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Get all products with prices from every store, grouped for comparison.
    """
    with get_db() as db:
        query = """
            SELECT store, name, price, unit, category, image_url, product_url, scraped_at
            FROM products
            WHERE 1=1
        """
        params: list = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if store:
            query += " AND store = ?"
            params.append(store)
        if search:
            query += " AND name LIKE ?"
            params.append(f"%{search}%")
        if min_price is not None:
            query += " AND price >= ?"
            params.append(min_price)
        if max_price is not None:
            query += " AND price <= ?"
            params.append(max_price)

        rows = db.execute(query, params).fetchall()

    # Group by product name
    grouped: dict[str, dict] = {}
    for row in rows:
        key = row["name"]
        if key not in grouped:
            grouped[key] = {
                "name": row["name"],
                "unit": row["unit"] or "",
                "category": row["category"] or "",
                "image_url": row["image_url"],
                "prices": [],
            }
        grouped[key]["prices"].append(StorePrice(
            store=row["store"],
            price=row["price"],
            scraped_at=row["scraped_at"],
            product_url=row["product_url"],
        ))

    # Build comparison objects
    comparisons = []
    for data in grouped.values():
        prices = data["prices"]
        if not prices:
            continue
        price_vals = [p.price for p in prices]
        best_price = min(price_vals)
        worst_price = max(price_vals)
        best_store = next(p.store for p in prices if p.price == best_price)
        comparisons.append(ProductComparison(
            **{k: v for k, v in data.items() if k != "prices"},
            prices=sorted(prices, key=lambda p: p.price),
            best_store=best_store,
            best_price=round(best_price, 2),
            worst_price=round(worst_price, 2),
            savings=round(worst_price - best_price, 2),
        ))

    # Sort
    if sort == "savings":
        comparisons.sort(key=lambda p: p.savings, reverse=True)
    elif sort == "price_asc":
        comparisons.sort(key=lambda p: p.best_price)
    elif sort == "price_desc":
        comparisons.sort(key=lambda p: p.best_price, reverse=True)
    else:
        comparisons.sort(key=lambda p: p.name)

    return comparisons[offset: offset + limit]


@app.get("/products/{name}/history", response_model=list[PriceHistoryPoint])
def get_price_history(name: str, store: Optional[str] = Query(None)):
    """
    Get the price history for a specific product (optionally filtered by store).
    Useful for showing price trends over time.
    """
    with get_db() as db:
        query = "SELECT store, price, recorded_at FROM price_history WHERE name = ?"
        params: list = [name]
        if store:
            query += " AND store = ?"
            params.append(store)
        query += " ORDER BY recorded_at ASC"
        rows = db.execute(query, params).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No history found for '{name}'")

    return [PriceHistoryPoint(store=r["store"], price=r["price"], recorded_at=r["recorded_at"]) for r in rows]


@app.get("/categories")
def get_categories():
    """List all available product categories."""
    with get_db() as db:
        rows = db.execute(
            "SELECT category, COUNT(DISTINCT name) as count FROM products GROUP BY category ORDER BY category"
        ).fetchall()
    return [{"category": r["category"], "product_count": r["count"]} for r in rows]


@app.get("/stores/stats", response_model=list[StoreStats])
def get_store_stats():
    """
    Stats per store: how many products, average price, and how often
    each store is the cheapest option.
    """
    with get_db() as db:
        # Get all products with all store prices
        rows = db.execute(
            "SELECT store, name, price FROM products ORDER BY name, price"
        ).fetchall()

    # Count wins (cheapest per product)
    by_product: dict[str, list] = {}
    for r in rows:
        by_product.setdefault(r["name"], []).append((r["store"], r["price"]))

    cheapest_wins: dict[str, int] = {}
    for name, entries in by_product.items():
        min_price = min(e[1] for e in entries)
        winner = next(e[0] for e in entries if e[1] == min_price)
        cheapest_wins[winner] = cheapest_wins.get(winner, 0) + 1

    # Per-store aggregate stats
    store_data: dict[str, dict] = {}
    for r in rows:
        s = r["store"]
        if s not in store_data:
            store_data[s] = {"prices": [], "names": set()}
        store_data[s]["prices"].append(r["price"])
        store_data[s]["names"].add(r["name"])

    return sorted([
        StoreStats(
            store=store,
            product_count=len(d["names"]),
            avg_price=round(sum(d["prices"]) / len(d["prices"]), 2),
            cheapest_count=cheapest_wins.get(store, 0),
        )
        for store, d in store_data.items()
    ], key=lambda s: s.cheapest_count, reverse=True)


@app.get("/compare")
def compare_basket(items: str = Query(..., description="Comma-separated product names")):
    """
    Given a basket of items, return the cheapest store for each and the
    optimal split (which store minimises total basket cost).
    """
    names = [n.strip() for n in items.split(",") if n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="Provide at least one item name.")

    with get_db() as db:
        results = {}
        for name in names:
            rows = db.execute(
                "SELECT store, price, product_url FROM products WHERE name LIKE ? ORDER BY price ASC",
                (f"%{name}%",),
            ).fetchall()
            if rows:
                results[name] = [{"store": r["store"], "price": r["price"], "url": r["product_url"]} for r in rows]

    # Calculate cheapest whole-basket per store
    store_totals: dict[str, float] = {}
    for item_prices in results.values():
        for entry in item_prices:
            store_totals.setdefault(entry["store"], 0)
            store_totals[entry["store"]] += entry["price"]

    best_single_store = min(store_totals, key=store_totals.get) if store_totals else None

    return {
        "items": results,
        "store_totals": {k: round(v, 2) for k, v in sorted(store_totals.items(), key=lambda x: x[1])},
        "best_single_store": best_single_store,
        "best_single_store_total": round(store_totals[best_single_store], 2) if best_single_store else None,
    }
