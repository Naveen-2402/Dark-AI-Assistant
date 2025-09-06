# utils/web_search.py
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    extract: str

def web_search(query: str, max_results: int = 5, extract_chars: int = 900) -> List[SearchResult]:
    """
    Perform a web search using Startpage (HTML scraping).
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://www.startpage.com/sp/search?q={requests.utils.quote(query)}"
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    results: List[SearchResult] = []

    for res in soup.select("a.result-link")[:max_results]:
        title = res.get_text(strip=True)
        href = res.get("href")
        snippet_tag = res.find_parent("div", class_="w-gl__result").select_one(".w-gl__description")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        extract = snippet[:extract_chars]

        if href and href.startswith("http"):
            results.append(SearchResult(title=title, url=href, snippet=snippet, extract=extract))

    return results

def format_results_for_prompt(results: List[SearchResult]) -> str:
    """
    Format search results for inclusion in LLM prompt.
    """
    formatted = []
    for i, r in enumerate(results, start=1):
        block = f"[{i}] {r.title}\nURL: {r.url}\n"
        if r.snippet:
            block += f"Snippet: {r.snippet}\n"
        if r.extract:
            block += f"Extract: {r.extract}\n"
        formatted.append(block.strip())
    return "\n\n".join(formatted)
