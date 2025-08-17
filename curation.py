import os
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

DEBUG_MODE = os.getenv('DEBUG_MODE', '0') == '1'

# Curated RSS feeds with AI security priority
RSS_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.marktechpost.com/feed/",
    "https://www.analyticsvidhya.com/feed/",
    "https://dailyai.com/feed/",
    "https://aibusiness.com/rss.xml",
    "https://www.infoworld.com/artificial-intelligence/feed/",
    "https://aws.amazon.com/blogs/aws/category/artificial-intelligence/feed/",
    "https://news.ycombinator.com/rss",
    "https://fastcompany.com/section/artificial-intelligence/rss",
    "http://arxiv.org/rss/cs.AI",
    "https://snyk.io/blog/category/application-security/rss/"  # Retained for Snyk
]

MAX_ARTICLES_PER_SOURCE = 3
MAX_TOTAL_ARTICLES = 20
MAX_TECHNICAL_ARTICLES = 4
CACHE_FILE = 'rss_cache.pkl'
CACHE_TTL = 3600
MIN_CACHE_ARTICLES = 15  # Threshold for cache refresh

# Style options (to be removed in Batch 3)
STYLE_CLASSES = ['style1', 'style2', 'style3', 'style4']

# Updated source mapping
SOURCE_MAP = {
    'techcrunch': 'TechCrunch',
    'venturebeat': 'VentureBeat',
    'marktechpost': 'MarkTechPost',
    'analyticsvidhya': 'Analytics Vidhya',
    'dailyai': 'DailyAI',
    'aibusiness': 'AIBusiness',
    'infoworld': 'Infoworld',
    'aws': 'Amazon',
    'ycombinator': 'Hacker News',
    'fastcompany': 'FastCompany',
    'arxiv': 'arXiv',
    'snyk': 'Snyk'
}

AI_KEYWORDS = [
    'ai ', 'artificial intelligence', 'machine learning', 'neural network', 'deep learning', 
    'llm', 'generative ai', 'chatgpt', 'gpt', 'model', 'algorithm', 'robotics', 'computer vision',
    'natural language processing', 'nlp', 'reinforcement learning', 'ai hardware', 'ai software',
    'agi', 'autonomous', 'predictive analytics', 'security', 'vulnerability', 'threat', 'snyk',
    'cloud', 'investment', 'infrastructure', 'funding'  # Added business terms
]

MA_KEYWORDS = ['merger', 'acquisition', 'm&a', 'buyout', 'investment', 'funding round', 'venture capital', 'acquired', 'merged']
PEOPLE_KEYWORDS = ['hire', 'hires', 'leaves', 'joins', 'promoted', 'ceo', 'executive', 'cfo', 'cto', 'resigns', 'appointment']
BREAKTHROUGH_KEYWORDS = ['breakthrough', 'revolution', 'game-changing', 'transformative', 'new model', 'agi', 'hardware advance', 'software breakthrough', 'innovation', 'first-ever', 'unveils', 'launches']
KEY_AI_PEOPLE = [
    'sam altman', 'elon musk', 'jensen huang', 'satya nadella', 'sundar pichai', 
    'demis hassabis', 'ila sutskever', 'andrew ng', 'fei-fei li', 'yann lecun',
    'tim cook', 'mark zuckerberg', 'jeff bezos', 'dario amodei'
]

fortune_top_20 = [
    'Walmart', 'Amazon', 'Apple', 'UnitedHealth Group', 'Berkshire Hathaway', 'CVS Health', 'ExxonMobil', 
    'Alphabet', 'McKesson Corporation', 'Cencora', 'Costco', 'JPMorgan Chase', 'Microsoft', 'Cardinal Health', 
    'Chevron Corporation', 'Cigna', 'Ford Motor Company', 'Bank of America', 'General Motors', 'Elevance Health'
]
fortune_21_to_50 = [
    'Citigroup', 'Centene', 'The Home Depot', 'Marathon Petroleum', 'Kroger', 'Phillips 66', 'Fannie Mae', 
    'Walgreens Boots Alliance', 'Valero Energy', 'Meta Platforms', 'Verizon Communications', 'AT&T', 'Comcast', 
    'Wells Fargo', 'Goldman Sachs', 'Freddie Mac', 'Target Corporation', 'Humana', 'State Farm', 'Tesla', 
    'Morgan Stanley', 'Johnson & Johnson', 'Archer Daniels Midland', 'PepsiCo', 'United Parcel Service', 
    'FedEx', 'The Walt Disney Company', 'Dell Technologies', "Lowe's", 'Procter & Gamble'
]
fortune_51_to_100 = [
    'Energy Transfer Partners', 'Boeing', 'Albertsons', 'Sysco', 'RTX Corporation', 'General Electric', 
    'Lockheed Martin', 'American Express', 'Caterpillar', 'MetLife', 'HCA Healthcare', 'Progressive Corporation', 
    'IBM', 'John Deere', 'Nvidia', 'StoneX Group', 'Merck & Co.', 'ConocoPhillips', 'Pfizer', 'Delta Air Lines', 
    'TD Synnex', 'Publix', 'Allstate', 'Cisco', 'Nationwide Mutual Insurance Company', 'Charter Communications', 
    'AbbVie', 'New York Life Insurance Company', 'Intel', 'TJX', 'Prudential Financial', 'HP', 'United Airlines', 
    'Performance Food Group', 'Tyson Foods', 'American Airlines', 'Liberty Mutual', 'Nike', 'Oracle Corporation', 
    'Enterprise Products', 'Capital One Financial', 'Plains All American Pipeline', 'World Kinect Corporation', 
    'AIG', 'Coca-Cola', 'TIAA', 'CHS', 'Bristol-Myers Squibb', 'Dow Chemical Company', 'Best Buy'
]
popular_ai_companies = [
    'Microsoft', 'NVIDIA', 'Google', 'Alphabet', 'Amazon', 'Meta', 'IBM', 'OpenAI', 'Salesforce',
    'Oracle', 'SAP', 'Baidu', 'Alibaba', 'Tesla', 'Apple', 'Adobe', 'Intel', 'AMD', 'Qualcomm',
    'Anthropic', 'xAI', 'DeepMind', 'Hugging Face', 'Stability AI', 'Cohere', 'Mistral AI',
    'Snyk', 'Crowdstrike', 'Palo Alto Networks', 'Databricks', 'Perplexity', 'Grok'
]

# --- FUNCTIONS ---

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            cache = pickle.load(f)
        if time.time() - cache.get('timestamp', 0) < CACHE_TTL:
            articles = cache.get('articles', [])
            if len(articles) < MIN_CACHE_ARTICLES:  # Refresh if too few articles
                return None
            return articles
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

def get_articles_from_rss():
    start_time = time.time()
    cached_articles = load_cache()
    if cached_articles:
        print("Using cached RSS articles")
    else:
        print("Fetching fresh RSS articles")

    articles = cached_articles if cached_articles else []
    if not cached_articles:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(fetch_feed, url): url for url in RSS_FEEDS}
            for future in concurrent.futures.as_completed(future_to_url):
                feed, feed_url = future.result()
                extracted = tldextract.extract(feed_url)
                domain = extracted.domain.lower()
                source_name = SOURCE_MAP.get(domain, extracted.domain.capitalize())
                for entry in feed.get('entries', [])[:MAX_ARTICLES_PER_SOURCE]:
                    if entry.get('title') and entry.get('link'):
                        article = {'title': entry.title, 'url': entry.link}
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
                        article['summary'] = entry.get('summary', "No summary available.")
                        if 'published' in entry:
                            dt = datetime(*entry.published_parsed[:6])
                        elif 'updated' in entry:
                            dt = datetime(*entry.updated_parsed[:6])
                        else:
                            dt = datetime.min
                        article['published'] = dt.replace(tzinfo=timezone.utc)
                        article['source'] = source_name
                        articles.append(article)
        save_cache(articles)
    print(f"RSS fetching took {time.time() - start_time:.2f} seconds")
    return articles

def get_articles_from_arxiv():
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
                'source': 'arXiv'
            })
    except Exception as e:
        print(f"Error fetching from arXiv: {e}")
    return articles

def is_ai_related(title, summary):
    text = (title + " " + summary).lower()
    if DEBUG_MODE:
        print(f"Debug: Checking article - Title: {title}, Summary: {summary[:50]}...")
    if any(kw in text for kw in AI_KEYWORDS):
        if DEBUG_MODE:
            matched_kw = next(kw for kw in AI_KEYWORDS if kw in text)
            print(f"Debug: Matched keyword: {matched_kw}")
        return True
    if any(company.lower() in text for company in popular_ai_companies):
        if DEBUG_MODE:
            matched_company = next(company for company in popular_ai_companies if company.lower() in text)
            print(f"Debug: Matched company: {matched_company}")
        return True
    if DEBUG_MODE:
        print(f"Debug: No match found for keywords or companies in '{title}'")
    return False

async def async_get_headline_and_score(title, summary, url):
    fallback_headline = title.strip()
    # Fallback scoring if API fails
    fallback_score = 5
    if any(company.lower() in (title + " " + summary).lower() for company in popular_ai_companies):
        fallback_score += 5  # Bonus for big names
    prompt = f"""
    Analyze the following article title, summary, and URL.
    First, on a scale of 1 to 20, rate how provocative, sensational, and AI-specific it is. Higher scores for controversial, shocking stories evoking strong emotions, controversy, breakthroughs, or business impacts in AI.
    Second, rewrite the title as an ultra-sensational, viral, clickbait-style headline that's irresistible—evoke curiosity, fear, excitement, FOMO, or shock while staying completely factual and not lying. Ensure the headline reflects the source (e.g., company name) and content accurately based on the URL. Avoid attributing to a company not in the URL domain. Keep it punchy and under 15 words.
    Third, if this seems technical/academic or a breakthrough in AI HW/SW, rate its importance/impact on a scale of 1-10 (higher for game-changers); otherwise, return 0.

    Respond with the score, the headline, and tech_importance separated by pipe characters (|). For example: 18|Microsoft unleashes AI revolution that could change everything!|8

    Article Title: "{title}"
    Article Summary: "{summary[:500]}"
    Article URL: "{url}"
    """
    try:
        response = await gemini_model.generate_content_async(prompt)
        parts = response.text.strip().split('|', 2)
        if len(parts) == 3:
            score = int(parts[0].strip())
            headline = parts[1].strip().replace('*', '')
            tech_importance = int(parts[2].strip())
            return headline, score, tech_importance
        return fallback_headline, fallback_score, 0
    except Exception as e:
        print(f"Error processing title '{title}': {e}")
        await asyncio.sleep(60)  # Increased delay for quota reset
        return fallback_headline, fallback_score, 0

def get_related_image_url(headline):
    keywords = headline.lower().split()
    if any(kw in ['ai', 'artificial', 'intelligence', 'machine', 'learning'] for kw in keywords):
        return f"https://source.unsplash.com/600x300/?ai,technology"
    return "https://via.placeholder.com/600x300?text=AI+Headline+Image"

def get_boost(title, summary, source, article):
    text = (title + " " + summary).lower()
    boost = 0
    for company in popular_ai_companies:
        if company.lower() in text:
            boost += 20  # Increased from 10 for big names
    for company in fortune_top_20:
        if company.lower() in text:
            boost += 30
    for company in fortune_21_to_50:
        if company.lower() in text:
            boost += 20
    for company in fortune_51_to_100:
        if company.lower() in text:
            boost += 10
    if any(kw in text for kw in MA_KEYWORDS):
        boost += 25
    if any(kw in text for kw in PEOPLE_KEYWORDS):
        boost += 20
        if any(person in text for person in KEY_AI_PEOPLE):
            boost += 15
    if any(kw in text for kw in BREAKTHROUGH_KEYWORDS):
        boost += 30
    technical_sources = ['arXiv', 'MIT News', "O'Reilly"]
    if source in technical_sources:
        boost += 5
    if source in technical_sources and boost < 10:
        boost -= 5
    # Enhanced: Business relevance boost (increased to 20 for stronger prioritization)
    business_keywords = ['funding', 'investment', 'enterprise', 'market', 'revenue', 'data center', 'expansion']
    if any(kw in text for kw in business_keywords):
        boost += 20
    # New: Startup/funding boost
    startup_keywords = ['startup', 'seed funding', 'series a', 'series b', 'venture funding']
    if any(kw in text for kw in startup_keywords):
        boost += 20
    # New: Security boost (prioritizes Snyk)
    security_keywords = ['security', 'vulnerability', 'threat', 'hack', 'breach', 'snyk']
    if any(kw in text for kw in security_keywords):
        boost += 25
    # New: Recency boost
    now = datetime.now(timezone.utc)
    if 'published' in article and (now - article['published']).total_seconds() < 24 * 3600:
        boost += 10
    return min(max(boost, 0), 100)

def main():
    overall_start = time.time()
    print("Starting content generation for Exhaustive AI...")

    # Fetch articles
    fetch_start = time.time()
    all_articles = get_articles_from_rss() + get_articles_from_arxiv()
    print(f"Article fetching took {time.time() - fetch_start:.2f} seconds")

    # Deduplication and filtering
    filter_start = time.time()
    seen_urls = set()
    unique_articles = []
    for article in all_articles:
        if article.get('url') and article['url'] not in seen_urls:
            if is_ai_related(article['title'], article['summary']):
                unique_articles.append(article)
                seen_urls.add(article['url'])
            else:
                print(f"Discarded non-AI article: {article['title']} - Reason: No AI keywords or companies matched")
    technical_sources = ['arXiv', 'MIT News', "O'Reilly"]
    technical_articles = [a for a in unique_articles if a['source'] in technical_sources]
    non_technical_articles = [a for a in unique_articles if a['source'] not in technical_sources]
    
    # Score all unique articles first
    process_start = time.time()
    async def process_articles_async():
        tasks = [async_get_headline_and_score(article['title'], article['summary'], article['url']) for article in unique_articles]
        return await asyncio.gather(*tasks)

    headline_results = asyncio.run(process_articles_async())
    scored_articles = []
    for article, (headline, sens_score, tech_importance) in zip(unique_articles, headline_results):
        pub_date = article['published']
        if pub_date == datetime.min.replace(tzinfo=timezone.utc):
            pub_date = datetime.now(timezone.utc)
        related_image_url = get_related_image_url(headline)
        style = random.choice(STYLE_CLASSES)
        boost = get_boost(article['title'], article['summary'], article.get('source', ''), article)
        final_score = sens_score + boost + tech_importance
        scored_articles.append({
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
        if DEBUG_MODE:
            print(f"Debug: Processed - Headline: {headline}, Score: {final_score}, Source: {article['source']}, URL: {article['url']}")

    print(f"Article processing (API calls) took {time.time() - process_start:.2f} seconds")

    # Sort by score and select top 20
    scored_articles.sort(key=lambda x: x['score'], reverse=True)
    articles_to_process = scored_articles[:MAX_TOTAL_ARTICLES]

    print(f"Filtering took {time.time() - filter_start:.2f} seconds")
    print(f"Selected {len(articles_to_process)} articles.")

    # Separate main headline
    main_headline = articles_to_process[0] if articles_to_process else None
    other_headlines = articles_to_process[1:]

    # Split into columns
    col_size = (len(other_headlines) + 2) // 3
    column1 = other_headlines[0:col_size]
    column2 = other_headlines[col_size:col_size*2]
    column3 = other_headlines[col_size*2:]

    # Render template
    template_loader = jinja2.FileSystemLoader(searchpath="./templates")
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template("index.html.j2")
    output_html = template.render(
        main_headline=main_headline,
        column1=column1,
        column2=column2,
        column3=column3,
        current_year=datetime.now().year
    )

    # Write HTML
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(output_html)

    print(f"Successfully generated new index.html with Drudge-style layout.")
    print(f"Total runtime: {time.time() - overall_start:.2f} seconds")

if __name__ == "__main__":
    main()
