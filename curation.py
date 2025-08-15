#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ExhaustiveAI - Curation Pipeline
(Business-Impact + Paywall-Aware + Free Mirror + Admin Overrides + Emergency Shutoff)
"""

import os, re, json, time, random, hashlib, asyncio, pickle
from datetime import datetime, timezone
import concurrent.futures

import jinja2
import feedparser
import arxiv
import tldextract
import requests
from bs4 import BeautifulSoup

# Gemini (optional fail-open)
import google.generativeai as genai

# Robust HTTP sessions
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# ---------------------------
# Admin / data file locations
# ---------------------------
OVERRIDES_FILE       = 'overrides.json'         # {"overrides": { "<url>": {"headline": "...", "url": "...", "image_url": "..."} } }
BANNED_DOMAINS_FILE  = 'banned_domains.json'    # ["example", "domain"]
CUSTOM_FEEDS_FILE    = 'custom_feeds.json'      # ["https://site/feed.xml", ...]
CURATED_DATA_FILE    = 'curated_items.json'     # export for admin UI
ADMIN_CONFIG_FILE    = 'admin_config.json'      # {"disable_mirror": false, "disable_overrides": false, "disable_custom_feeds": false}

# ---------------------------
# Gemini setup (fail-open)
# ---------------------------
USE_GEMINI = True
try:
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        raise KeyError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=gemini_api_key)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"WARNING: {e} — running WITHOUT Gemini. Headlines will use original titles.")
    USE_GEMINI = False
    gemini_model = None

# Cap Gemini calls per run to avoid 429s (env-tunable)
GEMINI_MAX_CALLS_PER_RUN = int(os.getenv("GEMINI_MAX_CALLS_PER_RUN", "12"))

# ---------------------------
# HTTP session (headers + retries)
# ---------------------------
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Ac
