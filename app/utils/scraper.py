import subprocess
import multiprocessing
from functools import partial
import asyncio
import sys
import socket
import urllib.parse
import uuid
from typing import Dict, List, Set, cast, Optional, Any
from bs4 import BeautifulSoup, Tag
import re
import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# --------------------------
# Utility functions
# --------------------------
def handle_response_status(response):
    """Handle different response statuses and cloud hosting scenarios."""
    status = response.status
    url = response.url
    headers = response.headers
    
    if status >= 400:
        error_msg = None
        if 'x-amz-' in str(headers).lower() or 'cloudfront' in str(headers).lower():
            if status == 403:
                error_msg = "Access denied by AWS CloudFront or S3"
            elif status == 404:
                error_msg = "Resource not found on AWS"
            else:
                error_msg = f"AWS returned error status {status}"
        elif 'azure' in str(headers).lower():
            error_msg = f"Azure hosting error: Status {status}"
        elif 'cf-ray' in str(headers).lower():
            error_msg = f"Cloudflare protection active: Status {status}"
            
        if error_msg:
            raise Exception(error_msg)

def normalize_url(input_url: str) -> str:
    """Normalize and validate the URL."""
    input_url = input_url.strip()

    # Handle protocol
    if not input_url.startswith(('http://', 'https://')):
        input_url = 'https://' + input_url

    # Parse the URL
    try:
        parsed = urllib.parse.urlparse(input_url)
        netloc = parsed.netloc

        # Enforce www prefix for bare domains
        if netloc.count('.') == 1 and not netloc.startswith('www.'):
            netloc = 'www.' + netloc

        # Reconstruct the URL
        path = parsed.path or '/'
        final_url = f"{parsed.scheme}://{netloc}{path}"
        if parsed.query:
            final_url += f"?{parsed.query}"

        return final_url
    except Exception as e:
        raise ValueError(f"Invalid URL format: {str(e)}")


def get_text_from_html(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove unwanted elements that typically don't contain useful text content
        for element in soup.find_all(['script', 'style', 'noscript', 'iframe', 'meta', 'link', 
                                    'svg', 'canvas', 'input', 'button', 'form', 'header', 'footer', 'nav']):
            element.decompose()
        
        # Extract all visible text
        text_content = []
        for element in soup.find_all(text=True):
            # Ensure element.parent is not None before accessing its name
            if element.parent and element.parent.name not in ['style', 'script', 'head', 'title', 'meta', '[document]']:
                stripped_text = str(element).strip() # Cast to string to ensure .strip() is available
                if stripped_text:
                    text_content.append(stripped_text)
        
        # Join all parts
        text = ' '.join(text_content)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)      # Normalize all whitespace to single spaces
        text = text.strip()
        
        return text
    
    except Exception as e:
        return f"Error extracting text from HTML: {str(e)}"

# --------------------------
# Tech detection dictionary
# --------------------------
TECH_SIGNATURES = {
    # Frontend
    "React": [r"id=['\"]root['\"]", r"react", r"react-dom"],
    "Next.js": [r"id=['\"]__next['\"]", r"_next/static"],
    "Vue.js": [r"vue(\.runtime)?\.js", r"_NUXT_"],
    "Angular": [r"ng-version"],
    "Svelte": [r"svelte"],
    "jQuery": [r"jquery.*\.js"],
    "Bootstrap": [r"bootstrap.\.css", r"bootstrap.\.js"],
    "Tailwind CSS": [r"tailwind.*\.css"],
    "Bulma": [r"bulma\.css"],
    "Foundation": [r"foundation\.css"],
    "Vuex": [r"vuex"],
    "Redux": [r"redux"],
    "Gatsby": [r"id=['\"]___gatsby['\"]"],
    "Nuxt.js": [r"_NUXT_"],
    "Vuetify": [r"vuetify\.min\.js"],
    "Preact": [r"preact"], # Added Preact
    "Lit": [r"lit-html"], # Added Lit
    "Dojo": [r"dojo\.js"], # Added Dojo Toolkit


    # Backend
    "Express.js": [r"x-powered-by.*express"],
    "NestJS": [r"nestjs"],
    "Django": [r"csrftoken"],
    "Flask": [r"flask"],
    "Rails": [r"_rails_session", r"x-runtime"],
    "Laravel": [r"laravel_session", r"x-powered-by.*php"],
    "ASP.NET": [r"ASP\.NET", r"aspnet"],
    "Spring Boot": [r"jsessionid"],
    "Node.js": [r"x-powered-by.*nodejs"],
    "Go": [r"go version"],
    "Ruby": [r"ruby version"],
    "PHP": [r"x-powered-by.*php"],
    "Python": [r"python version", r"server: python"], # Added Python server detection
    "Java": [r"java version", r"server: java"], # Added Java server detection
    "C#": [r"c# version", r"server: c#"], # Added C# server detection
    "Kotlin": [r"kotlin"], # Added Kotlin
    "Rust": [r"rustc version"], # Added Rust
    "Scala": [r"scala version"], # Added Scala


    # Databases
    "MongoDB": [r"ObjectId", r"_id"],
    "PostgreSQL": [r"PG::", r"postgres"],
    "MySQL": [r"MySQL"],
    "Firebase": [r"firebaseio\.com", r"firestore"],
    "Supabase": [r"supabase\.co"],
    "Redis": [r"redis"],
    "Elasticsearch": [r"elasticsearch"],
    "SQLite": [r"sqlite"], # Added SQLite
    "Microsoft SQL Server": [r"sql server"], # Added SQL Server
    "Cassandra": [r"cassandra"], # Added Cassandra
    "Couchbase": [r"couchbase"], # Added Couchbase


    # Servers
    "Nginx": [r"server: nginx"],
    "Apache": [r"server: apache"],
    "LiteSpeed": [r"server: litespeed"],
    "Caddy": [r"server: caddy"],
    "IIS": [r"server: iis"],
    "Tomcat": [r"apache-tomcat"], # Added Tomcat
    "Jetty": [r"jetty"], # Added Jetty


    # CDNs / Hosting
    "Vercel": [r"x-vercel-id"],
    "Netlify": [r"netlify"],
    "Cloudflare": [r"cf-ray", r"cf-cache-status"],
    "Akamai": [r"akamai"],
    "AWS CloudFront": [r"x-amz-cf-id"],
    "Firebase Hosting": [r"firebase"],
    "Heroku": [r"heroku"],
    "Google Cloud Platform": [r"x-goog-gfe"],
    "Azure": [r"azurewebsites\.net"], # Added Azure hosting
    "AWS S3": [r"amazonaws\.com"], # Added AWS S3
    "DigitalOcean Spaces": [r"digitaloceanspaces\.com"], # Added DigitalOcean Spaces


    # Analytics
    "Google Analytics": [r"gtag\.js", r"ga\.js"],
    "Hotjar": [r"hotjar"],
    "Mixpanel": [r"mixpanel"],
    "Facebook Pixel": [r"fbq\("],
    "Amplitude": [r"amplitude\.js"],
    "Matomo": [r"matomo\.js"], # Added Matomo
    "Segment": [r"segment\.io"], # Added Segment
    "Plausible Analytics": [r"plausible\.io/js/script\.js"], # Added Plausible


    # Payment / Auth
    "Stripe": [r"js\.stripe\.com"],
    "Razorpay": [r"checkout\.razorpay\.com"],
    "PayPal": [r"paypalobjects\.com"],
    "Auth0": [r"auth0\.com"],
    "Okta": [r"okta\.com"],
    "Paddle": [r"paddle\.js"], # Added Paddle
    "Square": [r"squarecdn\.com"], # Added Square
    "Adyen": [r"adyen\.com"], # Added Adyen


    # CMS & E-commerce
    "WordPress": [r"wp-content"],
    "Drupal": [r"drupal-settings-json"],
    "Shopify": [r"cdn\.shopify\.com"],
    "Magento": [r"mage/cookies\.js"],
    "Wix": [r"wixstatic\.com"],
    "Joomla": [r"joomla"],
    "SquareSpace": [r"squarespace\.com"],
    "WooCommerce": [r"woocommerce"], # Added WooCommerce
    "Headless CMS": [r"graphql.*cms", r"api.*cms"], # Generic pattern for headless CMS
    "Contentful": [r"cdn\.contentful\.com"], # Added Contentful
    "Strapi": [r"strapi"], # Added Strapi
    "Ghost": [r"ghost-cdn\.com"], # Added Ghost


    # Other
    "GraphQL": [r"graphql"],
    "Webpack": [r"webpack"],
    "Babel": [r"babel"],
    "Docker": [r"docker"],
    "Kubernetes": [r"kubernetes"],
    "REST API": [r"api/v\d+", r"/api/"], # Generic pattern for REST API
    "gRPC": [r"grpc-web"], # Added gRPC
    "WebAssembly": [r"wasm"], # Added WebAssembly
    "Storybook": [r"storybook"], # Added Storybook
    "Cypress": [r"cypress"], # Added Cypress
    "Selenium": [r"selenium"], # Added Selenium
    "WebSockets": [r"websocket"], # Added WebSockets
    "Service Workers": [r"service-worker\.js"], # Added Service Workers


}

# --------------------------
# Tech stack detection
# --------------------------


def detect_tech(html: str, scripts: List[str], headers: Dict[str, str]) -> List[str]:
    detected = set()
    content_sources = [html.lower()] + [s.lower() for s in scripts]
    header_str = " ".join([f"{k}:{v}" for k, v in headers.items()])
    content_sources.append(header_str.lower())

    for tech, patterns in TECH_SIGNATURES.items():
        for pattern in patterns:
            for source in content_sources:
                if re.search(pattern, source, re.IGNORECASE):
                    detected.add(tech)
                    break
    return sorted(detected)

# --------------------------
# Main scraper
# --------------------------



def create_error_result(url: str, error_msg: str, status_code: Optional[int] = None) -> Dict[str, Any]:
    """Create a standardized error result"""
    return {
        "url": url,
        "error": error_msg,
        "detected_tech": [],
        "tech_categories": {},
        "content": "",
        "raw_html": "",
        "links": [],
        "images": [],
        "metadata": {
            "title": None,
            "meta_description": None,
            "meta_keywords": None,
            "statusCode": status_code
        }
    }

def _scrape_single_page(url: str) -> Dict[str, Any]:
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--remote-debugging-port=9222")

        driver = webdriver.Chrome(
            service=Service("/usr/bin/chromedriver"),
            options=chrome_options
        )

        driver.set_page_load_timeout(30)
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(3)

        html = driver.page_source
        text = get_text_from_html(html)
        soup = BeautifulSoup(html, "html.parser")

        # Metadata
        metadata = {
            "title": driver.title or None,
            "meta_description": (soup.find('meta', {'name': 'description'}) or {}).get('content'),
            "meta_keywords": (soup.find('meta', {'name': 'keywords'}) or {}).get('content'),
            "statusCode": 200
        }

        # Links
        links, internal_links_to_crawl = [], set()
        base_netloc = urllib.parse.urlparse(url).netloc
        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute('href')
            text_link = a.text.strip() or href
            if href and not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                parsed_href = urllib.parse.urlparse(href)
                is_internal = parsed_href.netloc == base_netloc
                links.append({"url": href, "text": text_link, "is_internal": is_internal})
                if is_internal and parsed_href.path not in ['', '/'] and not parsed_href.fragment:
                    internal_links_to_crawl.add(urllib.parse.urljoin(url, href))

        # Images
        images = []
        for img in driver.find_elements(By.TAG_NAME, "img"):
            src = img.get_attribute('src')
            alt = img.get_attribute('alt') or ''
            class_name = img.get_attribute('class') or ''
            if src:
                images.append({
                    'url': src,
                    'alt': alt,
                    'is_logo': 'logo' in src.lower() or 'logo' in alt.lower() or 'logo' in class_name.lower()
                })

        # Placeholder tech detection
        tech_categories = {"frontend": [], "backend": [], "database": [], "hosting": [],
                           "analytics": [], "cms": [], "payment": [], "other": ["React"]}

        return {
            "url": url,
            "error": None,
            "content": text,
            "raw_html": html,
            "links": links,
            "images": images,
            "metadata": metadata,
            "tech_categories": tech_categories,
            "internal_links_to_crawl": list(internal_links_to_crawl)
        }

    except TimeoutException as e:
        return create_error_result(url, f"Page load timeout: {str(e)}")
    except WebDriverException as e:
        return create_error_result(url, f"Browser error: {str(e)}")
    except Exception as e:
        return create_error_result(url, f"Scraping failed: {str(e)}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    
    return result

async def scrape_multiple_pages(start_url: str, max_pages: int = 3) -> List[Dict[str, Any]]:
    start_url = normalize_url(start_url)
    try:
        socket.gethostbyname(urllib.parse.urlparse(start_url).netloc)
    except (ValueError, socket.gaierror, socket.error) as e:
        return [create_error_result(start_url, f"Invalid URL or domain not found: {str(e)}")]
    except Exception as e:
        return [create_error_result(start_url, f"Unexpected error during domain resolution: {str(e)}")]

    urls_to_visit, visited_urls, results = [start_url], set(), []

    while urls_to_visit and len(results) < max_pages:
        current_url = urls_to_visit.pop(0)
        if current_url in visited_urls:
            continue

        visited_urls.add(current_url)
        page_result = await asyncio.get_event_loop().run_in_executor(
            None, partial(_scrape_single_page, current_url)
        )
        results.append(page_result)

        for link in page_result.get('internal_links_to_crawl', []):
            try:
                normalized_link = normalize_url(link)
                parsed_link = urllib.parse.urlparse(normalized_link)
                if parsed_link.netloc == urllib.parse.urlparse(start_url).netloc:
                    if normalized_link not in visited_urls and normalized_link not in urls_to_visit:
                        urls_to_visit.append(normalized_link)
            except Exception:
                continue

    return results

# --------------------------
# Formatting Output for Different Types
# --------------------------

def format_json_output(results: List[Dict]) -> str:
    """Format scraping results as JSON, handling multiple pages."""
    if not results:
        return json.dumps([], indent=2, ensure_ascii=False) # Return an empty list for no results

    formatted_pages = []
    for r in results:
        if not isinstance(r, dict):
            continue

        content = r.get('content')
        metadata = r.get('metadata', {})
        
        company_info = {
            "company_name": metadata.get('title'),
            "company_description": metadata.get('meta_description')
        }
        
        links = []
        for link_data in r.get('links', []):
            url = link_data.get('url')
            if url and not url.startswith('#') and not url.startswith('javascript:'):
                links.append(url)
        
        response_metadata = {
            "description": metadata.get('meta_description'),
            "favicon": r.get('favicon'),
            "title": metadata.get('title'),
            "language": "en", # Defaulting to 'en' as it's a common practice and usually detected
            "scrapeId": str(uuid.uuid4()),
            "sourceURL": urllib.parse.urlparse(r.get('url', '')).netloc if r.get('url') else None,
            "url": r.get('url'),
            "statusCode": r.get('metadata', {}).get('statusCode'),
            "contentType": "text/html; charset=utf-8", # This is a reasonable default for web scraping
            "proxyUsed": "basic", # This is an internal detail, can be defaulted
            "cacheState": "miss", # This is an internal detail, can be defaulted
            "creditsUsed": 5 # This is an internal detail, can be defaulted
        }
        
        # Remove None values from metadata
        response_metadata = {k: v for k, v in response_metadata.items() if v is not None}

        page_response = {
            "json": company_info,
            "markdown": format_markdown_output_single_page(r), # Call new function for single page markdown
            "html": r.get('raw_html'),
            "links": links,
            "summary": content[:500] + ('...' if content and len(content) > 500 else '') if content else None,
            "metadata": response_metadata
        }
        
        # Remove None values from the page response
        page_response = {k: v for k, v in page_response.items() if v is not None}
        formatted_pages.append(page_response)
    
    return json.dumps(formatted_pages, indent=2, ensure_ascii=False)


def format_markdown_output_single_page(r: Dict) -> str:
    if r.get('error'):
        return f"# Error on Page: {r.get('url', 'Unknown URL')}\n\n**Error Message**: {r.get('error')}\n\n---\n"

    md = [f"## Scraped Page: {r.get('url', '')}\n", "="*50 + "\n"]
    metadata = r.get('metadata', {})
    content = r.get('content', '')
    images = r.get('images', [])
    links = r.get('links', [])
    tech_categories = r.get('tech_categories', {})

    # Company Info
    if metadata.get('title'):
        md.append("### Company Information:\n")
        md.append(f"- **Company Name**: {metadata['title']}\n")
        if metadata.get('meta_description'):
            md.append(f"- **Company Description**: {metadata['meta_description']}\n")
        md.append("\n")

    # Full content
    if content:
        md.append("### Full Content:\n" + "-"*16 + "\n")
        md.append(content + "\n\n")

    # Links
    if links:
        internal, external = [], []
        for link in links:
            text = link.get('text', link.get('url'))
            url_link = link.get('url')
            if link.get('is_internal'):
                internal.append(f"- [{text}]({url_link})")
            else:
                external.append(f"- [{text}]({url_link})")
        if internal:
            md.append("### Internal Links:\n" + "\n".join(internal) + "\n\n")
        if external:
            md.append("### External Links:\n" + "\n".join(external) + "\n\n")

    # Images
    if images:
        md.append("### Images:\n")
        for img in images:
            md.append(f"- {img['url']} (alt: {img.get('alt','')})")
        md.append("\n")

    # Page Metadata
    if metadata:
        md.append("### Page Metadata:\n")
        for k, v in metadata.items():
            if v: md.append(f"- **{k.replace('_',' ').title()}**: {v}")
        md.append("\n")

    # Technology stack
    if tech_categories:
        md.append("### Technology Stack:\n")
        for cat, techs in tech_categories.items():
            if techs:
                md.append(f"- **{cat.title()}**: {', '.join(sorted(techs))}")
        md.append("\n")

    md.append("="*50 + "\n\n")
    return "\n".join(md)

def format_markdown_output(results: List[Dict]) -> str:
    if not results:
        return "# No Results\n\nNo data returned.\n\n---\n"
    full_md = []
    for i, r in enumerate(results):
        full_md.append(f"# Result for Page {i+1}\n\n")
        full_md.append(format_markdown_output_single_page(r))
    return "\n".join(full_md)


def format_text_output(results: List[Dict]) -> str:
    """Format scraping results as plain text, handling multiple pages."""
    if not results:
        return "No results available."
        
    full_text_output = []
    
    for i, r in enumerate(results):
        if not isinstance(r, dict):
            continue

        url = r.get('url')
        if not url:
            continue

        # Page header
        full_text_output.extend([
            f"Page {i+1}: {url}",
            "=" * 50,
            ""
        ])

        # Handle errors
        error = r.get('error')
        if error and error not in ('None', None):
            full_text_output.extend([
                "Error occurred while scraping:",
                str(error),
                "",
                "=" * 50,
                ""
            ])
            continue

        # Metadata
        metadata = r.get('metadata', {})
        title = metadata.get('title')
        description = metadata.get('meta_description')
        keywords = metadata.get('meta_keywords')

        if title:
            full_text_output.append(f"Title: {title}")
        if description:
            full_text_output.append(f"Description: {description}")
        if keywords:
            full_text_output.append(f"Keywords: {keywords}")
        full_text_output.append("")

        # Technology Stack
        tech_categories = r.get('tech_categories', {})
        if tech_categories:
            full_text_output.append("Technology Stack:")
            full_text_output.append("-" * 16)
            for category, techs in tech_categories.items():
                if techs:
                    full_text_output.append(f"{category.title()}: {', '.join(sorted(techs))}")
            full_text_output.append("")

        # Main content (truncate long content for readability)
        content = r.get('content', '')
        if content:
            max_len = 3000
            display_content = content[:max_len] + ("..." if len(content) > max_len else "")
            full_text_output.extend([
                "Content:",
                "-" * 8,
                display_content,
                ""
            ])

        # Links
        links = r.get('links', [])
        if links:
            full_text_output.append("Links:")
            full_text_output.append("-" * 8)
            for link in links:
                if isinstance(link, dict):
                    text = link.get('text', link.get('url'))
                    link_url = link.get('url')
                else:
                    text = link_url = str(link)
                if link_url and text:
                    full_text_output.append(f"- {text}: {link_url}")
            full_text_output.append("")

        # Images
        images = r.get('images', [])
        if images:
            full_text_output.append("Images:")
            full_text_output.append("-" * 8)
            for img in images:
                url = img.get('url')
                alt = img.get('alt', '')
                if url:
                    full_text_output.append(f"- {url} (alt: {alt})")
            full_text_output.append("")

        # Navigation links (optional categorization)
        nav_links = []
        common_nav_patterns = {
            'about': ['about', 'about-us', 'company', 'who-we-are', 'our-story'],
            'contact': ['contact', 'contact-us', 'reach-us', 'get-in-touch', 'support'],
            'services': ['services', 'solutions', 'what-we-do', 'offerings', 'products'],
            'portfolio': ['portfolio', 'works', 'projects', 'case-studies', 'our-work'],
            'team': ['team', 'our-team', 'people', 'staff', 'members'],
            'blog': ['blog', 'news', 'articles', 'insights', 'posts'],
            'careers': ['careers', 'jobs', 'work-with-us', 'join-us', 'opportunities']
        }

        for link in links:
            if isinstance(link, dict):
                link_url = link.get('url', '')
                text = link.get('text', '').strip()
                if link_url and text and not link_url.startswith(('#', 'javascript:', 'tel:', 'mailto:')):
                    url_lower = link_url.lower()
                    text_lower = text.lower()
                    for category, patterns in common_nav_patterns.items():
                        if any(p in url_lower.replace('-', '').replace('_', '').replace('/', '') for p in patterns) or \
                           any(p in text_lower.replace('-', '').replace('_', '') for p in patterns):
                            nav_links.append(f"• {text}: {link_url}")
                            break

        if nav_links:
            full_text_output.append("Navigation Links:")
            full_text_output.append("-" * 16)
            # Remove duplicates while preserving order
            seen = set()
            unique_nav_links = [l for l in nav_links if not (l in seen or seen.add(l))]
            full_text_output.extend(unique_nav_links)
            full_text_output.append("")

        # Page separator
        full_text_output.extend([
            "=" * 50,
            ""
        ])

    return "\n".join(full_text_output)


def format_ai_response_output(results: List[Dict]) -> str:
     # Placeholder for AI summarization or analysis
    return "AI response not yet implemented."
