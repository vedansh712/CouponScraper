"""
╔══════════════════════════════════════════════════════════════════╗
║           LAYA — Coupon Scraper v1.0                            ║
║  Scrapes GrabOn · CouponDunia · Brand Websites                  ║
║  Output → coupons.json  (plug into DB later)                    ║
╚══════════════════════════════════════════════════════════════════╝

USAGE:
  python scraper.py --all                        # Scrape all brands
  python scraper.py --brand "Giva"               # Single brand
  python scraper.py --category jewellery         # Entire category
  python scraper.py --brand "Giva" --dry-run     # Print only, no file write
  python scraper.py --all --output my_file.json  # Custom output path
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import logging
import argparse
import re
import os
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

OUTPUT_FILE   = "coupons.json"
BRANDS_CONFIG = "brands_config.json"
SLEEP_MIN     = 1.5   # seconds between requests (be polite)
SLEEP_MAX     = 3.5
REQUEST_TIMEOUT = 12  # seconds

# Rotate user agents so we don't get blocked as easily
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("laya_scraper")


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def get_headers() -> dict:
    """Return headers with a random User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def polite_sleep():
    """Sleep a random amount between requests to avoid hammering servers."""
    sleep_for = random.uniform(SLEEP_MIN, SLEEP_MAX)
    time.sleep(sleep_for)


def safe_get(url: str, retries: int = 2) -> Optional[BeautifulSoup]:
    """
    Fetch a URL and return a BeautifulSoup object.
    Returns None on failure (404, timeout, etc).
    """
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url,
                headers=get_headers(),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            elif resp.status_code == 404:
                log.debug(f"404 — {url}")
                return None
            elif resp.status_code == 403:
                log.warning(f"403 Blocked — {url}  (attempt {attempt+1})")
                time.sleep(5)   # back off longer on a block
            else:
                log.warning(f"HTTP {resp.status_code} — {url}")
                return None
        except requests.exceptions.Timeout:
            log.warning(f"Timeout — {url}  (attempt {attempt+1})")
        except requests.exceptions.RequestException as e:
            log.warning(f"Request error — {url}: {e}")
            return None
        polite_sleep()
    return None


def strip_json_comments(text: str) -> str:
    # remove only full-line comments, not URLs
    cleaned = re.sub(r'^\s*//.*$', '', text, flags=re.MULTILINE)
    return cleaned


def load_brands(config_path: str = BRANDS_CONFIG) -> list[dict]:
    """Load and parse brands_config.json (supports // comments)."""
    with open(config_path, "r", encoding="utf-8") as f:
        raw = f.read()
    cleaned = strip_json_comments(raw)
    brands = json.loads(cleaned)
    log.info(f"Loaded {len(brands)} brands from {config_path}")
    return brands


def make_coupon(
    brand: str,
    category: str,
    code: Optional[str],
    discount: str,
    expiry: Optional[str],
    source: str,
    source_url: str,
    confidence: str,
) -> dict:
    """Build a normalised coupon dict."""
    return {
        "brand":       brand,
        "category":    category,
        "code":        code.strip().upper() if code else None,
        "discount":    discount.strip(),
        "expiry":      expiry,
        "source":      source,
        "source_url":  source_url,
        "confidence":  confidence,  # "verified" or "unverified"
        "scraped_at":  datetime.utcnow().isoformat() + "Z",
    }


# ─────────────────────────────────────────────
#  CONFIDENCE SCORER
# ─────────────────────────────────────────────

def score_confidence(coupon: dict, seen_brands: dict) -> str:
    """
    Returns 'verified' (✅) or 'unverified' (⚠️).

    Rules:
      - Has a valid-looking expiry date → verified
      - Appears on 2+ sources for this brand → verified
      - From the brand's own website → verified
      - Otherwise → unverified
    """
    if coupon.get("source") == "brand_website":
        return "verified"

    if coupon.get("expiry"):
        return "verified"

    brand = coupon["brand"]
    code  = coupon.get("code")
    if code and brand in seen_brands and seen_brands[brand].get(code, 0) >= 2:
        return "verified"

    return "unverified"


# ─────────────────────────────────────────────
#  MODULE 1 — GRABON SCRAPER
# ─────────────────────────────────────────────

# GRABON_BASE = "https://www.grabon.in/indiastore"
GRABON_BASE = "https://www.grabon.in"

# CSS selector candidates — GrabOn updates their HTML periodically.
# The scraper tries each in order and uses the first that matches.
GRABON_SELECTORS = {
    "coupon_card": [
        "div.coupon-box",
        "div.g-coupon-wrap",
        "div.coupons-list-item",
        "li.coupon-item",
        "div[class*='coupon']",
    ],
    "code": [
        "span.coupon-code",
        "span[class*='code']",
        "input[class*='code']",
        "div.code-holder span",
        "[data-coupon-code]",
    ],
    "discount": [
        "div.coupon-title",
        "h3.offer-title",
        "p.offer-desc",
        "div[class*='title']",
        "span[class*='offer']",
    ],
    "expiry": [
        "span.valid-date",
        "span[class*='valid']",
        "span[class*='expiry']",
        "div[class*='expire']",
        "p[class*='valid']",
    ],
}


def _first_match(soup, selector_list: list, attr: Optional[str] = None) -> Optional[str]:
    """Try each CSS selector in order, return first text match."""
    for sel in selector_list:
        try:
            el = soup.select_one(sel)
            if el:
                if attr:
                    val = el.get(attr, "").strip()
                    if val:
                        return val
                text = el.get_text(strip=True)
                if text:
                    return text
        except Exception:
            continue
    return None


def _find_all_first_match(soup, selector_list: list):
    """Return all elements matching the first working selector."""
    for sel in selector_list:
        try:
            results = soup.select(sel)
            if results:
                return results
        except Exception:
            continue
    return []


def parse_expiry(raw_text: Optional[str]) -> Optional[str]:
    """
    Try to extract a date string from messy expiry text.
    e.g. "Valid till: 31 Mar 2025" → "31 Mar 2025"
         "Expires: 2025-03-31"     → "2025-03-31"
    """
    if not raw_text:
        return None
    # Remove label words
    cleaned = re.sub(
        r"(valid|till|expires?|expiry|on|date)\s*[:—-]?\s*",
        "", raw_text, flags=re.IGNORECASE
    ).strip()
    # Match common date patterns
    date_patterns = [
        r"\d{1,2}\s+\w{3,9}\s+\d{4}",       # 31 March 2025
        r"\d{4}-\d{2}-\d{2}",                 # 2025-03-31
        r"\d{1,2}/\d{1,2}/\d{4}",             # 31/03/2025
        r"\d{1,2}-\d{1,2}-\d{4}",             # 31-03-2025
    ]
    for pattern in date_patterns:
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            return m.group(0)
    return cleaned if len(cleaned) < 30 else None


def scrape_grabon(brand_config: dict) -> list[dict]:
    """Scrape coupon codes for a brand from GrabOn."""
    slug   = brand_config["grabon_slug"]
    # url    = f"{GRABON_BASE}/{slug}/"
    url = f"{GRABON_BASE}/{slug}"
    brand  = brand_config["brand"]
    cat    = brand_config["category"]

    log.info(f"  [GrabOn] {brand} → {url}")
    soup = safe_get(url)
    if not soup:
        log.debug(f"  [GrabOn] No page for {brand}")
        return []

    polite_sleep()

    coupons = []
    cards = _find_all_first_match(soup, GRABON_SELECTORS["coupon_card"])

    if not cards:
        log.debug(f"  [GrabOn] No coupon cards found for {brand}")
        # Still try to get sitewide banner text as a no-code deal
        discount_text = _first_match(soup, GRABON_SELECTORS["discount"])
        if discount_text:
            coupons.append(make_coupon(
                brand=brand, category=cat,
                code=None, discount=discount_text,
                expiry=None, source="grabon.in",
                source_url=url, confidence="unverified",
            ))
        return coupons

    for card in cards:
        # Try to get the coupon code
        code = _first_match(card, GRABON_SELECTORS["code"])
        if not code:
            # Some GrabOn codes live in data attributes
            code_el = card.select_one("[data-coupon-code], [data-clipboard-text]")
            if code_el:
                code = (
                    code_el.get("data-coupon-code")
                    or code_el.get("data-clipboard-text", "")
                ).strip()

        discount = _first_match(card, GRABON_SELECTORS["discount"]) or "Discount offer"
        expiry   = parse_expiry(_first_match(card, GRABON_SELECTORS["expiry"]))

        # Skip obviously bad entries
        if not discount or len(discount) < 3:
            continue

        coupons.append(make_coupon(
            brand=brand, category=cat,
            code=code if code else None,
            discount=discount,
            expiry=expiry,
            source="grabon.in",
            source_url=url,
            confidence="unverified",  # will be re-scored later
        ))

    log.info(f"  [GrabOn] Found {len(coupons)} coupons for {brand}")
    return coupons


# ─────────────────────────────────────────────
#  MODULE 2 — COUPONDUNIA SCRAPER
# ─────────────────────────────────────────────

COUPONDUNIA_BASE = "https://www.coupondunia.in"

COUPONDUNIA_SELECTORS = {
    "coupon_card": [
        "div.card",
        "div.offer-card",
        "div.coupon-container",
        "li.offer",
        "div[class*='coupon']",
        "div[class*='offer']",
    ],
    "code": [
        "span.coupon-code",
        "span[class*='code']",
        "button[class*='code']",
        "div.code span",
        "[data-code]",
    ],
    "discount": [
        "div.offer-heading",
        "h3.offer-title",
        "p.offer-description",
        "span[class*='title']",
        "div[class*='description']",
    ],
    "expiry": [
        "span.expires",
        "span[class*='expir']",
        "p[class*='valid']",
        "div[class*='expiry']",
    ],
}


def scrape_coupondunia(brand_config: dict) -> list[dict]:
    """Scrape coupon codes for a brand from CouponDunia."""
    slug   = brand_config["coupondunia_slug"]
    url    = f"{COUPONDUNIA_BASE}/{slug}"
    brand  = brand_config["brand"]
    cat    = brand_config["category"]

    log.info(f"  [CouponDunia] {brand} → {url}")
    soup = safe_get(url)
    if not soup:
        log.debug(f"  [CouponDunia] No page for {brand}")
        return []

    polite_sleep()

    coupons = []
    cards = _find_all_first_match(soup, COUPONDUNIA_SELECTORS["coupon_card"])

    if not cards:
        log.debug(f"  [CouponDunia] No cards for {brand}")
        return coupons

    for card in cards:
        code     = _first_match(card, COUPONDUNIA_SELECTORS["code"])
        if not code:
            code_el = card.select_one("[data-code], [data-coupon]")
            if code_el:
                code = (
                    code_el.get("data-code")
                    or code_el.get("data-coupon", "")
                ).strip()

        discount = _first_match(card, COUPONDUNIA_SELECTORS["discount"]) or "Discount offer"
        expiry   = parse_expiry(_first_match(card, COUPONDUNIA_SELECTORS["expiry"]))

        if not discount or len(discount) < 3:
            continue

        coupons.append(make_coupon(
            brand=brand, category=cat,
            code=code if code else None,
            discount=discount,
            expiry=expiry,
            source="coupondunia.in",
            source_url=url,
            confidence="unverified",
        ))

    log.info(f"  [CouponDunia] Found {len(coupons)} coupons for {brand}")
    return coupons


# ─────────────────────────────────────────────
#  MODULE 3 — BRAND WEBSITE SCRAPER
# ─────────────────────────────────────────────

# Keywords that hint at a discount/offer on a brand's own page
OFFER_KEYWORDS = re.compile(
    r"(\d+%\s*off|flat\s*₹?\d+|upto\s*\d+%|save\s*₹?\d+|free\s*shipping|"
    r"buy\s*\d+\s*get|extra\s*\d+%|code[:\s]+[A-Z0-9]+)",
    re.IGNORECASE,
)

# Coupon code patterns — looks for things like "Use code: GIVA200" or "SAVE10"
CODE_PATTERN = re.compile(
    r"(?:use\s+code|promo\s+code|coupon\s+code|code)[:\s]+([A-Z0-9]{4,20})",
    re.IGNORECASE,
)


def scrape_brand_website(brand_config: dict) -> list[dict]:
    """
    Scrape the brand's own website for sitewide banners / offer pages.
    This is the most trustworthy source — codes here are almost always active.
    """
    website     = brand_config["website"]
    offers_path = brand_config.get("offers_path", "")
    brand       = brand_config["brand"]
    cat         = brand_config["category"]

    # Try offers page first, then homepage
    urls_to_try = []
    if offers_path and offers_path != "/":
        urls_to_try.append(website.rstrip("/") + offers_path)
    urls_to_try.append(website)

    coupons = []

    for url in urls_to_try:
        log.info(f"  [Website] {brand} → {url}")
        soup = safe_get(url)
        if not soup:
            polite_sleep()
            continue

        page_text = soup.get_text(" ", strip=True)

        # Look for explicit coupon codes mentioned on page
        code_matches = CODE_PATTERN.findall(page_text)
        for code in set(code_matches):
            if len(code) < 4 or len(code) > 20:
                continue
            # Try to find context around the code
            idx = page_text.upper().find(code.upper())
            snippet = page_text[max(0, idx-60):idx+60].strip()

            coupons.append(make_coupon(
                brand=brand, category=cat,
                code=code.upper(),
                discount=snippet,
                expiry=None,
                source="brand_website",
                source_url=url,
                confidence="verified",
            ))

        # Look for offer banners even without a code
        offer_matches = OFFER_KEYWORDS.findall(page_text)
        seen_offers = set()
        for offer in offer_matches:
            offer_clean = offer.strip()
            if offer_clean.lower() in seen_offers:
                continue
            seen_offers.add(offer_clean.lower())

            coupons.append(make_coupon(
                brand=brand, category=cat,
                code=None,
                discount=offer_clean,
                expiry=None,
                source="brand_website",
                source_url=url,
                confidence="verified",
            ))

        polite_sleep()

        # If we found something on the offers page, skip homepage
        if coupons:
            break

    log.info(f"  [Website] Found {len(coupons)} offers for {brand}")
    return coupons


# ─────────────────────────────────────────────
#  DEDUPLICATOR
# ─────────────────────────────────────────────

def deduplicate(coupons: list[dict]) -> list[dict]:
    """
    Remove duplicate coupons for the same brand.
    Dedup key: brand + code (case-insensitive).
    When a code appears twice, keep the one with more info (expiry, higher confidence).
    """
    seen: dict[str, dict] = {}

    for c in coupons:
        key = f"{c['brand'].lower()}::{(c.get('code') or c.get('discount',''))[:40].lower()}"

        if key not in seen:
            seen[key] = c
        else:
            existing = seen[key]
            # Prefer entries with an expiry date
            if c.get("expiry") and not existing.get("expiry"):
                seen[key] = c
            # Prefer verified over unverified
            elif c["confidence"] == "verified" and existing["confidence"] == "unverified":
                seen[key] = c

    return list(seen.values())


# ─────────────────────────────────────────────
#  CROSS-SOURCE CONFIDENCE RE-SCORER
# ─────────────────────────────────────────────

def rescore_confidence(coupons: list[dict]) -> list[dict]:
    """
    After dedup, promote anything seen on 2+ sources to 'verified'.
    Uses a pre-dedup count map.
    """
    # Count how many sources each (brand, code) appears on
    source_count: dict[str, set] = {}
    for c in coupons:
        code = c.get("code") or ""
        key  = f"{c['brand'].lower()}::{code.lower()}"
        source_count.setdefault(key, set()).add(c["source"])

    for c in coupons:
        code = c.get("code") or ""
        key  = f"{c['brand'].lower()}::{code.lower()}"
        if len(source_count.get(key, [])) >= 2:
            c["confidence"] = "verified"

    return coupons


# ─────────────────────────────────────────────
#  OUTPUT WRITER
# ─────────────────────────────────────────────

def save_results(
    all_coupons: list[dict],
    output_path: str = OUTPUT_FILE,
    dry_run: bool = False,
):
    """
    Write results to JSON.
    Structure:
    {
      "generated_at": "...",
      "total_coupons": N,
      "brands_scraped": N,
      "coupons": [ ... ]
    }
    """
    output = {
        "generated_at":   datetime.utcnow().isoformat() + "Z",
        "total_coupons":  len(all_coupons),
        "brands_scraped": len(set(c["brand"] for c in all_coupons)),
        "coupons":        all_coupons,
    }

    if dry_run:
        print("\n" + "─" * 60)
        print(f"DRY RUN — {len(all_coupons)} coupons found (not saved)")
        print("─" * 60)
        # for c in all_coupons:
        #     tag = "✅" if c["confidence"] == "verified" else "⚠️ "
        #     code_str = f"  CODE: {c['code']}" if c.get("code") else "  (no code — sitewide deal)"
        #     print(f"{tag} [{c['brand']}] {c['discount']}{code_str}  | {c['source']}")
        # print("─" * 60 + "\n")
        for c in all_coupons:
            print("\n----------------------------------")
            print("Brand     :", c["brand"])
            print("Discount  :", c["discount"])
            print("Code      :", c.get("code"))
            print("Expiry    :", c.get("expiry"))
            print("Source    :", c["source"])
            print("Confidence:", c["confidence"])
            print("URL       :", c["source_url"])
    else:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        log.info(f"Saved {len(all_coupons)} coupons → {output_path}")

    return output


# ─────────────────────────────────────────────
#  BRAND ORCHESTRATOR
# ─────────────────────────────────────────────

def scrape_brand(brand_config: dict) -> list[dict]:
    """
    Run all 3 scrapers for a single brand and return merged, deduped results.
    """
    brand = brand_config["brand"]
    log.info(f"\n{'═'*50}")
    log.info(f"  Scraping: {brand.upper()}")
    log.info(f"{'═'*50}")

    raw_coupons = []

    # 1. GrabOn
    try:
        raw_coupons += scrape_grabon(brand_config)
    except Exception as e:
        log.error(f"GrabOn error for {brand}: {e}")

    polite_sleep()

    # 2. CouponDunia
    try:
        raw_coupons += scrape_coupondunia(brand_config)
    except Exception as e:
        log.error(f"CouponDunia error for {brand}: {e}")

    polite_sleep()

    # 3. Brand website
    # try:
    #     raw_coupons += scrape_brand_website(brand_config)
    # except Exception as e:
    #     log.error(f"Website error for {brand}: {e}")

    # Re-score confidence based on cross-source matches (before dedup)
    raw_coupons = rescore_confidence(raw_coupons)

    # Dedup
    deduped = deduplicate(raw_coupons)

    log.info(f"  → {brand}: {len(raw_coupons)} raw → {len(deduped)} unique coupons")
    return deduped


# ─────────────────────────────────────────────
#  CLI + MAIN
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Laya Coupon Scraper — scrape Indian brand coupon codes"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all", action="store_true",
        help="Scrape all brands in brands_config.json"
    )
    group.add_argument(
        "--brand", type=str,
        help='Scrape a single brand by name (e.g. --brand "Giva")'
    )
    group.add_argument(
        "--category", type=str,
        help="Scrape all brands in a category (e.g. --category jewellery)"
    )

    parser.add_argument(
        "--output", type=str, default=OUTPUT_FILE,
        help=f"Output JSON file path (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print results to console without saving to file"
    )
    parser.add_argument(
        "--config", type=str, default=BRANDS_CONFIG,
        help=f"Path to brands config JSON (default: {BRANDS_CONFIG})"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    brands = load_brands(args.config)

    # ── Filter brands based on CLI args ──
    if args.brand:
        targets = [
            b for b in brands
            if b["brand"].lower() == args.brand.lower()
        ]
        if not targets:
            log.error(f"Brand '{args.brand}' not found in config. Check spelling.")
            return

    elif args.category:
        targets = [
            b for b in brands
            if b["category"].lower() == args.category.lower()
        ]
        if not targets:
            log.error(f"Category '{args.category}' not found. "
                      f"Available: {sorted(set(b['category'] for b in brands))}")
            return

    else:  # --all
        targets = brands

    log.info(f"\nStarting scrape for {len(targets)} brand(s)...\n")

    all_coupons = []
    total = len(targets)

    for i, brand_config in enumerate(targets, 1):
        log.info(f"Progress: {i}/{total}")
        brand_coupons = scrape_brand(brand_config)
        all_coupons.extend(brand_coupons)

        # Brief pause between brands
        if i < total:
            polite_sleep()

    # ── Summary ──
    verified   = [c for c in all_coupons if c["confidence"] == "verified"]
    unverified = [c for c in all_coupons if c["confidence"] == "unverified"]
    with_code  = [c for c in all_coupons if c.get("code")]
    no_code    = [c for c in all_coupons if not c.get("code")]

    log.info(f"""
╔══════════════════════════════════════╗
║         SCRAPE COMPLETE              ║
╠══════════════════════════════════════╣
║  Brands scraped   : {len(targets):<17}║
║  Total coupons    : {len(all_coupons):<17}║
║  ✅ Verified      : {len(verified):<17}║
║  ⚠️  Unverified   : {len(unverified):<17}║
║  With code        : {len(with_code):<17}║
║  Sitewide deals   : {len(no_code):<17}║
╚══════════════════════════════════════╝
""")

    save_results(all_coupons, output_path=args.output, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
