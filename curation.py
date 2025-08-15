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
    'Wells Fargo','Goldman Sachs','Freddie Mac','Target Corporation','Humana','State Farm','Tesla',
    'Morgan Stanley','Johnson & Johnson','Archer Daniels Midland','PepsiCo','United Parcel Service',
    'FedEx','The Walt Disney Company','Dell Technologies',"Lowe's",'Procter & Gamble'
]
fortune_51_to_100 = [
    'Energy Transfer Partners','Boeing','Albertsons','Sysco','RTX Corporation','General Electric',
    'Lockheed Martin','American Express','Caterpillar','MetLife','HCA Healthcare','Progressive Corporation',
    'IBM','John Deere','Nvidia','StoneX Group','Merck & Co.','ConocoPhillips','Pfizer','Delta Air Lines',
    'TD Synnex','Publix','Allstate','Cisco','Nationwide Mutual Insurance Company','Charter Communications',
    'AbbVie','New York Life Insurance Company','Intel','TJX','Prudential Financial','HP','United Airlines',
    'Performance Food Group','Tyson Foods','American Airlines','Liberty Mutual','Nike','Oracle Corporation',
    'Enterprise Products','Capital One Financial','Plains All American Pipeline','World Kinect Corporation',
    'AIG','Coca-Cola','TIAA','CHS','Bristol-Myers Squibb','Dow Chemical Company','Best Buy'
]

# Popular AI companies (expanded)
popular_ai_companies = [
    'Microsoft','NVIDIA','Google','Alphabet','Amazon','Meta','IBM','OpenAI','Salesforce',
    'Oracle','SAP','Baidu','Alibaba','Tesla','Apple','Adobe','Intel','AMD','Qualcomm',
    'Anthropic','xAI','DeepMind','Hugging Face','Stability AI','Cohere','Mistral AI','Databricks',
    'ServiceNow','Snowflake','Palantir','Cisco'
]

# --- HELPERS ---

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            cache = pickle.load(f)
        if time.time() - cache.get('timestamp', 0) < CACHE_TTL:
            return cache.get('articles', [])
    return None

def save_cache(articles):
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump({'timestamp': time.time(), 'articles': articles}, f)

def fetch_feed(feed_url):
    """Fetch a single feed with timeout."""
    try:
        response = requests.get(feed_url, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Error fetching {feed_url}: {e}")
        feed = {'entries': []}
    return feed, feed_url

def domain_of(url: str) -> str:
    ex = tldextract.extract(url)
    return ex.domain.lower()

def publisher_from_url(url, fallback_feed_url):
    """Best-effort publisher name from entry URL; fallback to feed URL host."""
    try:
        host = domain_of(url)
        return SOURCE_MAP.get(host, host.capitalize())
    except Exception:
        ex = tldextract.extract(fallback_feed_url)
        host = ex.domain.lower()
        return SOURCE_MAP.get(host, ex.domain.capitalize())

def is_always_paywalled(url: str) -> bool:
    try:
        d = domain_of(url)
        return d in PAYWALL_ALWAYS
    except Exception:
        return False

def is_metered_allowed(url: str) -> bool:
    try:
        d = domain_of(url)
        return (d in METERED_OK) or (d not in PAYWALL_ALWAYS)
    except Exception:
        return True

STOPWORDS = {
    'the','and','for','with','from','that','this','a','an','on','in','of','to','as','by','at','vs',
    'amid','after','before','over','into','about','its','their','our','your','his','her'
}

def normalize_title(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r'\b(update|exclusive|opinion|analysis|breaking)\b', '', s)
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s.strip()

def build_gn_query_from_title(title: str) -> str:
    # pull significant tokens from title for Google News RSS search
    tokens = re.findall(r'\b[A-Za-z0-9][A-Za-z0-9\-]{2,}\b', title or '')
    tokens = [t for t in tokens if t.lower() not in STOPWORDS]
    tokens = tokens[:6]  # cap tokens
    if 'AI' not in [t.upper() for t in tokens]:
        tokens.append('AI')
    # build q with intitle: to bias toward same/similar headline
    q = ' '.join(f'intitle:{t}' for t in tokens) + ' when:14d'
    return q

def google_news_search_articles(q: str, max_results: int = 8):
    """Search Google News RSS for q and return list of article dicts (paywall filtered later)."""
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(q)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as e:
        print(f"GN search error for '{q}': {e}")
        return []

    results = []
    for entry in feed.get('entries', [])[:max_results]:
        link = entry.get('link')
        title = entry.get('title', '')
        if not link or not title:
            continue

        source_name = publisher_from_url(link, url)
        source_authority = AUTHORITY_WEIGHTS.get(source_name, 0.75)

        # Published date
        if 'published_parsed' in entry and entry.published_parsed:
            dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
        elif 'updated_parsed' in entry and entry.updated_parsed:
            dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed))
        else:
            dt = datetime.min
        published = dt.replace(tzinfo=timezone.utc)

        # Summary & image (GN often lacks media; keep None)
        summary = entry.get('summary', 'No summary available.')

        results.append({
            'title': title,
            'url': link,
            'source': source_name,
            'source_authority': source_authority,
            'image_url': None,
            'summary': summary,
            'published': published
        })
    return results

def freshness_multiplier(published_at: datetime, half_life_hours=48.0) -> float:
    """0..1 where 1 is fresh; 48h half-life by default."""
    try:
        delta_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600.0
        delta_hours = max(delta_hours, 0.0)
        return 0.5 ** (delta_hours / half_life_hours)
    except Exception:
        return 0.8

# --- FETCHERS ---

def get_articles_from_rss():
    """Fetches RSS feeds in parallel, with caching."""
    start_time = time.time()
    cached_articles = load_cache()
    if cached_articles:
        print("Using cached RSS articles")
        return cached_articles

    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_feed, url): url for url in RSS_FEEDS}
        for future in concurrent.futures.as_completed(future_to_url):
            feed, feed_url = future.result()
            for entry in feed.get('entries', [])[:MAX_ARTICLES_PER_SOURCE]:
                if not (entry.get('title') and entry.get('link')):
                    continue

                # Determine source based on the article URL (not the feed host)
                source_name = publisher_from_url(entry.link, feed_url)
                source_authority = AUTHORITY_WEIGHTS.get(source_name, 0.75)

                article = {
                    'title': entry.title,
                    'url': entry.link,
                    'source': source_name,
                    'source_authority': source_authority
                }

                # Extract image URL if available
                image_url = None
                if 'media_content' in entry and entry.media_content:
                    image_url = entry.media_content[0].get('url')
                elif 'media_thumbnail' in entry and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get('url')
                elif 'enclosures' in entry and entry.enclosures:
                    for enc in entry.enclosures:
                        if 'image' in enc.get('type', ''):
                            image_url = enc.get('href')
                            break
                if not image_url and 'summary' in entry:
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    img = soup.find('img')
                    if img and img.get('src'):
                        image_url = img['src']
                article['image_url'] = image_url

                # Summary
                article['summary'] = entry.get('summary', "No summary available.")

                # Published date
                if 'published_parsed' in entry and entry.published_parsed:
                    dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                elif 'updated_parsed' in entry and entry.updated_parsed:
                    dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed))
                else:
                    dt = datetime.min
                article['published'] = dt.replace(tzinfo=timezone.utc)

                articles.append(article)

    save_cache(articles)
    print(f"RSS fetching took {time.time() - start_time:.2f} seconds")
    return articles

def get_articles_from_arxiv():
    """Fetches recent research papers from arXiv's Computer Science AI category."""
    articles = []
    try:
        search = arxiv.Search(
            query="cat:cs.AI",
            max_results=MAX_ARTICLES_PER_SOURCE,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        client = arxiv.Client()
        for result in client.results(search):
            articles.append({
                'title': result.title,
                'url': result.entry_id,
                'published': result.published,
                'image_url': None,
                'summary': result.summary if result.summary else "No summary available.",
                'source': 'arXiv',
                'source_authority': AUTHORITY_WEIGHTS.get('arXiv', 0.72)
            })
    except Exception as e:
        print(f"Error fetching from arXiv: {e}")
    return articles

# --- FILTERS & SCORING ---

def is_ai_related(title, summary):
    """Check if the article is AI-related using keywords."""
    text = (title + " " + summary).lower()
    return any(kw in text for kw in AI_KEYWORDS)

async def async_get_headline_and_score(title, summary):
    """Async wrapper for Gemini API call."""
    fallback_headline = title.strip()
    prompt = f"""
    Analyze the following article title and summary.
    First, on a scale of 1 to 20, rate how provocative, sensational, and AI-specific it is. Higher scores for stories evoking strong emotions, controversy, breakthroughs, or business impacts in AI.
    Second, rewrite the title as an ultra-sensational, viral, clickbait-style headline that's irresistible—evoke curiosity, fear, excitement, FOMO, or shock while staying completely factual and not lying. Use sentence case (capitalize first letter and proper names). If a major company or business is mentioned in the title or summary, include it prominently at the beginning. Keep it punchy and under 15 words.
    Third, if this seems technical/academic or a breakthrough in AI HW/SW, rate its importance/impact on a scale of 1-10 (higher for game-changers); otherwise, return 0.

    Respond with the score, the headline, and tech_importance separated by pipe characters (|). For example: 18|Microsoft unleashes AI revolution that could change everything!|8

    Article Title: "{title}"
    Article Summary: "{summary[:500]}"
    """
    try:
        response = await gemini_model.generate_content_async(prompt)
        parts = response.text.strip().split('|', 3)
        if len(parts) >= 3:
            score = int(parts[0].strip())
            headline = parts[1].strip().replace('*', '')
            tech_importance = int(parts[2].strip())
            return headline, score, tech_importance
        else:
            return fallback_headline, 5, 0
    except Exception as e:
        print(f"Error processing title '{title}': {e}")
        await asyncio.sleep(2)
        return fallback_headline, 5, 0

def get_related_image_url(headline):
    """Generate or fetch a related image URL based on the headline (placeholder logic)."""
    keywords = headline.lower().split()
    if any(kw in ['ai', 'artificial', 'intelligence', 'machine', 'learning'] for kw in keywords):
        return "https://source.unsplash.com/600x300/?ai,technology"
    return "https://via.placeholder.com/600x300?text=AI+Headline+Image"

def get_boost(title, summary, source):
    """Calculate business-impact boost based on companies, M&A, exec signals, breakthroughs, and source type."""
    text = (title + " " + summary).lower()
    boost = 0

    # Popular AI companies
    for company in popular_ai_companies:
        if company.lower() in text:
            boost += 8  # per hit

    # Fortune tiers
    for company in fortune_top_20:
        if company.lower() in text:
            boost += 22
    for company in fortune_21_to_50:
        if company.lower() in text:
            boost += 14
    for company in fortune_51_to_100:
        if company.lower() in text:
            boost += 8

    # Business intent & exec signals
    if any(kw in text for kw in BUSINESS_TERMS):
        boost += 18
    if any(kw in text for kw in EXEC_TERMS):
        boost += 10

    # M&A priority (stacks)
    if any(kw in text for kw in ['merger','acquisition','m&a','buyout']):
        boost += 10

    # Key people
    if any(person in text for person in KEY_AI_PEOPLE):
        boost += 10

    # Breakthrough/excitement
    if any(kw in text for kw in BREAKTHROUGH_KEYWORDS):
        boost += 14

    # Source tuning
    if source in ['BusinessWire', 'PR Newswire']:
        boost -= 8
    if source in ['NVIDIA','Microsoft','Google','Amazon/AWS','IBM','Salesforce','Oracle','Apple','Adobe','Meta']:
        boost += 6

    # Technical sources small nudge
    if source in ['arXiv', 'MIT News', "O'Reilly"]:
        boost += 3

    return min(max(boost, 0), 100)

def freshness_multiplier_scored(published_at: datetime, half_life_hours=48.0) -> float:
    return freshness_multiplier(published_at, half_life_hours)

# --- MIRROR SELECTION HELPERS ---

def choose_best_candidate(candidates):
    """Rank candidates: non-paywall (metered ok) -> higher authority -> newer."""
    # Drop always-paywall
    pool = [c for c in candidates if not is_always_paywalled(c.get('url',''))]
    if not pool:
        return None
    # Prefer non-Google-News links if available
    non_gn = [c for c in pool if domain_of(c['url']) != 'news']
    if non_gn:
        pool = non_gn
    def rank_key(c):
        paywall_penalty = 0 if is_metered_allowed(c['url']) else -1
        auth = c.get('source_authority', 0.75)
        pub = c.get('published', datetime.min.replace(tzinfo=timezone.utc))
        return (paywall_penalty, auth, pub)
    pool.sort(key=rank_key, reverse=True)
    return pool[0]

def find_free_mirror_by_title(title: str):
    """Try Google News RSS for a free/accessible mirror of the given title."""
    if not title:
        return None
    q = build_gn_query_from_title(title)
    gn_hits = google_news_search_articles(q, max_results=10)
    best = choose_best_candidate(gn_hits)
    return best

# --- MAIN EXECUTION ---

if __name__ == "__main__":
    overall_start = time.time()
    print("Starting content generation for Exhaustive AI...")

    # Fetch articles
    fetch_start = time.time()
    all_articles = get_articles_from_rss() + get_articles_from_arxiv()
    print(f"Article fetching took {time.time() - fetch_start:.2f} seconds")

    # Group by normalized title
    groups = {}
    for a in all_articles:
        title = a.get('title', '')
        norm = normalize_title(title)
        if not norm:
            norm = domain_of(a.get('url','')) + normalize_title(title)
        groups.setdefault(norm, []).append(a)

    deduped = []
    for norm, items in groups.items():
        # 1) Try to choose best non-paywalled candidate from what we already fetched
        best = choose_best_candidate(items)

        # 2) If none (all paywalled or only bad links), try to find a free mirror via Google News
        if not best:
            # use the longest title among the group as the representative
            rep_title = max((it.get('title','') for it in items), key=len, default='')
            mirror = find_free_mirror_by_title(rep_title)
            if mirror:
                print(f"Free mirror found for '{rep_title}': {mirror.get('url')}")
                best = mirror

        if best:
            deduped.append(best)

    # Filter AI-related and double-check paywall drop
    filtered = []
    for a in deduped:
        if not a.get('url'):
            continue
        if is_always_paywalled(a['url']):
            continue
        if is_ai_related(a.get('title',''), a.get('summary','')):
            filtered.append(a)
        else:
            print(f"Discarded non-AI article: {a.get('title','(no title)')}")

    # Technical gating
    technical_sources = ['arXiv', 'MIT News', "O'Reilly"]
    technical_articles = [a for a in filtered if a.get('source') in technical_sources]
    non_technical_articles = [a for a in filtered if a.get('source') not in technical_sources]

    technical_articles.sort(key=lambda x: x['published'], reverse=True)
    technical_articles = technical_articles[:MAX_TECHNICAL_ARTICLES]

    curated = non_technical_articles + technical_articles
    curated.sort(key=lambda x: x['published'], reverse=True)
    articles_to_process = curated[:MAX_TOTAL_ARTICLES]
    print(f"Selected {len(articles_to_process)} articles after paywall filter, mirror search, and dedupe.")

    # --- Gemini headline pass ---
    process_start = time.time()

    async def process_articles_async():
        tasks = [async_get_headline_and_score(a['title'], a.get('summary', '')) for a in articles_to_process]
        return await asyncio.gather(*tasks)

    try:
        headline_results = asyncio.run(process_articles_async())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        headline_results = loop.run_until_complete(process_articles_async())

    processed_articles = []
    for article, (headline, sens_score, tech_importance) in zip(articles_to_process, headline_results):
        pub_date = article.get('published') or datetime.now(timezone.utc)
        if pub_date == datetime.min.replace(tzinfo=timezone.utc):
            pub_date = datetime.now(timezone.utc)

        related_image_url = get_related_image_url(headline)
        style = random.choice(STYLE_CLASSES)
        boost = get_boost(article.get('title',''), article.get('summary',''), article.get('source',''))

        # Authority & freshness multipliers
        auth = article.get('source_authority', 0.75)
        fresh = freshness_multiplier_scored(pub_date)
        base = sens_score + boost + tech_importance
        authority_mult = 0.75 + 0.5 * max(0.6, min(1.0, auth))   # ~1.05..1.25x
        fresh_mult = 0.6 + 0.8 * fresh                           # ~0.6..1.4x

        final_score = round(base * authority_mult * fresh_mult, 4)

        processed_articles.append({
            'headline': headline,
            'url': article['url'],
            'score': final_score,
            'image_url': article.get('image_url'),
            'related_image_url': related_image_url,
            'summary': article.get('summary', "No summary available."),
            'source': article.get('source', 'Unknown Source'),
            'published': pub_date.isoformat(),
            'style': style
        })
        print(f"  -> Sens:{sens_score} Boost:{boost} Tech:{tech_importance} Auth:{auth} "
              f"Fresh:{fresh:.3f} Final:{final_score} Source:{article.get('source','?')} Title:{headline}")

    print(f"Article processing (API calls) took {time.time() - process_start:.2f} seconds")

    # Rank by final score
    processed_articles.sort(key=lambda x: x['score'], reverse=True)

    # Main + columns
    main_headline = processed_articles[0] if processed_articles else None
    other_headlines = processed_articles[1:]
    col_size = (len(other_headlines) + 2) // 3
    column1 = other_headlines[0:col_size]
    column2 = other_headlines[col_size:col_size*2]
    column3 = other_headlines[col_size*2:]

    # ---- Footer rotation (Top 30 free/accessible AI business destinations) ----
    CURATED_SITES_POOL = [
        ("Reuters – AI", "https://www.reuters.com/technology/artificial-intelligence/", True),
        ("Axios – AI", "https://www.axios.com/technology/automation-and-ai", True),
        ("CNBC – Tech", "https://www.cnbc.com/technology/", True),
        ("Techmeme", "https://techmeme.com/", True),
        ("VentureBeat – AI", "https://venturebeat.com/category/ai/", True),
        ("TechCrunch – AI", "https://techcrunch.com/category/artificial-intelligence/", True),
        ("The Verge – AI", "https://www.theverge.com/ai-artificial-intelligence", True),
        ("ZDNet – AI", "https://www.zdnet.com/topic/artificial-intelligence/", True),
        ("The Register – AI", "https://www.theregister.com/Tag/AI/", True),
        ("InfoWorld – AI", "https://www.infoworld.com/artificial-intelligence/", True),
        ("eWeek – AI", "https://www.eweek.com/artificial-intelligence/", True),
        ("Engadget – AI", "https://www.engadget.com/tag/ai/", True),
        ("Tom’s Hardware – AI", "https://www.tomshardware.com/t/ai/", True),
        ("SiliconANGLE – AI", "https://siliconangle.com/tag/ai/", True),
        ("The Next Platform – AI/HPC", "https://www.nextplatform.com/category/machine-learning/", True),
        ("DatacenterDynamics – AI", "https://www.datacenterdynamics.com/en/ai/", True),
        ("HPCwire – AI", "https://www.hpcwire.com/tag/ai/", True),
        ("ServeTheHome – AI", "https://www.servethehome.com/tag/ai/", True),
        ("AI News (industry)", "https://www.artificialintelligence-news.com/", True),
        ("AI Business", "https://aibusiness.com/", True),
        ("DailyAI", "https://dailyai.com/", True),
        ("MarkTechPost", "https://www.marktechpost.com/", True),
        ("The Decoder", "https://the-decoder.com/", True),
        ("Unite.AI", "https://www.unite.ai/", True),
        ("OpenAI Blog", "https://openai.com/blog", True),
        ("Google AI Blog", "https://ai.googleblog.com/", True),
        ("Microsoft Blog", "https://blogs.microsoft.com/", True),
        ("AWS – AI Blog", "https://aws.amazon.com/blogs/aws/category/artificial-intelligence/", True),
        ("NVIDIA News/Blog", "https://blogs.nvidia.com/", True),
        ("IBM Research Blog", "https://research.ibm.com/blog", True),
    ]

    today_key = datetime.now().strftime("%Y-%m-%d")
    seed = int(hashlib.md5(today_key.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    free_sites = [{"name": n, "url": u} for (n, u, ok) in CURATED_SITES_POOL if ok]
    rng.shuffle(free_sites)
    footer_links = free_sites[:30]

    # Render the HTML template
    template_loader = jinja2.FileSystemLoader(searchpath="./templates")
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template("index.html.j2")
    output_html = template.render(
        main_headline=main_headline,
        column1=column1, column2=column2, column3=column3,
        current_year=datetime.now().year,
        footer_links=footer_links
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(output_html)

    print("Successfully generated new index.html with business-focused, paywall-aware curation + free mirrors.")
    print(f"Total runtime: {time.time() - overall_start:.2f} seconds")
