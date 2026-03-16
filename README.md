# 🏷️ Laya Coupon Scraper

Scrapes publicly listed coupon codes for Indian lifestyle brands from:
- **GrabOn** (`grabon.in`)
- **CouponDunia** (`coupondunia.in`)
- **Brand's own website** (offers pages + homepage banners)

Outputs a clean `coupons.json` file ready to be ingested into your app's database.

---

## ⚡ Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Test with one brand first
python scraper.py --brand "Giva" --dry-run

# 3. Run a full category
python scraper.py --category jewellery

# 4. Run everything
python scraper.py --all

# 5. Custom output path
python scraper.py --all --output /path/to/your/coupons.json
```

---

## 📁 File Structure

```
coupon_scraper/
├── scraper.py          ← Main script (run this)
├── brands_config.json  ← Brand list with slugs + URLs
├── requirements.txt    ← Python dependencies
├── coupons.json        ← Output (auto-generated)
└── scraper.log         ← Run log (auto-generated)
```

---

## 📦 Output Format

```json
{
  "generated_at": "2025-03-15T10:00:00Z",
  "total_coupons": 148,
  "brands_scraped": 42,
  "coupons": [
    {
      "brand": "Giva",
      "category": "jewellery",
      "code": "GIVA200",
      "discount": "₹200 off on orders above ₹999",
      "expiry": "31 Mar 2025",
      "source": "grabon.in",
      "source_url": "https://www.grabon.in/indiastore/giva-coupons/",
      "confidence": "verified",
      "scraped_at": "2025-03-15T10:00:00Z"
    }
  ]
}
```

### Confidence Tags
| Tag | Meaning |
|-----|---------|
| `verified` ✅ | Has expiry date, OR found on 2+ sources, OR from brand's own site |
| `unverified` ⚠️ | Listed on only 1 source with no expiry date |

---

## 🔧 Tuning the Scraper

### If a brand returns 0 coupons
The GrabOn/CouponDunia slugs in `brands_config.json` might be wrong.

1. Go to `grabon.in` and search for the brand
2. Copy the URL slug from the browser (e.g. `giva-coupons`)
3. Update the `grabon_slug` field in `brands_config.json`

### If you're getting blocked (403s)
Increase sleep times in `scraper.py`:
```python
SLEEP_MIN = 3.0   # was 1.5
SLEEP_MAX = 6.0   # was 3.5
```

### If HTML structure has changed
GrabOn/CouponDunia update their HTML periodically. Update the selector lists at the top of each module:
```python
GRABON_SELECTORS = {
    "coupon_card": ["div.coupon-box", ...],   # ← add new selectors here
    ...
}
```

### How to find the right selector
1. Open the brand's GrabOn page in Chrome
2. Right-click a coupon card → Inspect
3. Find the CSS class of the card container, code span, and expiry span
4. Add them to the selector lists

---

## 🗓️ Scheduling (run every 12 hours)

### On Linux/Mac (cron)
```bash
crontab -e
# Add this line:
0 */12 * * * cd /path/to/coupon_scraper && python scraper.py --all >> cron.log 2>&1
```

### On Windows (Task Scheduler)
Create a basic task that runs:
```
python C:\path\to\coupon_scraper\scraper.py --all
```

---

## 🔌 Connecting to Your Database (next step)

When you're ready to write to your app's DB instead of a JSON file,
replace the `save_results()` function at the bottom of `scraper.py` with a DB writer.

Example for MySQL:
```python
import mysql.connector

def write_to_db(coupons: list[dict]):
    conn = mysql.connector.connect(
        host="your-host", user="your-user",
        password="your-password", database="your-db"
    )
    cursor = conn.cursor()
    for c in coupons:
        cursor.execute("""
            INSERT INTO coupons (brand, category, code, discount, expiry, source, confidence, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                discount=VALUES(discount), expiry=VALUES(expiry),
                confidence=VALUES(confidence), scraped_at=VALUES(scraped_at)
        """, (
            c['brand'], c['category'], c['code'], c['discount'],
            c['expiry'], c['source'], c['confidence'], c['scraped_at']
        ))
    conn.commit()
    cursor.close()
    conn.close()
```
