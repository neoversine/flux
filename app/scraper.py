from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import urllib.parse
import re
from typing import Set, Dict, List

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
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'form', 'button']):
        tag.decompose()
    keep_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul', 'ol', 'blockquote']
    for tag in soup.find_all(True):
        if tag.name not in keep_tags:
            tag.unwrap()
    content = soup.get_text(separator='\n', strip=True)
    content = re.sub(r'\n{2,}', '\n\n', content)
    return content.strip()

# --------------------------
# Tech detection dictionary
# --------------------------

TECH_SIGNATURES = {
    # Frontend
    "React": [r"id=['\"]root['\"]", r"react", r"react-dom"],
    "Next.js": [r"id=['\"]__next['\"]", r"_next/static"],
    "Vue.js": [r"vue(\.runtime)?\.js", r"__NUXT__"],
    "Angular": [r"ng-version"],
    "Svelte": [r"svelte"],
    "jQuery": [r"jquery.*\.js"],
    "Bootstrap": [r"bootstrap.*\.css", r"bootstrap.*\.js"],
    "Tailwind CSS": [r"tailwind.*\.css"],

    # Backend
    "Express.js": [r"x-powered-by.*express"],
    "NestJS": [r"nestjs"],
    "Django": [r"csrftoken"],
    "Flask": [r"flask"],
    "Rails": [r"_rails_session", r"x-runtime"],
    "Laravel": [r"laravel_session", r"x-powered-by.*php"],
    "ASP.NET": [r"ASP\.NET", r"aspnet"],
    "Spring Boot": [r"jsessionid"],

    # Databases
    "MongoDB": [r"ObjectId", r"_id"],
    "PostgreSQL": [r"PG::", r"postgres"],
    "MySQL": [r"MySQL"],
    "Firebase": [r"firebaseio\.com", r"firestore"],
    "Supabase": [r"supabase\.co"],

    # Servers
    "Nginx": [r"server: nginx"],
    "Apache": [r"server: apache"],
    "LiteSpeed": [r"server: litespeed"],
    "Caddy": [r"server: caddy"],

    # CDNs / Hosting
    "Vercel": [r"x-vercel-id"],
    "Netlify": [r"netlify"],
    "Cloudflare": [r"cf-ray", r"cf-cache-status"],
    "Akamai": [r"akamai"],
    "AWS CloudFront": [r"x-amz-cf-id"],
    "Firebase Hosting": [r"firebase"],

    # Analytics
    "Google Analytics": [r"gtag\.js", r"ga\.js"],
    "Google Tag Manager": [r"googletagmanager\.com"],
    "Hotjar": [r"hotjar"],
    "Mixpanel": [r"mixpanel"],
    "Facebook Pixel": [r"fbq\("],

    # Payment / Auth
    "Stripe": [r"js\.stripe\.com"],
    "Razorpay": [r"checkout\.razorpay\.com"],
    "PayPal": [r"paypalobjects\.com"],
    "Auth0": [r"auth0\.com"],
    "Firebase Auth": [r"identitytoolkit\.googleapis\.com"],

    # CMS & E-commerce
    "WordPress": [r"wp-content"],
    "Drupal": [r"drupal-settings-json"],
    "Shopify": [r"cdn\.shopify\.com"],
    "Magento": [r"mage/cookies\.js"],
    "Wix": [r"wixstatic\.com"],
}

# --------------------------
# Tech stack detection
# --------------------------

def detect_tech(html: str, scripts: List[str], headers: Dict[str, str]) -> List[str]:
    detected = set()
    content_sources = [html.lower()] + [s.lower() for s in scripts]

    # include headers
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

def scrape_multiple_pages(start_url: str, max_pages: int = 3) -> str:
    start_url = normalize_url(start_url)
    visited: Set[str] = set()
    results = []

    parsed_start = urllib.parse.urlparse(start_url)
    base_domain = f"{parsed_start.scheme}://{parsed_start.netloc}"

    def is_valid_link(href: str) -> bool:
        return href and (href.startswith('/') or href.startswith(base_domain))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        queue = [start_url]

        while queue and len(visited) < max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue

            try:
                response = page.goto(current_url, timeout=15000)
                page.wait_for_load_state('networkidle')
                html = page.content()
                visited.add(current_url)

                # Extract scripts
                soup = BeautifulSoup(html, "html.parser")
                scripts = [tag['src'] for tag in soup.find_all('script', src=True)]

                # Collect headers
                headers = {}
                if response:
                    headers = {k.lower(): v for k, v in response.headers.items()}

                # Detect tech
                tech_stack = detect_tech(html, scripts, headers)

                # Extract text
                text = get_text_from_html(html)

                results.append(
                    f"## {current_url}\n\n"
                    f"**Detected Tech:** {', '.join(tech_stack) if tech_stack else 'Unknown'}\n\n"
                    f"{text}"
                )

                # Add more links to crawl
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    full_url = urllib.parse.urljoin(base_domain, href)
                    if is_valid_link(href) and full_url not in visited and len(queue) + len(visited) < max_pages:
                        queue.append(full_url)

            except Exception as e:
                results.append(f"Error fetching {current_url}: {e}")

        browser.close()

    return "\n\n---\n\n".join(results)
