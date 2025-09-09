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
    """Scrape a single page and return its data along with discovered internal links."""
    driver = None
    result: Dict[str, Any] = {}
    status_code = 200  # Default status code

    try:
        # Configure Chrome options
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        # Initialize webdriver
        driver = webdriver.Chrome(
            service=Service("/usr/bin/chromedriver"),
            options=chrome_options
        )

        try:
            # Set page load timeout
            driver.set_page_load_timeout(30)
            
            # Navigate to URL
            driver.get(url)
            
            # Wait for the document to be ready and all resources to be loaded
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            WebDriverWait(driver, 15).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            
            # Allow additional time for dynamic content to render
            time.sleep(5)
            
            # Get page content
            html = driver.page_source
            text = get_text_from_html(html)
            
            # Get HTTP headers and status code
            performance_logs = driver.execute_script(
                "return window.performance.getEntries()[0]"
            )
            headers = {}
            if isinstance(performance_logs, dict):
                response_headers = performance_logs.get('responseHeaders', {})
                if isinstance(response_headers, dict):
                    headers = response_headers

            # Parse content with BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            # Get metadata
            metadata = {
                'title': driver.title,
                'meta_description': None,
                'meta_keywords': None,
                'statusCode': status_code
            }
            
            # Get meta tags
            try:
                meta_desc = soup.find('meta', {'name': 'description'}) or soup.find('meta', {'property': 'og:description'})
                if isinstance(meta_desc, Tag):
                    metadata['meta_description'] = meta_desc.get('content')
                    
                meta_keywords = soup.find('meta', {'name': 'keywords'})
                if isinstance(meta_keywords, Tag):
                    metadata['meta_keywords'] = meta_keywords.get('content')
            except Exception:
                pass
            
            # Extract all links using Selenium for better JavaScript support
            links = []
            internal_links_to_crawl = set()
            base_netloc = urllib.parse.urlparse(url).netloc

            for element in driver.find_elements(By.TAG_NAME, "a"):
                try:
                    href = element.get_attribute('href')
                    link_text = element.text
                    
                    if href and isinstance(href, str):
                        href = href.strip()
                        if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                            continue
                        
                        parsed_href = urllib.parse.urlparse(href)
                        is_internal = parsed_href.netloc == base_netloc
                        
                        links.append({
                            'url': href,
                            'text': link_text.strip() if link_text else href,
                            'is_internal': is_internal
                        })
                        
                        if is_internal and parsed_href.path not in ['', '/'] and not parsed_href.fragment:
                            internal_links_to_crawl.add(urllib.parse.urljoin(url, href))

                except Exception:
                    continue
            
            # Extract all images
            images = []
            for element in driver.find_elements(By.TAG_NAME, "img"):
                try:
                    src = element.get_attribute('src')
                    alt = element.get_attribute('alt') or ''
                    class_name = element.get_attribute('class') or ''
                    
                    if src and isinstance(src, str):
                        src = src.strip()
                        if not src:
                            continue
                        
                        # Check if image is likely a logo
                        is_logo = ('logo' in src.lower() or 
                                 'logo' in alt.lower() or 
                                 'logo' in class_name.lower())
                        
                        # Add image info
                        images.append({
                            'url': src,
                            'alt': alt,
                            'is_logo': is_logo
                        })
                except Exception:
                    continue
            
            # Get all scripts
            scripts = []
            for element in driver.find_elements(By.TAG_NAME, "script"):
                try:
                    src = element.get_attribute('src')
                    if src and isinstance(src, str):
                        scripts.append(src)
                except Exception:
                    continue
            
            # Detect technologies
            detected_tech = detect_tech(html, scripts, headers)
            
            # Categorize technologies
            tech_categories = {
                'frontend': [],
                'backend': [],
                'database': [],
                'hosting': [],
                'analytics': [],
                'cms': [],
                'payment': [],
                'other': []
            }
            
            # Categorize detected technologies
            for tech in detected_tech:
                category = next((cat for cat, techs in TECH_SIGNATURES.items() 
                               if tech in ['frontend', 'backend', 'database', 'hosting', 'analytics', 'cms', 'payment']),
                              'other')
                tech_categories[category].append(tech)
            
            # Success result
            result = {
                "url": url,
                "error": None,
                "detected_tech": detected_tech,
                "tech_categories": tech_categories,
                "content": text,
                "raw_html": html,
                "links": links,
                "images": images,
                "metadata": metadata,
                "internal_links_to_crawl": list(internal_links_to_crawl)
            }
            
        except TimeoutException as e:
            result = create_error_result(
                url,
                f"Page load timeout: {str(e)}",
                status_code
            )
        except WebDriverException as e:
            result = create_error_result(
                url,
                f"Browser error: {str(e)}",
                status_code
            )
        except Exception as e:
            result = create_error_result(
                url,
                f"Scraping failed: {str(e)}",
                status_code
            )
            
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    
    return result

async def scrape_multiple_pages(start_url: str, max_pages: int = 3) -> List[Dict[str, Any]]:
    """Scrape multiple pages from a website starting from the given URL."""
    try:
        start_url = normalize_url(start_url)
        parsed_start_url = urllib.parse.urlparse(start_url)
        socket.gethostbyname(parsed_start_url.netloc)
        
        urls_to_visit = [start_url]
        visited_urls = set()
        all_results: List[Dict[str, Any]] = []
        
        with multiprocessing.Pool(1) as pool: # Use a pool for single process to manage browser lifecycle
            while urls_to_visit and len(all_results) < max_pages:
                current_url = urls_to_visit.pop(0)
                if current_url in visited_urls:
                    continue
                
                visited_urls.add(current_url)
                
                # Scrape the current page
                page_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    partial(pool.apply, _scrape_single_page, args=(current_url,))
                )
                
                if page_result and not page_result.get('error'):
                    all_results.append(page_result)
                    
                    # Add new internal links to the queue
                    for link in page_result.get('internal_links_to_crawl', []):
                        normalized_link = normalize_url(link)
                        if normalized_link not in visited_urls and normalized_link not in urls_to_visit:
                            urls_to_visit.append(normalized_link)
                else:
                    # If there's an error, still add it to results if it's the first page
                    if current_url == start_url:
                        all_results.append(page_result)
        
        return all_results
            
    except (ValueError, socket.gaierror, socket.error) as e:
        return [create_error_result(start_url, f"Invalid URL or domain not found: {str(e)}")]
    except Exception as e:
        return [create_error_result(start_url, f"Unexpected error: {str(e)}")]
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
    """Format a single page's scraping results as markdown, mirroring JSON structure."""
    if r.get('error'):
        return (
            f"# Error on Page: {r.get('url', 'Unknown URL')}\n\n"
            f"**Error Message**: {r.get('error')}\n"
            f"**Status Code**: {r.get('metadata', {}).get('statusCode', 'N/A')}\n\n---\n"
        )

    md_output = []
    content = r.get('content')
    metadata = r.get('metadata', {})
    images = r.get('images', [])
    links = r.get('links', [])
    tech_categories = r.get('tech_categories', {})
    url = r.get('url')

    md_output.append(f"## Scraped Page: {url}\n")
    md_output.append("==================================================\n\n")

    # Company Info (from metadata, mirroring 'json' key in JSON output)
    title = metadata.get('title')
    description = metadata.get('meta_description')
    if title:
        md_output.append(f"### Company Information:\n")
        md_output.append(f"- **Company Name**: {title}\n")
        if description:
            md_output.append(f"- **Company Description**: {description}\n\n")
        else:
            md_output.append("\n")

    # Summary
    if content:
        summary = content[:500] + ('...' if len(content) > 500 else '')
        md_output.append("### Summary:\n")
        md_output.append(f"{summary}\n\n")

    # Links
    if links:
        md_output.append("### Links:\n")
        md_output.append("----------------\n")
        internal_links = []
        external_links = []
        for link in links:
            if isinstance(link, dict) and 'url' in link and 'text' in link:
                if link.get('is_internal'):
                    internal_links.append(f"- [{link['text']}]({link['url']})")
                else:
                    external_links.append(f"- [{link['text']}]({link['url']})")
        
        if internal_links:
            md_output.append("#### Internal Links:\n")
            md_output.extend(internal_links)
            md_output.append("\n\n")
        
        if external_links:
            md_output.append("#### External Links:\n")
            md_output.extend(external_links)
            md_output.append("\n\n")

    # Metadata (mirroring 'metadata' key in JSON output)
    md_output.append("### Page Metadata:\n")
    md_output.append("----------------\n")
    for key, value in metadata.items():
        if value is not None:
            md_output.append(f"- **{key.replace('_', ' ').title()}**: {value}\n")
    md_output.append("\n")

    # Detected Tech
    all_detected_tech = []
    for category in ['frontend', 'backend', 'database', 'hosting', 'analytics', 'cms', 'payment', 'other']:
        if tech_categories.get(category):
            all_detected_tech.extend(tech_categories[category])
    
    if all_detected_tech:
        md_output.append("### Technology Stack:\n")
        md_output.append("----------------\n")
        for category in ['frontend', 'backend', 'database', 'hosting', 'analytics', 'cms', 'payment', 'other']:
            if tech_categories.get(category):
                md_output.append(f"{category.title()}:\n  " + ", ".join(sorted(tech_categories[category])) + "\n")
        md_output.append("\n")

    # Raw HTML (optional, can be very long)
    # md_output.append("### Raw HTML:\n")
    # md_output.append("```html\n" + r.get('raw_html', '')[:1000] + "...\n```\n\n") # Truncate raw HTML

    md_output.append("==================================================\n\n")
    
    return "".join(md_output)

def format_markdown_output(results: List[Dict]) -> str:
    """Format scraping results as markdown, handling multiple pages by concatenating single page outputs."""
    if not results:
        return "# No Results\n\nNo data was returned from the scraping operation.\n\n---\n"
    
    full_md_output = []
    for i, r in enumerate(results):
        full_md_output.append(f"## Result for Page {i+1}\n")
        full_md_output.append(format_markdown_output_single_page(r))
        full_md_output.append("\n") # Add a newline between pages for readability
    
    return "".join(full_md_output)

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

        # Start with website URL and page number
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

        # Add metadata
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

        # Add technology stack
        tech_categories = r.get('tech_categories', {})
        if tech_categories:
            full_text_output.append("Technology Stack:")
            full_text_output.append("-" * 16)
            for category, techs in tech_categories.items():
                if techs:
                    full_text_output.append(f"{category.title()}:")
                    full_text_output.append("  " + ", ".join(sorted(techs)))
            full_text_output.append("")

        # Add main content
        content = r.get('content')
        if content:
            full_text_output.append("Content:")
            full_text_output.append("-" * 8)
            full_text_output.append(content)
            full_text_output.append("")

        # Add navigation links
        links = r.get('links', [])
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
                    # Convert URL and text to lowercase for matching
                    url_lower = link_url.lower()
                    text_lower = text.lower()
                    
                    # Check if the link appears to be a navigation link
                    for category, patterns in common_nav_patterns.items():
                        if any(pattern in url_lower.replace('-', '').replace('_', '').replace('/', '') for pattern in patterns) or \
                           any(pattern in text_lower.replace('-', '').replace('_', '') for pattern in patterns):
                            nav_links.append(f"• {text}: {link_url}")
                            break
        
        if nav_links:
            full_text_output.append("Navigation:")
            full_text_output.append("-" * 10)
            # Remove duplicates while preserving order
            seen = set()
            unique_nav_links = []
            for link in nav_links:
                if link not in seen:
                    seen.add(link)
                    unique_nav_links.append(link)
            full_text_output.extend(unique_nav_links)
            full_text_output.append("")

        # Add separator at the end
        full_text_output.extend([
            "=" * 50,
            ""
        ])

    return "\n".join(full_text_output)

def format_ai_response_output(results: List[Dict]) -> str:
     # Placeholder for AI summarization or analysis
    return "AI response not yet implemented."
