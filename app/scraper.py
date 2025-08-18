from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from bs4.element import Tag 
import urllib.parse
import re
from typing import Set, Dict, List , cast
import gradio as gr
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


def scrape_multiple_pages(start_url: str, max_pages: int = 3) -> List[Dict]:
    start_url = normalize_url(start_url)
    visited: Set[str] = set()
    results = []

    parsed_start = urllib.parse.urlparse(start_url)
    base_domain = f"{parsed_start.scheme}://{parsed_start.netloc}"

    def is_valid_link(href: str) -> bool:
        return bool(href and (href.startswith('/') or href.startswith(base_domain)))

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



# --------------------------
# Formatting Output for Gradio Tabs
# --------------------------

def format_json_output(markdown_content: str) -> str:
    # Only add gaps inside markdown (not in JSON formatting itself)
    markdown_with_gaps = markdown_content.replace("\n", "\n\n")

    json_string = json.dumps({"markdown": markdown_with_gaps}, indent=2, ensure_ascii=False)
    return json_string

[{
	"resource": "/root/agents_tool_kit/app/main.py",
	"owner": "pylance",
	"code": {
		"value": "reportArgumentType",
		"target": {
			"$mid": 1,
			"path": "/microsoft/pylance-release/blob/main/docs/diagnostics/reportArgumentType.md",
			"scheme": "https",
			"authority": "github.com"
		}
	},
	"severity": 8,
	"message": "Argument of type \"List[Dict[Unknown, Unknown]]\" cannot be assigned to parameter \"markdown_content\" of type \"str\" in function \"format_json_output\"\n  \"List[Dict[Unknown, Unknown]]\" is not assignable to \"str\"",
	"source": "Pylance",
	"startLineNumber": 125,
	"startColumn": 47,
	"endLineNumber": 125,
	"endColumn": 54,
	"origin": "extHost2"
}]
def format_markdown_output(results: List[Dict]) -> str:
    md_output = []
    for r in results:
        md_output.append(f"# {r['url']}\n\n")  # URL as top-level heading

        soup = BeautifulSoup(r["raw_html"], "html.parser")

        # --- 1. Logo and Site Title ---
        logo_tag: Tag | None = None
        site_title = soup.find("title")
        site_title_text = site_title.get_text(strip=True) if site_title else ""

        for img in soup.find_all("img"):
            if isinstance(img, Tag):
                src = img.get("src")
                if isinstance(src, str) and "logo" in src.lower():
                    logo_tag = img
                    break

        if logo_tag:
            src = logo_tag.get("src")
            logo_url = urllib.parse.urljoin(r["url"], src) if isinstance(src, str) else r["url"]
            md_output.append(f"[![logo]({logo_url})]({r['url']})")
            if site_title_text:
                md_output.append(f" {site_title_text}")
            md_output.append("\n\n")
        elif site_title_text:
            md_output.append(f"# {site_title_text}\n\n")

        # --- 2. Navigation links ---
        nav_links: List[str] = []
        for nav_tag in soup.find_all(["nav", "header", "footer"]):
            if isinstance(nav_tag, Tag):
                for a in nav_tag.find_all("a", href=True):
                    if isinstance(a, Tag):
                        href = a.get("href")
                        if isinstance(href, str):
                            full_url = urllib.parse.urljoin(r["url"], href)
                            text = a.get_text(strip=True)
                            if text and len(text) < 50 and full_url != r["url"] + "#":
                                nav_links.append(f"[{text}]({full_url})")

        if nav_links:
            md_output.append(" ".join(nav_links))
            md_output.append("\n\n")

        # --- 3. Main Content ---
        md_output.append(r["content"])
        md_output.append("\n\n")

        # --- 4. Tech stack ---
        md_output.append(f"**Detected Tech:** {', '.join(r['detected_tech'])}\n\n")

        md_output.append("\n---\n\n")

    return "".join(md_output)


def format_text_output(results: List[Dict]) -> str:
    text_output = []
    for r in results:
        text_output.append(f"URL: {r['url']}\n") # Added newline
        text_output.append(f"Detected Tech: {', '.join(r['detected_tech'])}\n") # Added newline
        text_output.append("\nContent:\n")
        text_output.append(r['content'])
        text_output.append("\n\n---\n\n") # Added newlines
    text_string = "\n".join(text_output)
    # Add extra newline after each line (excluding the content block)
    # This might be too much spacing, let's revert to adding spacing between sections like markdown
    text_output_spaced = []
    for r in results:
        text_output_spaced.append(f"URL: {r['url']}\n\n")
        text_output_spaced.append(f"Detected Tech: {', '.join(r['detected_tech'])}\n\n")
        text_output_spaced.append("Content:\n\n")
        text_output_spaced.append(r['content'])
        text_output_spaced.append("\n\n---\n\n")
    return "".join(text_output_spaced)

def format_ai_response_output(results: List[Dict]) -> str:
     # Placeholder for AI summarization or analysis
    return "AI response not yet implemented."
