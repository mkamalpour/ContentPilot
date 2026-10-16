"""Small, bounded trend-source adapters; empty upstream results remain visible."""

import random
import time
import requests
from threading import Lock
from bs4 import BeautifulSoup
from scraper.scraper import make_request, ScrapeError

TREND_SOURCES = {
    "explodingtopics": "https://explodingtopics.com/topic",
    "trendaz": "https://www.trend.az/iran/",
}
_cache = {}
_lock = Lock()


def get_trends_from_page(page_num=1, category="featured"):
    response = make_request(
        f"{TREND_SOURCES['explodingtopics']}?page={max(1, min(int(page_num), 3))}"
    )
    soup = BeautifulSoup(response.text, "html.parser")
    nodes = soup.select(
        "div.tileKeyword, .topic-name, .topicInfo h2, h3 a[href*='/topic/'], a[href*='/topic/'] h3"
    )
    return _titles(nodes)


def _titles(nodes):
    titles = []
    for node in nodes:
        title = " ".join(node.get_text(" ", strip=True).split())
        if 3 <= len(title) <= 250 and title not in titles:
            titles.append(title)
    return titles


def get_trends_from_trendaz(num_trends=5):
    response = make_request(TREND_SOURCES["trendaz"])
    soup = BeautifulSoup(response.text, "html.parser")
    return _titles(
        soup.select(
            ".news-title, .article-title, h2 a, h3 a, h4:not([class]), h4[class='']"
        )
    )[:num_trends]


def get_trends(num_trends=10, source="explodingtopics", **kwargs):
    if source not in {*TREND_SOURCES, "all"}:
        raise ValueError("Unknown trend source")
    with _lock:
        cached = _cache.get(source)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1][:num_trends]
    results, failures = [], []
    for name in TREND_SOURCES if source == "all" else [source]:
        try:
            values = (
                get_trends_from_page()
                if name == "explodingtopics"
                else get_trends_from_trendaz(20)
            )
            results.extend(value for value in values if value not in results)
        except (ScrapeError, requests.RequestException, ValueError) as exc:
            failures.append(type(exc).__name__)
    if not results:
        raise ScrapeError(
            "The trend source returned no readable topics. Try another source or enter your own topic."
        )
    with _lock:
        _cache[source] = (time.monotonic(), results)
    return results[:num_trends]


def get_random_trends(num_trends=5, **kwargs):
    return get_trends(num_trends=num_trends)


def get_trend_from_source(source="explodingtopics"):
    return random.choice(get_trends(source=source))
