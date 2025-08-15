#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ExhaustiveAI - Curation Pipeline (Business-Impact + Paywall-Aware + Free Mirror + Admin Overrides)
- Parallel RSS fetching with caching
- Google Gemini headline rewrite + sensational score
- Business-impact scoring (brands, deals, execs, authority, freshness)
- Paywall handling: remove always-paywall sources; search Google News for free mirrors
- Admin: applies overrides (headline/url/image), merges custom feeds, respects never-list (banned domains)
- Exports curated_items.json for admin panel
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
import json

# --- FILES (admin panel uses these) ---
OVERRIDES_FILE = 'overrides.json'          # {"overrides": { "<url>": {"headline": "...", "url": "...", "image_url": "..."} } }
BANNED_DOMAINS_FILE = 'banned_domains.json' # ["example.com", ...]
CUSTOM_FEEDS_FILE = 'custom_feeds.json'     # ["https://site/feed.xml", ...]
CURATED_DATA_FILE = 'curated_items.json'    # latest generated items for admin view

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
RSS_FEEDS_BASE = [
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

    # Google News queries (7-day window surfaces free mirrors)
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

STYLE_CLASSES = ['style1', 'style2', 'style3', 'style4']

SOURCE_MAP = {
    'theverge':'The Verge','techcrunch':'TechCrunch','wired':'Wired','fastcompany':'Fast Company',
    'venturebeat':'VentureBeat','eweek':'eWeek','infoworld':'InfoWorld','enterpriseai':'EnterpriseAI',
    'dailyai':'DailyAI','marktechpost':'MarkTechPost','emerj':'Emerj','crunchbase':'Crunchbase News',
    'nvidia':'NVIDIA','google':'Google','blogspot':'Google AI','amazon':'Amazon/AWS','microsoft':'Microsoft',
    'ibm':'IBM','salesforce':'Salesforce','oracle':'Oracle','apple':'Apple','adobe':'Adobe','meta':'Meta',
    'news':'Google News','businesswire':'BusinessWire','prnewswire':'PR Newswire',
}

AUTHORITY_WEIGHTS = {
    'TechCrunch':0.86,'VentureBeat':0.84,'The Verge':0.82,'Wired':0.82,'Fast Company':0.80,'EnterpriseAI':0.80,
    'InfoWorld':0.78,'eWeek':0.78,'Crunchbase News':0.78,'Google News':0.80,
    'NVIDIA':0.90,'Microsoft':0.88,'Google':0.88,'Amazon/AWS':0.88,'IBM':0.85,'Salesforce':0.84,'Oracle':0.83,
    'Apple':0.83,'Adobe':0.83,'Meta':0.82,'DailyAI':0.77,'MarkTechPost':0.75,'Emerj':0.78,
    'BusinessWire':0.65,'PR Newswire':0.60
}

# Paywall policy
PAYWALL_ALWAYS = { 'wsj', 'bloomberg', 'ft', 'theinformation', 'economist' }  # drop
METERED_OK = { 'nytimes', 'washingtonpost', 'businessinsider', 'theatlantic', 'forbes' }  # allow

# AI relevance keywords
AI_KEYWORDS = [
    'ai ','artificial intelligence','machine learning','neural network','deep learning','llm','generative ai',
    'chatgpt','gpt','model','algorithm','robotics','computer vision','natural language processing','nlp',
    'reinforcement learning','ai hardware','ai software','agi','autonomous','predictive analytics','genai',
    'foundation model','inference','gpu','accelerator','agents','agentic','rag'
]

MA_KEYWORDS = ['merger','acquisition','m&a','buyout','investment','funding round','venture capital','acquired','merged']
PEOPLE_KEYWORDS = ['hire','hires','leaves','joins','promoted','ceo','executive','cfo','cto','resigns','appointment']
BUSINESS_TERMS = [
    'acquisition','acquires','acquired','merger','m&a','deal','partnership','partner','strategic','investment',
    'funding','raises','series a','series b','valuation','earnings','guidance','revenue','profit','loss',
    'contract','agreement','licensing','deploys','rollout','selects','standardizes on','ipo','spinoff','joint venture'
]
EXEC_TERMS = ['ceo','cfo','cio','cto','chief executive','board','chair','svp','evp','general manager']
BREAKTHROUGH_KEYWORDS = ['breakthrough','revolution','game-changing','transformative','new model','agi','hardware advance','software breakthrough','innovation','first-ever','unveils','launches']

fortune_top_20 = ['Walmart','Amazon','Apple','UnitedHealth Group','Berkshire Hathaway','CVS Health','ExxonMobil','Alphabet','McKesson Corporation','Cencora','Costco','JPMorgan Chase','Microsoft','Cardinal Health','Chevron Corporation','Cigna','Ford Motor Company','Bank of America','General Motors','Elevance Health']
fortune_21_to_50 = ['Citigroup','Centene','The Home Depot','Marathon Petroleum','Kroger','Phillips 66','Fannie Mae','Walgreens Boots Alliance','Valero Energy','Meta Platforms','Verizon Communications','AT&T','Comcast','Wells Fargo','Goldman Sachs','Freddie Mac','Target Corporation','Humana','State Farm','Tesla','Morgan Stanley','Johnson & Johnson','Archer Daniels Midland','PepsiCo','United Parcel Service','FedEx','The Walt Disney Company','Dell Technologies',"Lowe's",'Procter & Gamble']
fortune_51_to_100 = ['Energy Transfer Partners','Boeing','Albertsons','Sysco','RTX Corporation','General Electric','Lockheed Martin','American Express','Caterpillar','MetLife','HCA Healthcare','Progressive Corporation','IBM','John Deere','Nvidia','StoneX Group','Merck & Co.','ConocoPhillips','Pfizer','Delta Air Lines','TD Synnex','Publix','Allstate','Cisco','Nationwide Mutual Insurance Company','Charter Communications','AbbVie','New York Life Insurance Company','Intel','TJX','Prudential Financial','HP','United Airlines','Performance Food Group','Tyson Foods','American Airlines','Liberty Mutual','Nike','Oracle Corporation','Enterprise Products','Capital One Financial','Plains All American Pipeline','World Kinect Corporation','AIG','Coca-Cola','TIAA','CHS','Bristol-Myers Squibb','Dow Chemical Company','Best Buy']

popular_ai_companies = ['Microsoft','NVIDIA','Google','Alphabet','Amazon','Meta','IBM','OpenAI','Salesforce','Oracle','SAP','Baidu','Alibaba','Tesla','Apple','Adobe','Intel','AMD','Qualcomm','Anthropic','xAI','DeepMind','Hugging Face','Stability AI','Cohere','Mistral AI','Databricks','ServiceNow','Snowflake','Palantir','Cisco']

# --- UTIL ---

def load_json_list(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def load_overrides_map(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('overrides', {}) if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_overrides_map(path, overrides_map):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'overrides': overrides_map}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed saving overrides: {e}")

def save_curated_data(path, main_headline, cols):
    try:
        items = []
        if main_headline:
            items.append(main_headline)
        for col in cols:
            items.extend(col)
        payload = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'items': items
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed saving curated data: {e}")

def domain_of(url: str) -> str:
    ex = tldextract.extract(url)
    return ex.domain.lower()

def publisher_from_url(url, fallback_feed_url):
    try:
        host = domain_of(url)
        return SOURCE_MAP.get(host, host.capitalize())
    except Exception:
        ex = tldextract.extract(fallback_feed_url)
        host = ex.domain.lower()
        return SOURCE_MAP.get(host, ex.domain.capitalize())

def is_always_paywalled(url: str, never_set=None) -> bool:
    try:
        d = domain_of(url)
        if never_set and d in never_set:
            return True
        return d in PAYWALL_ALWAYS
    except Exception:
        return False

def is_metered_allowed(url: str) -> bool:
    try:
        d = domain_of(url)
        return (d in METERED_OK) or (d not in PAYWALL_ALWAYS)
    except Exception:
        return True

STOPWORDS = {'the','and','for','with','from','that','this','a','an','on','in','of','to','as','by','at','vs','amid','after','before','over','into','about','its','their','our','your','his','her'}

def normalize_title(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r'\b(update|exclusive|opinion|analysis|breaking)\b', '', s)
    s = re.sub(r'[^a-z0-9]+', '', s)
    return s.strip()

def build_gn_query_from_title(title: str) -> str:
    tokens = re.findall(r'\b[A-Za-z0-9][A-Za-z0-9\-]{2,}\b', title or '')
    tokens = [t for t in tokens if t.lower() not in STOPWORDS][:6]
    if 'AI' not in [t.upper() for t in tokens]:
        tokens.append('AI')
    q = ' '.join(f'intitle:{t}' for t in tokens) + ' when:14d'
    return q

def google_news_search_articles(q: str, max_results: int = 10):
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
        link = entry.get('link'); title = entry.get('title', '')
        if not link or not title:
            continue
        source_name = publisher_from_url(link, url)
        source_authority = AUTHORITY_WEIGHTS.get(source_name, 0.75)
        if 'published_parsed' in entry and entry.published_parsed:
            dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
        elif 'updated_parsed' in entry and entry.updated_parsed:
            dt = datetime.fromtimestamp(time.mktime(entry.updated_parsed))
        else:
            dt = datetime.min
        published = dt.replace(tzinfo=timezone.utc)
        results.append({'title': title,'url': link,'source': source_name,'source_authority': source_authority,'image_url': None,'summary': entry.get('summary', 'No summary available.'),'published': published})
    return results

def freshness_multiplier(published_at: datetime, half_life_hours=48.0) -> float:
    try:
        delta_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600.0
        delta_hours = max(delta_hours, 0.0)
        return 0.5 ** (delta_hours / half_life_hours)
    except Exception:
        return 0.8

# --- FETCHERS ---

def load_rss_feeds():
    base = list(RSS_FEEDS_BASE)
    custom = load_json_list(CUSTOM_FEEDS_FILE)
    merged = list(dict.fromkeys(base + [u for u in custom if isinstance(u, str) and u.strip()]))
    return merged

def load_never_domains():
    lst = load_json_list(BANNED_DOMAINS_FILE)
    return set([tldextract.extract(d).domain.lower() for d in lst if isinstance(d, str)])

def get_articles_from_rss(RSS_FEEDS):
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
                source_name = publisher_from_url(entry.link, feed_url)
                source_authority = AUTHORITY_WEIGHTS.get(source_name, 0.75)
                article = {'title': entry.title,'url': entry.link,'source': source_name,'source_authority': source_authority}
                image_url = None
                if 'media_content' in entry and entry.media_content:
                    image_url = entry.media_content[0].get('url')
                elif 'media_thumbnail' in entry and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get('url')
                elif 'enclosures' in entry and entry.enclosures:
                    for enc in entry.enclosures:
                        if 'image' in enc.get('type', ''):
                            image_url = enc.get('href'); break
                if not image_url and 'summary' in entry:
                    soup = BeautifulSoup(entry.summary, 'html.parser')
                    img = soup.find('img')
                    if img and img.get('src'):
                        image_url = img['src']
                article['image_url'] = image_url
                article['summary'] = entry.get('summary', "No summary available.")
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
    articles = []
    try:
        search = arxiv.Search(query="cat:cs.AI", max_results=MAX_ARTICLES_PER_SOURCE, sort_by=arxiv.SortCriterion.SubmittedDate)
        client = arxiv.Client()
        for result in client.results(search):
            articles.append({'title': result.title,'url': result.entry_id,'published': result.published,'image_url': None,'summary': result.summary if result.summary else "No summary available.",'source': 'arXiv','source_authority': AUTHORITY_WEIGHTS.get('arXiv', 0.72)})
    except Exception as e:
        print(f"Error fetching from arXiv: {e}")
    return articles

# --- FILTERS & SCORING ---

def is_ai_related(title, summary):
    text = (title + " " + summary).lower()
    return any(kw in text for kw in AI_KEYWORDS)

async def async_get_headline_and_score(title, summary):
    fallback_headline = title.strip()
    prompt = f"""
    Analyze the following article title and summary.
    First, on a scale of 1 to 20, rate how provocative, sensational, and AI-specific it is.
    Second, rewrite the title in a punchy, viral, factual style (<15 words). Put major company up front.
    Third, rate technical-importance 0-10 (breakthroughs).
    Respond: score|headline|tech
    Title: "{title}"
    Summary: "{summary[:500]}"
    """
    try:
        response = await gemini_model.generate_content_async(prompt)
        parts = response.text.strip().split('|', 3)
        if len(parts) >= 3:
            score = int(parts[0].strip()); headline = parts[1].strip().replace('*',''); tech_importance = int(parts[2].strip())
            return headline, score, tech_importance
        else:
            return fallback_headline, 5, 0
    except Exception as e:
        print(f"Error processing title '{title}': {e}")
        await asyncio.sleep(2)
        return fallback_headline, 5, 0

def get_related_image_url(headline):
    kw = headline.lower().split()
    if any(k in ['ai','artificial','intelligence','machine','learning'] for k in kw):
        return "https://source.unsplash.com/600x300/?ai,technology"
    return "https://via.placeholder.com/600x300?text=AI+Headline+Image"

def get_boost(title, summary, source):
    text = (title + " " + summary).lower()
    boost = 0
    for company in popular_ai_companies:
        if company.lower() in text: boost += 8
    for c in fortune_top_20:
        if c.lower() in text: boost += 22
    for c in fortune_21_to_50:
        if c.lower() in text: boost += 14
    for c in fortune_51_to_100:
        if c.lower() in text: boost += 8
    if any(kw in text for kw in BUSINESS_TERMS): boost += 18
    if any(kw in text for kw in EXEC_TERMS): boost += 10
    if any(kw in text for kw in ['merger','acquisition','m&a','buyout']): boost += 10
    if any(p in text for p in ['sam altman','elon musk','jensen huang','satya nadella','sundar pichai','demis hassabis','ila sutskever','andrew ng','fei-fei li','yann lecun','tim cook','mark zuckerberg','jeff bezos','dario amodei']): boost += 10
    if any(kw in text for kw in BREAKTHROUGH_KEYWORDS): boost += 14
    if source in ['BusinessWire','PR Newswire']: boost -= 8
    if source in ['NVIDIA','Microsoft','Google','Amazon/AWS','IBM','Salesforce','Oracle','Apple','Adobe','Meta']: boost += 6
    if source in ['arXiv','MIT News',"O'Reilly"]: boost += 3
    return min(max(boost, 0), 100)

def freshness_multiplier_scored(published_at: datetime, half_life_hours=48.0) -> float:
    return freshness_multiplier(published_at, half_life_hours)

# --- MIRROR HELPERS ---

def choose_best_candidate(candidates, never_set=None):
    pool = [c for c in candidates if not is_always_paywalled(c.get('url',''), never_set)]
    if not pool: return None
    non_gn = [c for c in pool if domain_of(c['url']) != 'news']
    if non_gn: pool = non_gn
    def rank_key(c):
        paywall_penalty = 0 if is_metered_allowed(c['url']) else -1
        auth = c.get('source_authority', 0.75)
        pub = c.get('published', datetime.min.replace(tzinfo=timezone.utc))
        return (paywall_penalty, auth, pub)
    pool.sort(key=rank_key, reverse=True)
    return pool[0]

def find_free_mirror_by_title(title: str, never_set=None):
    if not title: return None
    q = build_gn_query_from_title(title)
    gn_hits = google_news_search_articles(q, max_results=10)
    return choose_best_candidate(gn_hits, never_set=never_set)

# --- CACHE ---

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
    try:
        response = requests.get(feed_url, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Error fetching {feed_url}: {e}")
        feed = {'entries': []}
    return feed, feed_url

# --- MAIN ---

if __name__ == "__main__":
    overall_start = time.time()
    print("Starting content generation for Exhaustive AI...")

    # Load admin-configurable lists
    NEVER_DOMAINS = load_never_domains()   # user "not ever" list
    RSS_FEEDS = load_rss_feeds()           # base + custom feeds
    overrides_map = load_overrides_map(OVERRIDES_FILE)

    # Fetch
    fetch_start = time.time()
    all_articles = get_articles_from_rss(RSS_FEEDS) + get_articles_from_arxiv()
    print(f"Article fetching took {time.time() - fetch_start:.2f} seconds")

    # Group by normalized title; select best (drop always-paywall, try mirror)
    groups = {}
    for a in all_articles:
        title = a.get('title', '')
        norm = normalize_title(title) or (domain_of(a.get('url','')) + normalize_title(title))
        groups.setdefault(norm, []).append(a)

    deduped = []
    for norm, items in groups.items():
        best = choose_best_candidate(items, never_set=NEVER_DOMAINS)
        if not best:
            rep_title = max((it.get('title','') for it in items), key=len, default='')
            mirror = find_free_mirror_by_title(rep_title, never_set=NEVER_DOMAINS)
            if mirror:
                print(f"Free mirror found for '{rep_title}': {mirror.get('url')}")
                best = mirror
        if best:
            deduped.append(best)

    # AI filter + never list safety
    filtered = []
    for a in deduped:
        if not a.get('url'): continue
        if is_always_paywalled(a['url'], NEVER_DOMAINS): continue
        if is_ai_related(a.get('title',''), a.get('summary','')): filtered.append(a)
        else: print(f"Discarded non-AI article: {a.get('title','(no title)')}")

    # Technical gating
    technical_sources = ['arXiv','MIT News',"O'Reilly"]
    technical_articles = [a for a in filtered if a.get('source') in technical_sources]
    non_technical_articles = [a for a in filtered if a.get('source') not in technical_sources]
    technical_articles.sort(key=lambda x: x['published'], reverse=True)
    technical_articles = technical_articles[:MAX_TECHNICAL_ARTICLES]

    curated = non_technical_articles + technical_articles
    curated.sort(key=lambda x: x['published'], reverse=True)
    articles_to_process = curated[:MAX_TOTAL_ARTICLES]
    print(f"Selected {len(articles_to_process)} articles after filters/mirrors.")

    # Gemini pass
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
        auth = article.get('source_authority', 0.75)
        fresh = freshness_multiplier_scored(pub_date)
        base = sens_score + boost + tech_importance
        authority_mult = 0.75 + 0.5 * max(0.6, min(1.0, auth))
        fresh_mult = 0.6 + 0.8 * fresh
        final_score = round(base * authority_mult * fresh_mult, 4)
        processed_articles.append({
            'headline': headline,'url': article['url'],'score': final_score,
            'image_url': article.get('image_url'),'related_image_url': related_image_url,
            'summary': article.get('summary', "No summary available."),'source': article.get('source', 'Unknown Source'),
            'published': pub_date.isoformat(),'style': style
        })
        print(f"  -> Sens:{sens_score} Boost:{boost} Tech:{tech_importance} Auth:{auth} Fresh:{fresh:.3f} Final:{final_score} Source:{article.get('source','?')} Title:{headline}")

    # --- APPLY ADMIN OVERRIDES (headline/url/image_url) ---
    if overrides_map:
        for item in processed_articles:
            key = item.get('url')
            if key and key in overrides_map:
                ov = overrides_map[key]
                if 'headline' in ov and ov['headline']: item['headline'] = ov['headline']
                if 'url' in ov and ov['url']: item['url'] = ov['url']
                if 'image_url' in ov: item['image_url'] = ov['image_url'] or item.get('image_url')

    # Rank by final score
    processed_articles.sort(key=lambda x: x['score'], reverse=True)
    main_headline = processed_articles[0] if processed_articles else None
    other_headlines = processed_articles[1:]
    col_size = (len(other_headlines) + 2) // 3
    column1 = other_headlines[0:col_size]
    column2 = other_headlines[col_size:col_size*2]
    column3 = other_headlines[col_size*2:]

    # Export items for admin panel
    save_curated_data(CURATED_DATA_FILE, main_headline, [column1, column2, column3])

    # Footer rotation (unchanged)
    CURATED_SITES_POOL = [
        ("Reuters – AI","https://www.reuters.com/technology/artificial-intelligence/",True),
        ("Axios – AI","https://www.axios.com/technology/automation-and-ai",True),
        ("CNBC – Tech","https://www.cnbc.com/technology/",True),
        ("Techmeme","https://techmeme.com/",True),
        ("VentureBeat – AI","https://venturebeat.com/category/ai/",True),
        ("TechCrunch – AI","https://techcrunch.com/category/artificial-intelligence/",True),
        ("The Verge – AI","https://www.theverge.com/ai-artificial-intelligence",True),
        ("ZDNet – AI","https://www.zdnet.com/topic/artificial-intelligence/",True),
        ("The Register – AI","https://www.theregister.com/Tag/AI/",True),
        ("InfoWorld – AI","https://www.infoworld.com/artificial-intelligence/",True),
        ("eWeek – AI","https://www.eweek.com/artificial-intelligence/",True),
        ("Engadget – AI","https://www.engadget.com/tag/ai/",True),
        ("Tom’s Hardware – AI","https://www.tomshardware.com/t/ai/",True),
        ("SiliconANGLE – AI","https://siliconangle.com/tag/ai/",True),
        ("The Next Platform – AI/HPC","https://www.nextplatform.com/category/machine-learning/",True),
        ("DatacenterDynamics – AI","https://www.datacenterdynamics.com/en/ai/",True),
        ("HPCwire – AI","https://www.hpcwire.com/tag/ai/",True),
        ("ServeTheHome – AI","https://www.servethehome.com/tag/ai/",True),
        ("AI News (industry)","https://www.artificialintelligence-news.com/",True),
        ("AI Business","https://aibusiness.com/",True),
        ("DailyAI","https://dailyai.com/",True),
        ("MarkTechPost","https://www.marktechpost.com/",True),
        ("The Decoder","https://the-decoder.com/",True),
        ("Unite.AI","https://www.unite.ai/",True),
        ("OpenAI Blog","https://openai.com/blog",True),
        ("Google AI Blog","https://ai.googleblog.com/",True),
        ("Microsoft Blog","https://blogs.microsoft.com/",True),
        ("AWS – AI Blog","https://aws.amazon.com/blogs/aws/category/artificial-intelligence/",True),
        ("NVIDIA News/Blog","https://blogs.nvidia.com/",True),
        ("IBM Research Blog","https://research.ibm.com/blog",True),
    ]
    today_key = datetime.now().strftime("%Y-%m-%d")
    seed = int(hashlib.md5(today_key.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    free_sites = [{"name": n, "url": u} for (n, u, ok) in CURATED_SITES_POOL if ok]
    rng.shuffle(free_sites)
    footer_links = free_sites[:30]

    # Render HTML
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

    print("Successfully generated new index.html with overrides and admin data export.")
    print(f"Total runtime: {time.time() - overall_start:.2f} seconds")
