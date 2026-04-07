#!/usr/bin/env python3
"""
Dansk Vin Tilbud Scraper - GitHub Actions version
Bruger Playwright (headless Chromium) til at scrape de stoerste danske vinwebsites.
Koerer dagligt via GitHub Actions og gemmer wine_deals.json.
"""

import json
import re
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

def parse_price(txt):
    if not txt:
        return None
    m = re.search(r'([\d]+[,\.][\d]{1,2})', txt.replace('\xa0', ''))
    return float(m.group(1).replace(',', '.')) if m else None

def guess_wine_type(name):
    n = name.lower()
    if any(w in n for w in ['champagne', 'cremant', 'cava', 'prosecco', 'mousserende', 'sekt', 'sparkling']):
        return 'mousserende'
    if any(w in n for w in ['rose', 'rosvin']):
        return 'rose'
    if any(w in n for w in ['chardonnay', 'riesling', 'sauvignon blanc', 'pinot gris', 'hvidvin',
                             'gruner', 'verdejo', 'blanc', 'chenin', 'viognier', 'albarino']):
        return 'hvidvin'
    if any(w in n for w in ['cabernet', 'merlot', 'syrah', 'shiraz', 'malbec', 'pinot noir',
                             'tempranillo', 'sangiovese', 'grenache', 'garnacha', 'monastrell',
                             'primitivo', 'rodvin', 'nebbiolo']):
        return 'rodvin'
    return 'ukendt'

def scrape_andrupvin(page):
    deals = []
    for url in ['https://www.andrupvin.dk/vintilbud', 'https://www.andrupvin.dk/spring-sale']:
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(2000)
            try:
                page.click('button:has-text("OK til alle")', timeout=3000)
            except:
                pass
            items = page.query_selector_all('.product-item, .item.product')
            for el in items:
                try:
                    name_el = el.query_selector('.product-item-link, h2, h3')
                    name = name_el.inner_text().strip() if name_el else ''
                    link_el = el.query_selector('a.product-item-link, a')
                    url_prod = link_el.get_attribute('href') if link_el else url
                    badge_el = el.query_selector('[class*="badge"], [class*="label"], [class*="tag"]')
                    badge = badge_el.inner_text().strip() if badge_el else ''
                    disc_match = re.search(r'(\d+)\s*%', badge)
                    disc_pct = int(disc_match.group(1)) if disc_match else None
                    prices = []
                    for p in el.query_selector_all('.price'):
                        v = parse_price(p.inner_text())
                        if v and 10 < v < 50000:
                            prices.append(v)
                    cur = min(prices) if prices else None
                    old = max(prices) if len(prices) > 1 else None
                    computed = round((1 - cur/old)*100) if (old and cur and old > cur) else disc_pct
                    if not name or not cur:
                        continue
                    deals.append({
                        'name': name[:100], 'current_price': cur,
                        'original_price': old if old != cur else None,
                        'discount_pct': computed,
                        'url': url_prod, 'store': 'AndrupVin',
                        'store_url': 'https://www.andrupvin.dk',
                        'wine_type': guess_wine_type(name),
                        'scraped_at': datetime.now().isoformat(),
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f'  AndrupVin fejl ({url}): {e}')
    return deals

def scrape_jyskvin(page):
    deals = []
    try:
        page.goto('https://www.jyskvin.dk/vintilbud', wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(2000)
        try:
            page.click('button:has-text("Accepter")', timeout=3000)
        except:
            pass
        for el in page.query_selector_all('a.entity-teaser--product'):
            try:
                name_el = el.query_selector('[class*="title"], h2, h3')
                price_el = el.query_selector('.entity-teaser__price--highlighted')
                old_el = el.query_selector('del, s')
                name = name_el.inner_text().strip() if name_el else ''
                cur = parse_price(price_el.inner_text() if price_el else '')
                old = parse_price(old_el.inner_text() if old_el else '')
                href = el.get_attribute('href') or 'https://www.jyskvin.dk/vintilbud'
                if not name or not cur:
                    continue
                disc = round((1-cur/old)*100) if (old and old > cur) else None
                deals.append({
                    'name': name[:100], 'current_price': cur,
                    'original_price': old or None, 'discount_pct': disc,
                    'url': href if href.startswith('http') else 'https://www.jyskvin.dk' + href,
                    'store': 'JyskVin', 'store_url': 'https://www.jyskvin.dk',
                    'wine_type': guess_wine_type(name),
                    'scraped_at': datetime.now().isoformat(),
                })
            except Exception:
                continue
    except Exception as e:
        print(f'  JyskVin fejl: {e}')
    return deals

def scrape_supervin(page):
    deals = []
    urls = [
        'https://www.supervin.dk/tilbud/top10',
        'https://www.supervin.dk/tilbud/hvidvin',
        'https://www.supervin.dk/tilbud/fransk-rodvin',
        'https://www.supervin.dk/tilbud/italiensk-rodvin',
        'https://www.supervin.dk/tilbud/spansk-rodvin',
        'https://www.supervin.dk/tilbud/rose-vin',
    ]
    seen = set()
    for url in urls:
        try:
            page.goto(url, wait_until='networkidle', timeout=25000)
            page.wait_for_timeout(2000)
            try:
                page.click('button:has-text("Kun nodvendige")', timeout=3000)
            except:
                pass
            for el in page.query_selector_all('.product-top'):
                try:
                    data = el.evaluate('''el => {
                        const w = el.closest(".item") || el.parentElement?.parentElement;
                        const name = w?.querySelector("h2,h3,h4")?.innerText?.trim() || "";
                        const baseEl = w?.querySelector(".price.base-price");
                        const basePrice = parseFloat((baseEl?.getAttribute("data-price") || "").replace(",", ".")) || null;
                        const badge = w?.querySelector("[class*=badge],[class*=discount]")?.innerText?.trim() || "";
                        const m = badge.match(/([\\d,.]+)\\s*DKK/);
                        const bulk = m ? parseFloat(m[1].replace(",", ".")) : null;
                        const disc = (bulk && basePrice && bulk < basePrice) ? Math.round((1 - bulk/basePrice)*100) : null;
                        const link = w?.querySelector("a[href]");
                        const url = link?.href || "";
                        return { name, basePrice, bulk, disc, url };
                    }''')
                    if not data['name'] or not data['basePrice'] or data['name'] in seen:
                        continue
                    seen.add(data['name'])
                    deals.append({
                        'name': data['name'][:100],
                        'current_price': data['basePrice'],
                        'original_price': None,
                        'bulk_price_6': data['bulk'],
                        'discount_pct': data['disc'],
                        'url': data['url'],
                        'store': 'Supervin',
                        'store_url': 'https://www.supervin.dk',
                        'wine_type': guess_wine_type(data['name']),
                        'scraped_at': datetime.now().isoformat(),
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f'  Supervin fejl ({url}): {e}')
    return deals

def scrape_vildmedvin(page):
    deals = []
    try:
        page.goto('https://www.vildmedvin.dk/tilbud', wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(3000)
        try:
            page.click('button:has-text("Vaelg alle")', timeout=3000)
        except:
            pass
        for el in page.query_selector_all('.product-item'):
            try:
                name_el = el.query_selector('.product-name')
                prev_el = el.query_selector('.previous-price')
                disc_el = el.query_selector('.saving-price .price')
                link_el = el.query_selector('a.product-link, a')
                name = name_el.inner_text().strip() if name_el else ''
                single_price = parse_price(prev_el.inner_text() if prev_el else '')
                disc_pct = int(re.sub(r'[^\d]', '', disc_el.inner_text())) if disc_el else None
                href = link_el.get_attribute('href') if link_el else ''
                url = href if href.startswith('http') else 'https://www.vildmedvin.dk' + href
                bulk = round(single_price * (1 - disc_pct/100), 2) if (single_price and disc_pct) else None
                if not name or not single_price:
                    continue
                deals.append({
                    'name': name[:100], 'current_price': single_price,
                    'original_price': None, 'bulk_price_6': bulk,
                    'discount_pct': disc_pct,
                    'url': url, 'store': 'VildMedVin',
                    'store_url': 'https://www.vildmedvin.dk',
                    'wine_type': guess_wine_type(name),
                    'scraped_at': datetime.now().isoformat(),
                })
            except Exception:
                continue
    except Exception as e:
        print(f'  VildMedVin fejl: {e}')
    return deals

def main():
    print(f'Starter scraping - {datetime.now().strftime("%H:%M")}')
    all_deals = []
    stats = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            locale='da-DK',
        )
        page = context.new_page()
        scrapers = [
            ('AndrupVin', scrape_andrupvin),
            ('JyskVin', scrape_jyskvin),
            ('Supervin', scrape_supervin),
            ('VildMedVin', scrape_vildmedvin),
        ]
        for name, fn in scrapers:
            print(f'  Scraper {name}...')
            deals = fn(page)
            all_deals.extend(deals)
            stats.append({'store': name, 'deals_found': len(deals)})
            print(f'  -> {len(deals)} tilbud fra {name}')
        browser.close()
    all_deals.sort(key=lambda d: (-(d.get('discount_pct') or 0), d.get('current_price', 9999)))
    output = {
        'last_updated': datetime.now().isoformat(),
        'total_deals': len(all_deals),
        'sites_scraped': len(scrapers),
        'scrape_stats': stats,
        'deals': all_deals,
    }
    with open('wine_deals.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'Gemt {len(all_deals)} tilbud til wine_deals.json')
    for s in stats:
        print(f'  {s["store"]}: {s["deals_found"]}')

if __name__ == '__main__':
    main()
