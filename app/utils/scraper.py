import subprocess
from playwright.sync_api import sync_playwright
import multiprocessing
from functools import partial
import asyncio
import sys
import urllib.parse
import uuid
from typing import Dict, List, Set, cast
from bs4 import BeautifulSoup, Tag
import re
import json
from random import randint

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
        # Remove potentially noisy tags
        for element in soup(['script', 'style', 'noscript', 'footer', 'header', 'form', 'button']):
            tag = cast(Tag, element)
            tag.decompose()

        # Convert relevant tags to markdown-friendly format - This part might be redundant or need adjustment based on desired markdown output
        # Let's rely on BeautifulSoup's get_text with a separator first.
        for element in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul', 'ol', 'blockquote']):
           tag = cast(Tag, element)
           if tag.name.startswith('h'):
                tag.insert_before(f"\n{'#' * int(tag.name[1])} ")
                tag.insert_after("\n")
           elif tag.name == 'p':
                tag.insert_before("\n")
                tag.insert_after("\n")
           elif tag.name in ['li']:
                tag.insert_before("* ")
                tag.insert_after("\n")
           elif tag.name in ['ul', 'ol', 'blockquote']:
                tag.insert_before("\n")
                tag.insert_after("\n")


        # Get text and clean up extra whitespace, using \n as separator
        content = soup.get_text(separator='\n', strip=True)
        content = re.sub(r'\n{3,}', '\n\n', content) # Reduce multiple newlines to at most two
        # content = re.sub(r'\s{2,}', ' ', content) # This might remove intended spaces within lines

        return content.strip()
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
    "Google Tag Manager": [r"googletagmanager\.com"],
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
    "Firebase Auth": [r"identitytoolkit\.googleapis\.com"],
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



def _scrape_single_process(start_url: str, max_pages: int) -> List[Dict]:
    start_url = normalize_url(start_url)
    visited: Set[str] = set()
    results = []
    
    parsed_start = urllib.parse.urlparse(start_url)
    base_domain = f"{parsed_start.scheme}://{parsed_start.netloc}"

    def is_valid_link(href: str) -> bool:
        if not href:
            return False
        try:
            parsed = urllib.parse.urlparse(href)
            # Accept links that are either relative or from the same domain
            return (not parsed.netloc) or parsed.netloc == parsed_start.netloc
        except Exception:
            return False

    with sync_playwright() as p:
        try:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0',
                java_script_enabled=True,
                accept_downloads=True,
                has_touch=False,
                is_mobile=False,
                locale='en-US'
            )
            page = context.new_page()
        except Exception as e:
            results.append({
                "url": start_url,
                "error": f"Failed to launch browser: {str(e)}. Ensure Playwright dependencies are installed on the VPS.",
                "detected_tech": [],
                "tech_categories": {},
                "content": "",
                "raw_html": "",
                "links": [],
                "images": [],
                "metadata": {
                    "title": None,
                    "meta_description": None,
                    "meta_keywords": None
                }
            })
            return results # Exit early if browser launch fails
        
        # Add error handling for common cloud hosting scenarios
        page.on("response", lambda response: handle_response_status(response))
        
        # Set default timeout
        page.set_default_timeout(30000)  # 30 seconds
        queue = [start_url]

        while queue and len(visited) < max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue

            response = None
            try:
                # Try to navigate to the page with proper error handling
                response = page.goto(
                    current_url,
                    timeout=30000,
                    wait_until="domcontentloaded"
                )
                status_code = response.status if response else None

                if not response or (status_code is not None and status_code >= 400):
                    error_msg = f"Website returned {status_code} for {current_url}"
                    results.append({
                        "url": current_url,
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
                    })
                    continue
                
                # Wait for the content to be loaded
                page.wait_for_load_state('domcontentloaded')
                page.wait_for_timeout(2000)  # Give JavaScript 2 seconds to execute
                
                # Add random mouse movements and delays to simulate human behavior
                page.mouse.move(
                    x=float(randint(100, 800)),
                    y=float(randint(100, 600))
                )
                page.wait_for_timeout(randint(500, 1500))
                
                html = page.content()
                visited.add(current_url)

                soup = BeautifulSoup(html, "html.parser")

                # Extract all links and images
                links = []
                images = []
                for tag in soup.find_all(['a', 'img']):
                    if isinstance(tag, Tag):
                        if tag.name == 'a':
                            href = tag.get('href')
                            text = tag.get_text(strip=True)
                            if href:
                                links.append({
                                    'url': href,
                                    'text': text if text else href
                                })
                        elif tag.name == 'img':
                            src = tag.get('src')
                            alt = tag.get('alt', '')
                            if src:
                                images.append({
                                    'url': src,
                                    'alt': alt
                                })

                # Collect scripts for tech detection
                scripts = []
                for tag in soup.find_all(["script", "link", "meta"]):
                    if isinstance(tag, Tag):
                        if tag.name == "script":
                            src = tag.get("src")
                            if src:
                                scripts.append(src)
                            # Also collect inline scripts for better detection
                            if tag.string:
                                scripts.append(tag.string)
                        elif tag.name == "link":
                            href = tag.get("href")
                            if href:
                                scripts.append(href)
                        elif tag.name == "meta":
                            content = tag.get("content", "")
                            name = tag.get("name", "")
                            if content and name:
                                scripts.append(f"{name}:{content}")

                headers = {}
                if response is not None:
                    headers = {k.lower(): v for k, v in response.headers.items()}

                tech_stack = detect_tech(html, scripts, headers)
                text = get_text_from_html(html)

                # Categorize the tech stack
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

                CATEGORY_MAP = {
                    "frontend": ["React", "Next.js", "Vue.js", "Angular", "Svelte", "jQuery", "Bootstrap", "Tailwind CSS", "Bulma", "Foundation", "Vuex", "Redux", "Gatsby", "Nuxt.js", "Vuetify", "Preact", "Lit", "Dojo"],
                    "backend": ["Express.js", "NestJS", "Django", "Flask", "Rails", "Laravel", "ASP.NET", "Spring Boot", "Node.js", "Go", "Ruby", "PHP", "Python", "Java", "C#", "Kotlin", "Rust", "Scala"],
                    "database": ["MongoDB", "PostgreSQL", "MySQL", "Firebase", "Supabase", "Redis", "Elasticsearch", "SQLite", "Microsoft SQL Server", "Cassandra", "Couchbase"],
                    "hosting": ["Vercel", "Netlify", "Cloudflare", "Akamai", "AWS CloudFront", "Firebase Hosting", "Heroku", "Google Cloud Platform", "Azure", "AWS S3", "DigitalOcean Spaces"],
                    "analytics": ["Google Analytics", "Google Tag Manager", "Hotjar", "Mixpanel", "Facebook Pixel", "Amplitude", "Matomo", "Segment", "Plausible Analytics"],
                    "payment": ["Stripe", "Razorpay", "PayPal", "Auth0", "Firebase Auth", "Okta", "Paddle", "Square", "Adyen"],
                    "cms": ["WordPress", "Drupal", "Shopify", "Magento", "Wix", "Joomla", "SquareSpace", "WooCommerce", "Headless CMS", "Contentful", "Strapi", "Ghost"],
                    "other": ["GraphQL", "Webpack", "Babel", "Docker", "Kubernetes", "REST API", "gRPC", "WebAssembly", "Storybook", "Cypress", "Selenium", "WebSockets", "Service Workers"]
                }

                for tech in tech_stack:
                    found_category = False
                    for category, techs_in_category in CATEGORY_MAP.items():
                        if tech in techs_in_category:
                            tech_categories[category].append(tech)
                            found_category = True
                            break
                    if not found_category:
                        tech_categories['other'].append(tech)

                # Extract metadata safely
                metadata = {
                    'title': soup.title.string if soup.title else None,
                    'meta_description': None,
                    'meta_keywords': None,
                    'statusCode': status_code
                }
                
                meta_desc = soup.find('meta', {'name': 'description'})
                if isinstance(meta_desc, Tag):
                    metadata['meta_description'] = meta_desc.get('content')
                    
                meta_keywords = soup.find('meta', {'name': 'keywords'})
                if isinstance(meta_keywords, Tag):
                    metadata['meta_keywords'] = meta_keywords.get('content')

                results.append({
                    "url": current_url,
                    "detected_tech": tech_stack if tech_stack else ["Unknown"],
                    "tech_categories": tech_categories,
                    "content": text,
                    "raw_html": html,
                    "links": links,
                    "images": images,
                    "metadata": metadata
                })

                for link in soup.find_all("a", href=True):
                    if isinstance(link, Tag):
                     href = link.get("href")

                     if isinstance(href, str):  # ✅ ensure it's a string
                        full_url = urllib.parse.urljoin(base_domain, href)

                        if (
                            is_valid_link(full_url)  # ✅ validate the resolved URL
                            and full_url not in visited
                            and len(queue) + len(visited) < max_pages
                        ):
                            queue.append(full_url)

            except Exception as e:
                error_message = str(e)
                if "net::ERR_NAME_NOT_RESOLVED" in error_message:
                    error_message = f"Could not resolve domain name for: {current_url}"
                elif "net::ERR_CONNECTION_REFUSED" in error_message:
                    error_message = f"Connection refused by: {current_url}"
                elif "net::ERR_CONNECTION_TIMED_OUT" in error_message:
                    error_message = f"Connection timed out while trying to reach: {current_url}"
                elif "AWS" in error_message:
                    error_message = f"Website hosted on AWS is not accessible or requires authentication: {current_url}"
                elif any(host in error_message for host in ["cloudfront", "s3.amazonaws", "amazonaws.com"]):
                    error_message = f"Website is hosted on AWS but is not properly configured or accessible: {current_url}"
                
                results.append({
                    "url": current_url,
                    "error": error_message,
                    "detected_tech": [],
                    "tech_categories": {},
                    "content": "",
                    "raw_html": "",
                    "links": [],
                    "images": [],
                    "metadata": {
                        "title": None,
                        "meta_description": None,
                        "meta_keywords": None
                    }
                })

        browser.close()

    return results

async def scrape_multiple_pages(start_url: str, max_pages: int = 3) -> List[Dict]:
    try:
        # Validate and normalize URL
        start_url = normalize_url(start_url)
        parsed_url = urllib.parse.urlparse(start_url)
        
        # First do a quick check if the domain resolves
        import socket
        try:
            socket.gethostbyname(parsed_url.netloc)
        except (socket.gaierror, socket.error):
            return [{
                "url": start_url,
                "error": f"Domain not found: {parsed_url.netloc}",
                "detected_tech": [],
                "tech_categories": {},
                "content": None,
                "raw_html": None,
                "links": [],
                "images": [],
                "metadata": {
                    "title": None,
                    "meta_description": None,
                    "meta_keywords": None
                }
            }]
        
        # Create a process pool with just one process to run Playwright
        with multiprocessing.Pool(1) as pool:
            # Run the scraping in a separate process
            result = await asyncio.get_event_loop().run_in_executor(
                None,  # Uses default executor
                partial(pool.apply, _scrape_single_process, args=(start_url, max_pages))
            )
            
        return result
    except ValueError as e:
        # Handle URL validation errors
        return [{
            "url": start_url,
            "error": str(e),
            "detected_tech": [],
            "tech_categories": {},
            "content": None,
            "raw_html": None,
            "links": [],
            "images": [],
            "metadata": {
                "title": None,
                "meta_description": None,
                "meta_keywords": None
            }
        }]
    except Exception as e:
        # Handle any other unexpected errors
        return [{
            "url": start_url,
            "error": f"Unexpected error: {str(e)}",
            "detected_tech": [],
            "tech_categories": {},
            "content": None,
            "raw_html": None,
            "links": [],
            "images": [],
            "metadata": {
                "title": None,
                "meta_description": None,
                "meta_keywords": None
            }
        }]



# --------------------------
# Formatting Output for Different Types
# --------------------------

def format_json_output(results: List[Dict]) -> str:
    if not results or len(results) == 0:
        return json.dumps({}, indent=2, ensure_ascii=False)

    r = results[0]  # Take first result
    
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

    response = {
        "json": company_info,
        "markdown": format_markdown_output([r]),
        "html": r.get('raw_html'),
        "links": links,
        "summary": content[:500] + ('...' if content and len(content) > 500 else '') if content else None,
        "metadata": response_metadata
    }
    
    # Remove None values from the main response
    response = {k: v for k, v in response.items() if v is not None}
    
    return json.dumps(response, indent=2, ensure_ascii=False)


def format_markdown_output(results: List[Dict]) -> str:
    """Format scraping results as markdown with custom styling."""
    if not results or len(results) == 0:
        return ""
        
    r = results[0]  # Take first result
    if 'error' in r:
        return f"# Error\n\n**Error Message**: {r['error']}\n\n---\n"

    md_output = []
    content = r.get('content')
    metadata = r.get('metadata', {})
    images = r.get('images', [])
    links = r.get('links', [])
    tech_categories = r.get('tech_categories', {})
    url = r.get('url')
    
    logo_url = next((img.get('url') for img in images if img.get('url') and 'logo' in img['url'].lower()), None)
    title = metadata.get('title')
    
    if logo_url:
        md_output.append(f"![logo]({logo_url})\n")
    if title:
        md_output.append(f"# {title}\n\n")
    
    if content:
        content_lines = content.split('\n')
        current_section = []
        
        for line in content_lines:
            line = line.strip()
            
            if not line:
                if current_section:
                    md_output.append("\n".join(current_section) + "\n\n")
                    current_section = []
                continue
                
            if line.startswith('#'):
                if current_section:
                    md_output.append("\n".join(current_section) + "\n\n")
                    current_section = []
                if line.startswith('# '):
                    line = line.replace('', '\n')
                current_section.append(line)
            else:
                current_section.append(line)
        
        if current_section:
            md_output.append("\n".join(current_section) + "\n\n")
    
    all_detected_tech = []
    for category in ['frontend', 'backend', 'database', 'hosting', 'analytics', 'cms', 'payment', 'other']:
        if tech_categories.get(category):
            all_detected_tech.extend(tech_categories[category])
    
    if all_detected_tech:
        md_output.append("## We build with\n\n")
        md_output.append(" • ".join(sorted(list(set(all_detected_tech)))) + " •\n\n")
    
    if logo_url and title and url:
        md_output.append(f"[![logo]({logo_url}){title}]({url})\n\n")
    
    nav_items = []
    for link in links:
        if isinstance(link, dict) and 'url' in link and 'text' in link:
            if '/works' in link['url'].lower():
                nav_items.append(f"[Our Works]({link['url']})")
            elif '/labs' in link['url'].lower():
                nav_items.append(f"[Labs]({link['url']})")
            elif '/about' in link['url'].lower():
                nav_items.append(f"[]({link['url']})")
    if nav_items:
        md_output.append(" ".join(nav_items) + "\n\n")
    
    connect_link = next((link for link in links if isinstance(link, dict) and '/contact' in link.get('url', '').lower()), None)
    if connect_link:
        md_output.append(f"[Connect]({connect_link['url']})\n\n")
    
    if logo_url and title and url:
        md_output.append(f"[![logo]({logo_url}){title}]({url})\n\n")
    
    return "".join(md_output)

def format_text_output(results: List[Dict]) -> str:
    text_output = []
    for r in results:
        if not isinstance(r, dict):
            continue

        url = r.get('url')
        if url is None:
            continue # Skip if URL is not available

        # Check for errors first
        if 'error' in r:
            text_output.extend([
                f"Website: {url}"
                "\n" + "="*50 + "\n"
            ])
            continue

        metadata = r.get('metadata', {})
        title = metadata.get('title')
        meta_desc = metadata.get('meta_description')

        tech_categories = r.get('tech_categories', {})
        content = r.get('content')
        links = r.get('links', [])
        images = r.get('images', [])

        text_output.append(f"Website: {url}")
        if title:
            text_output.append(f"Title: {title}")
        if meta_desc:
            text_output.append(f"Description: {meta_desc}")

        all_techs = [tech for category_list in tech_categories.values() for tech in category_list]
        if all_techs:
            text_output.extend([
                "\nTechnology Stack:",
                "----------------"
            ])
            for category, techs in tech_categories.items():
                if techs:
                    text_output.append(f"\n{category.title()}:")
                    text_output.append("  " + ", ".join(techs))

        if links:
            text_output.extend([
                "\nLinks Found:",
                "------------"
            ])
            for link in links[:10]:
                link_url = link.get('url')
                link_text = link.get('text')
                if link_url and link_text:
                    text_output.append(f"  • {link_text}: {link_url}")
            if len(links) > 10:
                text_output.append(f"  ... and {len(links) - 10} more links")

        if images:
            text_output.extend([
                "\nImages Found:",
                "-------------"
            ])
            for img in images[:10]:
                img_url = img.get('url')
                img_alt = img.get('alt')
                if img_url:
                    text_output.append(f"  • {img_alt or 'No description'}: {img_url}")
            if len(images) > 10:
                text_output.append(f"  ... and {len(images) - 10} more images")

        if content:
            text_output.extend([
                "\nContent Preview:",
                "---------------",
                content[:1000] + ('...' if len(content) > 1000 else ''),
                "\n" + "="*50 + "\n"
            ])
        else:
            text_output.append("\nNo content available.\n" + "="*50 + "\n")
    
    return "\n".join(text_output)

def format_ai_response_output(results: List[Dict]) -> str:
     # Placeholder for AI summarization or analysis
    return "AI response not yet implemented."
