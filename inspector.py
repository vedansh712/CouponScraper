"""
╔══════════════════════════════════════════════════════════════════╗
║           LAYA — DOM Inspector / Selector Finder                ║
║                                                                  ║
║  Run this BEFORE updating scraper.py selectors.                 ║
║  It tells you exactly what HTML structure the page has          ║
║  so you can write selectors based on real evidence.             ║
╠══════════════════════════════════════════════════════════════════╣
║  USAGE:                                                          ║
║    python inspector.py --url "https://www.grabon.in/giva-coupons/"  ║
║    python inspector.py --url "https://www.coupondunia.in/giva-coupons"  ║
║    python inspector.py --url "..." --click "a.cbtn"             ║
╚══════════════════════════════════════════════════════════════════╝
"""

import argparse
import re
import sys
from collections import Counter
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


# ── Candidates we want to test (update these as you find better ones) ──────
SELECTOR_CANDIDATES = {
    "coupon_card": [
        "div.coupon-box",
        "div.clp-coupon",
        "div[class*='coupon-box']",
        "div[class*='coupon-card']",
        "div[class*='CouponCard']",
        "div.g-coupon-wrap",
        "div.coupons-list-item",
        "li.coupon-item",
        "article",
        "div[class*='offer-card']",
        "div[class*='offerCard']",
        "div[data-testid*='coupon']",
        "div[data-testid*='offer']",
        "section[class*='coupon']",
        "li[class*='coupon']",
        "div[class*='deal']",
    ],
    "code": [
        "span.coupon-code",
        "input[class*='coupon-code']",
        "input[id*='code']",
        "span[class*='code-txt']",
        ".cbtn .visible-lg",
        "div.code-holder span",
        "[data-coupon-code]",
        "[data-clip]",
        "[data-clipboard-text]",
        "[data-code]",
        "[data-val]",
        "span[class*='code']",
        "p[class*='code']",
        "button[class*='code'] span",
        "input[class*='code']",
    ],
    "discount_title": [
        "div.coupon-title",
        "p.title",
        "h2",
        "h3",
        "h3.coupon-title",
        "p.offer-desc",
        "div[class*='title']",
        "span[class*='offer-title']",
        "p[class*='title']",
        "div[class*='heading']",
        "p[class*='heading']",
        "[data-testid*='title']",
        "[data-testid*='heading']",
    ],
    "expiry": [
        "span.validity",
        "span.valid-date",
        "span[class*='valid']",
        "span[class*='expiry']",
        "span[class*='expir']",
        "div[class*='expire']",
        "p[class*='valid']",
        "time",
        "[data-testid*='expiry']",
        "[data-testid*='valid']",
    ],
}


def fetch_page(url: str, click_selector: str = None) -> str:
    """Load a page with Playwright, optionally click buttons, return HTML."""
    print(f"\n🌐  Loading: {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
        )

        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=15000)
            print("  ✅ Page loaded (networkidle)")

            if click_selector:
                print(f"  🖱️  Clicking: {click_selector}")
                buttons = page.query_selector_all(click_selector)
                print(f"  Found {len(buttons)} button(s) matching selector")
                for btn in buttons[:10]:
                    try:
                        btn.click(timeout=2000)
                        page.wait_for_timeout(400)
                    except Exception:
                        pass
                page.wait_for_timeout(800)
                print("  ✅ Clicks done")

            html = page.content()
            print(f"  📄 HTML size: {len(html):,} bytes")
            browser.close()
            return html

        except Exception as e:
            print(f"  ❌ Error: {e}")
            browser.close()
            sys.exit(1)


def analyse(html: str, save_path: str = None):
    soup = BeautifulSoup(html, "html.parser")

    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  💾 HTML saved → {save_path}  (open in browser + Inspect Element)")

    # ── 1. SELECTOR TESTS ───────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  SELECTOR TEST RESULTS")
    print("═" * 60)

    for group, selectors in SELECTOR_CANDIDATES.items():
        print(f"\n  [{group.upper()}]")
        any_hit = False
        for sel in selectors:
            try:
                results = soup.select(sel)
                if results:
                    sample_text = results[0].get_text(" ", strip=True)[:80]
                    print(f"    ✅  {sel:<45}  → {len(results)} match(es)   sample: \"{sample_text}\"")
                    any_hit = True
            except Exception as e:
                print(f"    💥  {sel:<45}  → ERROR: {e}")

        if not any_hit:
            print(f"    ❌  ALL selectors returned 0 matches")

    # ── 2. DATA ATTRIBUTE SCAN ──────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  DATA ATTRIBUTES CONTAINING LIKELY COUPON CODES")
    print("═" * 60)

    data_attrs = [
        "data-coupon-code", "data-code", "data-val",
        "data-clipboard-text", "data-clip", "data-value",
        "data-coupon", "data-promo", "data-offer",
    ]
    found_any = False
    for attr in data_attrs:
        elements = soup.find_all(attrs={attr: True})
        for el in elements:
            val = el.get(attr, "").strip()
            if val and 3 < len(val) < 30:
                print(f"    [{attr}] = \"{val}\"   tag: <{el.name}> class: {el.get('class', '')}")
                found_any = True
    if not found_any:
        print("    ❌  No data attributes found with coupon-like values")

    # ── 3. PROMO CODE PATTERN SCAN ──────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  PROMO CODE PATTERN SCAN  (all-caps 4-20 char strings in page text)")
    print("═" * 60)

    page_text = soup.get_text(" ", strip=True)
    code_pattern = re.compile(r"\b([A-Z][A-Z0-9]{3,19})\b")
    false_positives = {
        "HTTP", "HTML", "FREE", "SALE", "UPTO", "GRAB", "DEAL", "CODE", "SHOP",
        "SAVE", "FLAT", "BEST", "GIVA", "INDIA", "OFFER", "VALID", "MORE",
        "APPLY", "VIEW", "SHOW", "COPY", "EXTRA", "FIRST", "ORDER", "HOME",
        "BRAND", "CART", "USER", "EMAIL", "LOGIN", "SIGN",
    }
    candidates = [m for m in code_pattern.findall(page_text) if m not in false_positives]
    counts = Counter(candidates)
    top = counts.most_common(20)
    if top:
        for code, count in top:
            print(f"    \"{code}\"   (appears {count}x)")
    else:
        print("    ❌  No code-like strings found in page text")

    # ── 4. ALL UNIQUE CLASSES ON THE PAGE ───────────────────────────────────
    print("\n" + "═" * 60)
    print("  ALL UNIQUE CSS CLASSES ON PAGE  (look for coupon/offer/code ones)")
    print("═" * 60)

    all_classes = set()
    for tag in soup.find_all(True):
        for cls in tag.get("class", []):
            all_classes.add(cls)

    # Filter to only classes that look coupon/deal/offer related
    keywords = ["coupon", "offer", "deal", "code", "promo", "discount",
                "reveal", "valid", "expir", "card", "title", "btn"]
    relevant = sorted(
        c for c in all_classes
        if any(k in c.lower() for k in keywords)
    )

    if relevant:
        print(f"\n  Coupon/offer-related classes ({len(relevant)} found):")
        for cls in relevant:
            tag_using_it = soup.find(class_=cls)
            tag_name = tag_using_it.name if tag_using_it else "?"
            print(f"    .{cls}   (on <{tag_name}>)")
    else:
        print("  ⚠️  No obviously named coupon classes found.")
        print("  This usually means the site uses hashed/randomised class names.")
        print("  → Try data-testid attributes or structural selectors (article, section, li)")

    # Also show ALL classes if no relevant ones found
    if not relevant:
        print(f"\n  All {len(all_classes)} classes on page:")
        for cls in sorted(all_classes)[:100]:
            print(f"    .{cls}")

    # ── 5. STRUCTURAL SUMMARY ───────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  STRUCTURAL SUMMARY  (tags that appear many times = repeating cards)")
    print("═" * 60)

    tag_counts = Counter(tag.name for tag in soup.find_all(True))
    for tag_name, count in tag_counts.most_common(20):
        bar = "█" * min(count // 2, 40)
        print(f"    <{tag_name:<12}> {count:>4}   {bar}")

    # ── 6. QUICK RECOMMENDATION ─────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  RECOMMENDED NEXT STEPS")
    print("═" * 60)

    card_hits = []
    for sel in SELECTOR_CANDIDATES["coupon_card"]:
        try:
            if soup.select(sel):
                card_hits.append(sel)
        except Exception:
            pass

    if card_hits:
        print(f"\n  ✅ Use this as your coupon_card selector:")
        print(f"     \"{card_hits[0]}\"")
        print(f"\n  Also matched: {card_hits[1:3]}")
    else:
        print("\n  ❌ No card selector matched. This site likely uses:")
        print("     - Hashed class names (React/Next.js)")
        print("     - Dynamically injected content after heavy JS")
        print(f"\n  💡 Open the saved HTML in browser, Ctrl+F for a known brand name")
        print(f"     or coupon code, then inspect that element.")

    print("\n" + "═" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Laya DOM Inspector — find real selectors")
    parser.add_argument("--url",   required=True, help="URL to inspect")
    parser.add_argument("--click", default=None,  help="CSS selector of buttons to click before reading DOM")
    parser.add_argument("--save",  default="inspector_output.html", help="Path to save raw HTML (default: inspector_output.html)")
    args = parser.parse_args()

    html = fetch_page(args.url, click_selector=args.click)
    analyse(html, save_path=args.save)


if __name__ == "__main__":
    main()
    