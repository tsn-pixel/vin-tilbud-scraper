#!/usr/bin/env python3
"""
Dansk Vin Tilbud Scraper – GitHub Actions version
Bruger Playwright (headless Chromium) til at scrape de største danske vinwebsites.
Koerer dagligt via GitHub Actions og gemmer wine_deals.json.
"""

import json
import re
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── Hjaelpefunktioner ──────────────────────────────────────────────

def parse_price(txt):
    if not txt:
        return None
    m = re.search(r'([\d]+[,\.][\d]{1,2})', txt.replace('\xa0', ''))
    return float(m.group(1).replace(',', '.')) if m else None

def parse_quantity(txt):
    """Udtraekker antal flasker fra strenge som 'v/12 stk.', 'Ved 6 stk.', '6 fl. pr. stk.'"""
    if not txt:
        return None
    m = re.search(r'(\d+)\s*(?:stk|fl)', txt)
    return int(m.group(1)) if m else None

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

def title_case_da(s):
    """Konverterer VERSALER til Title Case"""
    if not s:
        return s
    return s.title() if s.isupper() else s

# ── Felt-mapping hjaelper ──────────────────────────────────────────

def _map_field(deal, label, value):
    """Mapper et label/value par til deal-felter."""
    if not label or not value:
        return
    l = label.lower()
    if 'land' in l:
        if not deal.get('country'):
            deal['country'] = value
    elif 'omrade' in l or 'omrde' in l or 'region' in l:
        if not deal.get('region'):
            deal['region'] = value
    elif 'producent' in l or 'producer' in l:
        if not deal.get('producer'):
            deal['producer'] = value
    elif 'argang' in l or 'rgang' in l or 'vintage' in l:
        if not deal.get('vintage'):
            deal['vintage'] = value
    elif 'drue' in l or 'grape' in l:
        if not deal.get('grapes'):
            deal['grapes'] = value
    elif 'alkohol' in l or 'alcohol' in l:
        if not deal.get('alcohol'):
            deal['alcohol'] = value
    elif any(x in l for x in ['storrelse', 'rrelse', 'indhold', 'flaskestr', 'volumen', 'cl', 'liter']):
        if not deal.get('bottle_size'):
            deal['bottle_size'] = value

# ── Site-specifikke scrapere ──────────────────────────────────────

def scrape_andrupvin(page):
    """AndrupVin – Magento, Spring Sale med rigtige rabatter"""
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
                    deal = {
                        'name': name[:100], 'current_price': cur,
                        'original_price': old if old != cur else None,
                        'discount_pct': computed,
                        'min_quantity': None,
                        'url': url_prod, 'store': 'AndrupVin',
                        'store_url': 'https://www.andrupvin.dk',
                        'wine_type': guess_wine_type(name),
                        'country': None, 'region': None, 'producer': None,
                        'vintage': None, 'grapes': None, 'alcohol': None,
                        'bottle_size': None,
                        'scraped_at': datetime.now().isoformat(),
                    }
                    if url_prod and url_prod.startswith('http'):
                        try:
                            page.goto(url_prod, wait_until='domcontentloaded', timeout=20000)
                            page.wait_for_timeout(1500)
                            info_section = page.query_selector('.info-section')
                            if info_section:
                                children = info_section.query_selector_all('.flex.items-center.gap-2, .flex')
                                for child in children:
                                    texts = [t.strip() for t in child.inner_text().split('\n') if t.strip()]
                                    if len(texts) >= 2:
                                        _map_field(deal, texts[0], texts[1])
                            body_text = page.inner_text('body')
                            qty_match = re.search(r'kassevis\s*[aa]\s*(\d+)\s*stk', body_text, re.IGNORECASE)
                            if qty_match:
                                deal['min_quantity'] = int(qty_match.group(1))
                            else:
                                qty_match2 = re.search(r'v/\s*(\d+)\s*stk', body_text, re.IGNORECASE)
                                if qty_match2:
                                    deal['min_quantity'] = int(qty_match2.group(1))
                        except Exception as e:
                            print(f'    AndrupVin produktside fejl ({url_prod}): {e}')
                    deals.append(deal)
                except Exception:
                    continue
        except Exception as e:
            print(f'  AndrupVin fejl ({url}): {e}')
    return deals


def scrape_jyskvin(page):
    """JyskVin – Drupal.
    current_price = stykpris ved bulk-kob (tilbudspris).
    original_price = 1-flaske-prisen (normalpris).
    """
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
                name_el = el.query_selector('.entity-teaser__heading, [class*="title"], h2, h3')
                name = name_el.inner_text().strip() if name_el else ''

                subhead_el = el.query_selector('.entity-teaser__subheading, [class*="subhead"]')
                subhead = subhead_el.inner_text().strip() if subhead_el else ''
                producer_raw = ''
                country_raw = ''
                if ',' in subhead:
                    parts = subhead.rsplit(',', 1)
                    producer_raw = title_case_da(parts[0].strip())
                    country_raw = title_case_da(parts[1].strip())
                elif subhead:
                    country_raw = title_case_da(subhead)

                price_highlighted = el.query_selector('.entity-teaser__price--highlighted')
                bulk_text = price_highlighted.inner_text() if price_highlighted else ''
                qty_el = el.query_selector('.entity-teaser__price--highlighted .entity-teaser__price__small')
                qty_text = qty_el.inner_text() if qty_el else bulk_text
                min_qty = parse_quantity(qty_text)
                cur = parse_price(bulk_text)

                old = None
                for price_el2 in el.query_selector_all('.entity-teaser__price'):
                    if 'highlighted' not in (price_el2.get_attribute('class') or ''):
                        txt = price_el2.inner_text()
                        v = parse_price(txt)
                        if v and v > 0:
                            if '1 stk' in txt or 'v/1' in txt or (min_qty and min_qty > 1):
                                old = v
                            elif old is None:
                                old = v

                href = el.get_attribute('href') or 'https://www.jyskvin.dk/vintilbud'
                full_url = href if href.startswith('http') else 'https://www.jyskvin.dk' + href

                if not name or not cur:
                    continue
                disc = round((1 - cur/old)*100) if (old and old > cur) else None

                deal = {
                    'name': name[:100], 'current_price': cur,
                    'original_price': old or None, 'discount_pct': disc,
                    'min_quantity': min_qty,
                    'url': full_url,
                    'store': 'JyskVin', 'store_url': 'https://www.jyskvin.dk',
                    'wine_type': guess_wine_type(name),
                    'country': country_raw or None,
                    'region': None,
                    'producer': producer_raw or None,
                    'vintage': None, 'grapes': None, 'alcohol': None,
                    'bottle_size': None,
                    'scraped_at': datetime.now().isoformat(),
                }

                try:
                    page.goto(full_url, wait_until='domcontentloaded', timeout=20000)
                    page.wait_for_timeout(1500)
                    for row in page.query_selector_all('.product__facts__table tr'):
                        cells = row.query_selector_all('td')
                        if len(cells) >= 2:
                            _map_field(deal, cells[0].inner_text().strip(), cells[1].inner_text().strip())
                except Exception as e:
                    print(f'    JyskVin produktside fejl ({full_url}): {e}')

                deals.append(deal)
            except Exception:
                continue
    except Exception as e:
        print(f'  JyskVin fejl: {e}')
    return deals


def scrape_supervin(page):
    """Supervin – Angular SPA"""
    deals = []
    urls = [
        'https://www.supervin.dk/tilbud/top10',
        'https://www.supervin.dk/tilbud/hvidvin',
        'https://www.supervin.dk/tilbud/fransk-rodvin',
        'https://www.supervin.dk/tilbud/italiensk-rodvin',
        'https://www.supervin.dk/tilbud/spansk-rodvin',
        'https://www.supervin.dk/tilbud/rose-vin',
        'https://www.supervin.dk/udlober-snart',
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
                    data = el.evaluate("""el => {
                        const w = el.closest('.item') || el.parentElement?.parentElement;
                        const name = w?.querySelector('h2,h3,h4')?.innerText?.trim() || '';
                        const baseEl = w?.querySelector('.price.base-price');
                        const basePrice = parseFloat((baseEl?.getAttribute('data-price') || '').replace(',', '.')) || null;
                        const badge = w?.querySelector('[class*=badge],[class*=discount]')?.innerText?.trim() || '';
                        const m = badge.match(/([\d,.]+)\s*DKK/);
                        const bulk = m ? parseFloat(m[1].replace(',', '.')) : null;
                        const disc = (bulk && basePrice && bulk < basePrice) ? Math.round((1 - bulk/basePrice)*100) : null;
                        const link = w?.querySelector('a[href]');
                        const url = link?.href || '';
                        const flagImg = w?.querySelector('img[src*="country_icon"]');
                        const country = flagImg?.getAttribute('alt') || '';
                        let minQty = null;
                        const labels = w?.querySelectorAll('.label') || [];
                        for (const lbl of labels) {
                            const t = lbl.innerText || '';
                            const qm = t.match(/(\d+)\s*fl/);
                            if (qm) { minQty = parseInt(qm[1]); }
                        }
                        return { name, basePrice, bulk, disc, url, country, minQty };
                    }""")
                    if not data['name'] or not data['basePrice'] or data['name'] in seen:
                        continue
                    seen.add(data['name'])

                    deal = {
                        'name': data['name'][:100],
                        'current_price': data['basePrice'],
                        'original_price': None,
                        'bulk_price_6': data['bulk'],
                        'discount_pct': data['disc'],
                        'min_quantity': data.get('minQty'),
                        'url': data['url'],
                        'store': 'Supervin',
                        'store_url': 'https://www.supervin.dk',
                        'wine_type': guess_wine_type(data['name']),
                        'country': data.get('country') or None,
                        'region': None, 'producer': None,
                        'vintage': None, 'grapes': None, 'alcohol': None,
                        'bottle_size': None,
                        'scraped_at': datetime.now().isoformat(),
                    }

                    prod_url = data['url']
                    if prod_url and prod_url.startswith('http'):
                        try:
                            page.goto(prod_url, wait_until='domcontentloaded', timeout=20000)
                            page.wait_for_timeout(1500)

                            all_data = page.evaluate("""() => {
                                const result = {};
                                document.querySelectorAll('.product-data-value').forEach(el => {
                                    const prev = el.previousElementSibling;
                                    if (prev) {
                                        const label = (prev.innerText || prev.textContent || '').trim().toLowerCase();
                                        const value = (el.innerText || el.textContent || '').trim();
                                        result[label] = value;
                                    }
                                });
                                return result;
                            }""")
                            for label, value in all_data.items():
                                _map_field(deal, label, value)

                            fra_data = page.evaluate("""() => {
                                const els = document.querySelectorAll('*');
                                for (const el of els) {
                                    const t = (el.innerText || '').trim();
                                    if (t === 'Vinen kommer fra' || t === 'Oprindelse') {
                                        const next = el.parentElement?.nextElementSibling;
                                        if (next) return (next.innerText || '').trim();
                                    }
                                }
                                return '';
                            }""")
                            if fra_data:
                                lines = [l.strip() for l in fra_data.split('\n') if l.strip()]
                                if lines and not deal['country']:
                                    deal['country'] = lines[0]
                                if len(lines) > 1 and not deal['region']:
                                    deal['region'] = ', '.join(lines[1:])

                        except Exception as e:
                            print(f'    Supervin produktside fejl ({prod_url}): {e}')

                    deals.append(deal)
                except Exception:
                    continue
        except Exception as e:
            print(f'  Supervin fejl ({url}): {e}')
    return deals


def scrape_vildmedvin(page):
    """VildMedVin – Vue.js, maengerabat"""
    deals = []
    try:
        page.goto('https://www.vildmedvin.dk/tilbud/vin-tilbud', wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(3000)
        try:
            page.click('button:has-text("Vaelg alle")', timeout=3000)
        except:
            pass
        for el in page.query_selector_all('.product-item'):
            try:
                name_el = el.query_selector('.product-name')
                link_el = el.query_selector('a.product-link, a')
                name = name_el.inner_text().strip() if name_el else ''
                href = link_el.get_attribute('href') if link_el else ''
                prod_url = href if href.startswith('http') else 'https://www.vildmedvin.dk' + href

                item_text = el.inner_text()
                price_1_match = re.search(r'[Vv]ed\s+1\s+stk[.\s]+(\d+[\.,]\d+)\s*kr', item_text)
                price_bulk_match = re.search(r'[Vv]ed\s+(\d+)\s+stk[.\s]+(\d+[\.,]\d+)\s*kr', item_text)

                single_price = parse_price(price_1_match.group(1)) if price_1_match else None
                bulk_qty = int(price_bulk_match.group(1)) if price_bulk_match else None
                bulk_price = parse_price(price_bulk_match.group(2)) if price_bulk_match else None

                if not single_price:
                    prev_el = el.query_selector('.previous-price')
                    single_price = parse_price(prev_el.inner_text() if prev_el else '')

                if not bulk_qty:
                    offer_el = el.query_selector('.offer-inner, .offer')
                    if offer_el:
                        bulk_qty = parse_quantity(offer_el.inner_text())

                if not bulk_price and single_price and bulk_qty:
                    disc_el = el.query_selector('.saving-price .price')
                    disc_pct_raw = int(re.sub(r'[^\d]', '', disc_el.inner_text())) if disc_el else None
                    if disc_pct_raw:
                        bulk_price = round(single_price * (1 - disc_pct_raw/100), 2)

                disc = round((1 - bulk_price/single_price)*100) if (bulk_price and single_price and single_price > bulk_price) else None

                if not name or not single_price:
                    continue

                deal = {
                    'name': name[:100],
                    'current_price': bulk_price if bulk_price else single_price,
                    'original_price': single_price if bulk_price else None,
                    'bulk_price_6': bulk_price,
                    'discount_pct': disc,
                    'min_quantity': bulk_qty,
                    'url': prod_url, 'store': 'VildMedVin',
                    'store_url': 'https://www.vildmedvin.dk',
                    'wine_type': guess_wine_type(name),
                    'country': None, 'region': None, 'producer': None,
                    'vintage': None, 'grapes': None, 'alcohol': None,
                    'bottle_size': None,
                    'scraped_at': datetime.now().isoformat(),
                }

                if prod_url and prod_url.startswith('http'):
                    try:
                        page.goto(prod_url, wait_until='domcontentloaded', timeout=20000)
                        page.wait_for_timeout(2000)
                        facts = page.evaluate("""() => {
                            const result = {};
                            document.querySelectorAll('.name').forEach(el => {
                                const label = (el.innerText || '').trim().replace(/:$/, '').toLowerCase();
                                const parent = el.parentElement;
                                if (parent) {
                                    const next = parent.nextElementSibling;
                                    if (next) {
                                        const value = (next.innerText || '').trim();
                                        result[label] = value;
                                    }
                                }
                            });
                            return result;
                        }""")
                        for label, value in facts.items():
                            _map_field(deal, label, value)
                    except Exception as e:
                        print(f'    VildMedVin produktside fejl ({prod_url}): {e}')

                deals.append(deal)
            except Exception:
                continue
    except Exception as e:
        print(f'  VildMedVin fejl: {e}')
    return deals


# ── Hovedfunktion ─────────────────────────────────────────────────

def main():
    print(f'Starter scraping – {datetime.now().strftime("%H:%M")}')
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

    print(f'\n Gemt {len(all_deals)} tilbud til wine_deals.json')
    for s in stats:
        print(f'  {s["store"]}: {s["deals_found"]}')


if __name__ == '__main__':
    main()
