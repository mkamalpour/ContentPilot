"""Bounded public-web requests with validation on every redirect."""

import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin
import requests
from scraper.utils import clean_html

MAX_BYTES = 2 * 1024 * 1024


class ScrapeError(ValueError):
    pass


def validate_url(url):
    try:
        parsed = urlsplit(str(url).strip())
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def validate_public_url(url):
    if not validate_url(url):
        raise ScrapeError("Enter an HTTP or HTTPS URL without embedded credentials")
    parsed = urlsplit(url)
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, ValueError) as exc:
        raise ScrapeError("The source hostname could not be resolved") from exc
    if not addresses or any(
        not ipaddress.ip_address(row[4][0]).is_global for row in addresses
    ):
        raise ScrapeError("Source URLs must resolve to public internet addresses")
    return url


def make_request(url, headers=None):
    deadline = time.monotonic() + 40
    with requests.Session() as client:
        client.trust_env = False
        client.headers.update(
            headers
            or {
                "User-Agent": "ContentPilot/1.0 (+research and drafting)",
                "Accept": "text/html,application/xhtml+xml,text/plain",
            }
        )
        for _ in range(6):
            if time.monotonic() >= deadline:
                raise ScrapeError('The source exceeded the request time limit')
            validate_public_url(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScrapeError('The source exceeded the request time limit')
            with client.get(
                url, timeout=(min(5, remaining), min(20, remaining)), allow_redirects=False, stream=True
            ) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise ScrapeError("The source returned an invalid redirect")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                media = (
                    response.headers.get("Content-Type", "text/html")
                    .split(";", 1)[0]
                    .lower()
                )
                if media not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    raise ScrapeError("The source must be an HTML or text page")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES or time.monotonic() > deadline:
                        raise ScrapeError(
                            "The source exceeds the download size or time limit"
                        )
                    chunks.append(chunk)
                response._content = b"".join(chunks)
                response._content_consumed = True
                return response
    raise ScrapeError("The source redirected too many times")


def scrape_url(url):
    try:
        response = make_request(str(url))
        result = clean_html(response.text)
        if not result.strip():
            raise ScrapeError("No readable article text was found on this page")
        return result
    except requests.RequestException as exc:
        raise ScrapeError(
            "The source could not be downloaded. Check the URL and try again."
        ) from exc
