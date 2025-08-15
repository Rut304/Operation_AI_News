#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ExhaustiveAI - Curation Pipeline (Business-Impact Optimized, Paywall-Aware + Free Mirror)
- Parallel RSS fetching with caching
- Google Gemini headline rewrite + sensational score
- Business-impact scoring (brands, deals, execs, authority, freshness)
- Paywall handling: remove always-paywall sources; search Google News for free mirrors
- Footer rotation: daily Top 30 (free/accessible) AI business destinations
"""

import os
import re
import jinja2
import feedparser
import arxiv
import google.generativeai as genai
import time
from datetime import datetime, timezone
import random
import tldextract
from bs4 import BeautifulSoup
import concurrent.futures
import requests
import pickle
import asyncio
import hashlib

# --- CONFIGURATION ---

try:
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        raise KeyError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=gemini_api_key)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
except KeyError as e:
    print(f"ERROR: {e}")
    exit(1)

# Trimmed/optimized RSS feeds (business-heavy + free-friendly + brand queries)
RSS_FEEDS = [
    # Major tech/business with AI sections
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/group/ai-artificial-intelligence/index.xml",
    "https://www.wired.com/feed/category/business/artificial-intelligence/latest/rss",
    "https://www.fastcompany.com/section/artificial-intelligence/rss",
    "https://www.eweek.com/artificial-intelligence/feed/",
    "https://www.infoworld.com/artificial-intelligence/feed/",
    "https://www.enterpriseai.news/feed/",
    "https://aibusiness.com/rss.xml",

    # Corporate newsrooms (big brands announce here first)
    "https://blogs.nvidia.com/feed/",
    "https://about.fb.com/news/category/technology/ai/feed/",
    "https://about.google/press/rss/",
    "https://aws.amazon.com/blogs/aws/category/artificial-intelligence/feed/",
    "https://blogs.microsoft.com/feed/",
    "https://news.microsoft.com/source/topics/ai/feed/",
    "https://www.ibm.com/blogs/research/feed/",
    "https://www.salesforce.com/news/feed/",
    "https://blogs.oracle.com/rss",
    "https://www.apple.com/newsroom/rss-feed.rss",
    "https://www.adobe.com/blog/feed",

    # Deal flow
    "https://news.crunchbase.com/sections/ai/feed/",

    # Curated AI publications
    "https://dailyai.com/feed/",
    "https://www.marktechpost.com/feed/",
    "https://emerj.com/feed/",

    # Press wires (kept but down-weighted in scoring)
    "https://www.businesswire.com/rss/topic/Artificial+Intelligence",
    "https://www.prnewswire.com/rss/artificial-intelligence-news.rss",

    # Google News “intitle” company queries (7-day window surfaces free mirrors)
    "https://news.google.com/rss/search?q=intitle:Microsoft+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Google+AI+OR+Alphabet+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Amazon+AI+OR+AWS+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:NVIDIA+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:OpenAI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Apple+AI+OR+%22Apple+Intelligence%22+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Meta+AI+OR+Facebook+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:IBM+AI+OR+watsonx+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Salesforce+AI+OR+Einstein+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Oracle+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Adobe+AI+OR+Firefly+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Intel+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:AMD+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:Broadcom+AI+OR+AVGO+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=intitle:TSMC+AI+when:7d&hl=en-US&gl=US&ceid=US:en",
]

MAX_ARTICLES_PER_SOURCE = 2
MAX_TOTAL_ARTICLES = 25
MAX_TECHNICAL_ARTICLES = 3
CACHE_FILE = 'rss_cache.pkl'
CACHE_TTL = 1800  # 30 minutes

# Style options for random assignment
STYLE_CLASSES = ['style1', 'style2', 'style3', 'style4']

# Source mapping for friendly names (based on article URL host)
SOURCE_MAP = {
    # publications
    'theverge': 'The Verge',
    'techcrunch': 'TechCrunch',
    'wired': 'Wired',
    'fastcompany': 'Fast Company',
    'venturebeat': 'VentureBeat',
    'eweek': 'eWeek',
    'infoworld': 'InfoWorld',
    'enterpriseai': 'EnterpriseAI',
    'dailyai': 'DailyAI',
    'marktechpost': 'MarkTechPost',
    'emerj': 'Emerj',
    'crunchbase': 'Crunchbase News',

    # corporate newsrooms
    'nvidia': 'NVIDIA',
    'google': 'Google',
    'blogspot': 'Google AI',
    'amazon': 'Amazon/AWS',
    'microsoft': 'Microsoft',
    'ibm': 'IBM',
    'salesforce': 'Salesforce',
    'oracle': 'Oracle',
    'apple': 'Apple',
    'adobe': 'Adobe',
    'meta': 'Meta',

    # aggregators / search
    'news': 'Google News',

    # wires
    'businesswire': 'BusinessWire',
    'prnewswire': 'PR Newswire',
}

# Source authority weights (0..1)
AUTHORITY_WEIGHTS = {
    # high-quality tech/business pubs
    'TechCrunch': 0.86, 'VentureBeat': 0.84, 'The Verge': 0.82, 'Wired': 0.82,
    'Fast Company': 0.80, 'EnterpriseAI': 0.80, 'InfoWorld': 0.78, 'eWeek': 0.78,
    'Crunchbase News': 0.78, 'Google News': 0.80,

    # corporate first-party (strong for partnerships/deals)
    'NVIDIA': 0.90, 'Microsoft': 0.88, 'Google': 0.88, 'Amazon/AWS': 0.88,
    'IBM': 0.85, 'Salesforce': 0.84, 'Oracle': 0.83, 'Apple': 0.83, 'Adobe': 0.83, 'Meta': 0.82,

    # specialty AI pubs
    'DailyAI': 0.77, 'MarkTechPost': 0.75, 'Emerj': 0.78,

    # wires (down-weighted)
    'BusinessWire': 0.65, 'PR Newswire': 0.60
}

# --- Paywall policy ---
PAYWALL_ALWAYS = { 'wsj', 'bloomberg', 'ft', 'theinformation', 'economist' }  # drop
METERED_OK = { 'nytimes', 'washingtonpost', 'businessinsider', 'theatlantic', 'forbes' }  # allow

# AI relevance keywords
AI_KEYWORDS = [
    'ai ', 'artificial intelligence', 'machine learning', 'neural network', 'deep learning',
    'llm', 'generative ai', 'chatgpt', 'gpt', 'model', 'algorithm', 'robotics', 'computer vision',
    'natural language processing', 'nlp', 'reinforcement learning', 'ai hardware', 'ai software',
    'agi', 'autonomous', 'predictive analytics', 'genai', 'foundation model', 'inference',
    'gpu', 'accelerator', 'agents', 'agentic', 'rag'
]

# M&A / exec / breakthrough signals
MA_KEYWORDS = ['merger', 'acquisition', 'm&a', 'buyout', 'investment', 'funding round', 'venture capital', 'acquired', 'merged']
PEOPLE_KEYWORDS = ['hire', 'hires', 'leaves', 'joins', 'promoted', 'ceo', 'executive', 'cfo', 'cto', 'resigns', 'appointment']
BUSINESS_TERMS = [
    'acquisition','acquires','acquired','merger','m&a','deal','partnership','partner',
    'strategic','investment','funding','raises','series a','series b','valuation',
    'earnings','guidance','revenue','profit','loss','contract','agreement','licensing',
    'deploys','rollout','selects','standardizes on','ipo','spinoff','joint venture'
]
EXEC_TERMS = ['ceo','cfo','cio','cto','chief executive','board','chair','svp','evp','general manager']
BREAKTHROUGH_KEYWORDS = ['breakthrough', 'revolution', 'game-changing', 'transformative', 'new model', 'agi', 'hardware advance', 'software breakthrough', 'innovation', 'first-ever', 'unveils', 'launches']

# Fortune tiers
fortune_top_20 = [
    'Walmart','Amazon','Apple','UnitedHealth Group','Berkshire Hathaway','CVS Health','ExxonMobil',
    'Alphabet','McKesson Corporation','Cencora','Costco','JPMorgan Chase','Microsoft','Cardinal Health',
    'Chevron Corporation','Cigna','Ford Motor Company','Bank of America','General Motors','Elevance Health'
]
fortune_21_to_50 = [
    'Citigroup','Centene','The Home Depot','Marathon Petroleum','Kroger','Phillips 66','Fannie Mae',
    'Walgreens Boots Alliance','Valero Energy','Meta Platforms','Verizon Communications','AT&T','Comcast',
    'Wells Fargo','Goldman Sachs','Freddie Mac','Target Corporation','Humana',
