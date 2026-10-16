"""Extract readable article text without duplicating nested content containers."""

from bs4 import BeautifulSoup


def clean_html(html, max_sentences=100):
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.select(
        "script,style,nav,footer,header,aside,noscript,form,svg,button"
    ):
        element.decompose()
    article = soup.find("article") or soup.find("main") or soup.body or soup
    lines = [
        " ".join(line.split())
        for line in article.get_text("\n", strip=True).splitlines()
    ]
    # Keep original order; only remove repeated boilerplate lines.
    seen, result = set(), []
    for line in lines:
        if line and line not in seen:
            seen.add(line)
            result.append(line)
    return "\n\n".join(result)[:50000]
