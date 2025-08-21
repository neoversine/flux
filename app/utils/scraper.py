import subprocess
from playwright.sync_api import sync_playwright
import multiprocessing
from functools import partial
import asyncio
import sys
import urllib.parse
from typing import Dict, List, Set, cast
from bs4 import BeautifulSoup, Tag
import re
import json

# --------------------------
# Utility functions
# --------------------------


def normalize_url(input_url: str) -> str:
    input_url = input_url.strip()
    if not input_url.startswith("http://") and not input_url.startswith("https://"):
        input_url = "https://" + input_url
    return input_url


def get_text_from_html(html: str) -> str:
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
        return bool(href and (href.startswith('/') or href.startswith(base_domain)))

    try:
        subprocess.run(['playwright', 'install'], check=True)
    except Exception as e:
        print(f"Warning: Failed to install playwright: {str(e)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        queue = [start_url]

        while queue and len(visited) < max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue

            response = None
            try:
                response = page.goto(current_url, timeout=15000)
                page.wait_for_load_state('networkidle')
                html = page.content()
                visited.add(current_url)

                soup = BeautifulSoup(html, "html.parser")

                # ✅ Ensure tag is a Tag before calling .get()
                scripts = []
                for tag in soup.find_all("script", src=True):
                    if isinstance(tag, Tag):
                        src = tag.get("src")
                        if isinstance(src, str):
                            scripts.append(src)

                headers = {}
                if response is not None:
                    headers = {k.lower(): v for k, v in response.headers.items()}

                tech_stack = detect_tech(html, scripts, headers)
                text = get_text_from_html(html)

                results.append({
                    "url": current_url,
                    "detected_tech": tech_stack if tech_stack else ["Unknown"],
                    "content": text,
                    "raw_html": html
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
                results.append({
                    "url": current_url,
                    "detected_tech": ["Error"],
                    "content": str(e),
                    "raw_html": ""
                })

        browser.close()

    return results

async def scrape_multiple_pages(start_url: str, max_pages: int = 3) -> List[Dict]:
    start_url = normalize_url(start_url)
    
    # Create a process pool with just one process to run Playwright
    with multiprocessing.Pool(1) as pool:
        # Run the scraping in a separate process
        result = await asyncio.get_event_loop().run_in_executor(
            None,  # Uses default executor
            partial(pool.apply, _scrape_single_process, (start_url, max_pages))
        )
        
    return result

    return results



# --------------------------
# Formatting Output for Different Types
# --------------------------

def format_json_output(markdown_content: str) -> str:
    # Only add gaps inside markdown (not in JSON formatting itself)
    markdown_with_gaps = markdown_content.replace("\n", "\n\n")

    json_string = json.dumps({"markdown": markdown_with_gaps}, indent=2, ensure_ascii=False)
    return json_string


def format_markdown_output(results: List[Dict]) -> str:
    md_output = []
    for r in results:
        if not isinstance(r, dict):
            continue

        url = r.get('url', 'Unknown URL')
        soup = BeautifulSoup(r.get('raw_html', ''), 'html.parser')
        detected_tech = r.get('detected_tech', [])

        # Site Header
        md_output.append(f"# Website Analysis: {url}\n")
        
        # Site Title
        title = soup.find('title')
        if title:
            md_output.append(f"## {title.get_text(strip=True)}\n")

        # Technology Stack Section
        md_output.append("\n## Technology Stack\n")
        
        # Frontend Technologies
        frontend_tech = [tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('Frontend')]), [])]
        if frontend_tech:
            md_output.append("\n### Frontend\n")
            for tech in frontend_tech:
                md_output.append(f"- **{tech}**\n")

        # Backend Technologies
        backend_tech = [tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('Backend')]), [])]
        if backend_tech:
            md_output.append("\n### Backend\n")
            for tech in backend_tech:
                md_output.append(f"- **{tech}**\n")

        # Database Technologies
        db_tech = [tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('Databases')]), [])]
        if db_tech:
            md_output.append("\n### Databases\n")
            for tech in db_tech:
                md_output.append(f"- **{tech}**\n")

        # Hosting/CDN Technologies
        hosting_tech = [tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('CDNs / Hosting')]), [])]
        if hosting_tech:
            md_output.append("\n### Hosting & CDN\n")
            for tech in hosting_tech:
                md_output.append(f"- **{tech}**\n")

        # Analytics and Other Technologies
        other_tech = [tech for tech in detected_tech if tech not in frontend_tech + backend_tech + db_tech + hosting_tech]
        if other_tech:
            md_output.append("\n### Other Technologies\n")
            for tech in other_tech:
                md_output.append(f"- **{tech}**\n")

        # Content Section
        md_output.append("\n## Content Preview\n")
        content = r.get('content', 'No content available.')
        md_output.append(f"```\n{content[:500]}{'...' if len(content) > 500 else ''}\n```\n")

        # Navigation Links
        links = r.get('links', [])
        if links:
            md_output.append("\n## Site Navigation\n")
            for link in links[:10]:  # Limit to first 10 links
                md_output.append(f"- [{link}]({link})\n")

        md_output.append("\n---\n\n")

    return "".join(md_output)


def format_text_output(results: List[Dict]) -> str:
    text_output = []
    for r in results:
        if not isinstance(r, dict):
            continue

        url = r.get('url', 'Unknown URL')
        if not isinstance(url, str):
            url = str(url)

        soup = BeautifulSoup(r.get('raw_html', ''), 'html.parser')
        title = soup.find('title')
        title_text = title.get_text(strip=True) if title else 'No Title'

        detected_tech = r.get('detected_tech', ['Unknown'])
        content = r.get('content', 'No content available.')
        if not isinstance(content, str):
            content = str(content)

        # Structure the output in a more readable format
        text_output.extend([
            f"Website: {url}",
            f"Title: {title_text}",
            "\nTechnology Stack:",
            "----------------",
            "Frontend:",
            "  " + ", ".join([tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('Frontend')]), [])] or ['None detected']),
            "\nBackend:",
            "  " + ", ".join([tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('Backend')]), [])] or ['None detected']),
            "\nDatabases:",
            "  " + ", ".join([tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('Databases')]), [])] or ['None detected']),
            "\nHosting/CDN:",
            "  " + ", ".join([tech for tech in detected_tech if tech in TECH_SIGNATURES.keys() and tech in next(iter([k for k, v in TECH_SIGNATURES.items() if k.startswith('CDNs / Hosting')]), [])] or ['None detected']),
            "\nContent Preview:",
            "---------------",
            content[:1000] + ('...' if len(content) > 1000 else ''),
            "\n" + "="*50 + "\n"
        ])
    
    return "\n".join(text_output)

def format_ai_response_output(results: List[Dict]) -> str:
     # Placeholder for AI summarization or analysis
    return "AI response not yet implemented."
