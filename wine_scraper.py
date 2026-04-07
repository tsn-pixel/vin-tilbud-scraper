#!/usr/bin/env python3
"""
Dansk Vin Tilbud Scraper – GitHub Actions version
Bruger Playwright (headless Chromium) til at scrape de største danske vinwebsites.
Kører dagligt via GitHub Actions og gemmer wine_deals.json.
"""

import json
import re
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

# ── Hjælpefunktioner ──────────────────────────────────────────────

def parse_price(txt):
    if not txt:
        return None
    m = re.search(r'([\d]+[,\.][\d]{1,2})', txt.replace('\xa0', ''))
    return float(m.group(1).replace(',', '.')) if m else None

def parse_quantity(txt):
    """Udtrækker antal flasker fra strenge som 'v/12 stk.', 'Ved 6 stk.', '6 fl. pr. stk.'"""
    if not txt:
        return None
    m = re.search(r'(\d+)\s*(?:stk|fl)', txt)
    return int(m.group(1)) if m else None

def guess_wine_type(name):
    n = name.lower()
    if any(w in n for w in ['champagne', 'crémant', 'cava', 'prosecco', 'mousserende', 'sekt', 'sparkling']):
        return 'mousserende'
    if any(w in n for w in ['rosé', 'rosé', 'rosvin', 'rosé']):
        return 'rosé'
    if any(w in n for w in ['chardonnay', 'riesling', 'sauvignon blanc', 'pinot gris', 'hvidvin',
                             'grüner', 'verdejo', 'blanc', 'chenin', 'viognier', 'albariño']):
