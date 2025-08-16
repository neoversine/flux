from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import urllib.parse
import re
from typing import Set

# --------------------------
# Scraping functions
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
        page = browser.new_page()
        queue = [start_url]

        while queue and len(visited) < max_pages:
            current_url = queue.pop(0)
            if current_url in visited:
                continue

            try:
                page.goto(current_url, timeout=15000)
                page.wait_for_load_state('networkidle')
                html = page.content()
                visited.add(current_url)

                text = get_text_from_html(html)
                results.append(f"## {current_url}\n\n{text}")

                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    full_url = urllib.parse.urljoin(base_domain, href)
                    if is_valid_link(href) and full_url not in visited and len(queue) + len(visited) < max_pages:
                        queue.append(full_url)

            except Exception as e:
                results.append(f"Error fetching {current_url}: {e}")

        browser.close()

    return "\n\n---\n\n".join(results)
