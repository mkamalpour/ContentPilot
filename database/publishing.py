"""Explicit WordPress delivery; database inserts never trigger HTTP requests."""

import requests
import bleach
import markdown
from core import config


def wordpress_configured():
    return all(
        [config.WORDPRESS_API_URL, config.WORDPRESS_USERNAME, config.WORDPRESS_PASSWORD]
    )


def beautify_content(raw_text):
    html = markdown.markdown(raw_text or "", extensions=["extra"])
    return bleach.clean(
        html,
        tags={
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "blockquote",
            "pre",
            "code",
            "a",
            "hr",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
        },
        attributes={"a": ["href", "title"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )


def create_wordpress_post_data(title, content, status="draft"):
    if status not in {"draft", "publish"}:
        raise ValueError("WordPress status must be draft or publish")
    return {"title": title, "content": beautify_content(content), "status": status}


def publish_content(content, status="draft"):
    if not wordpress_configured():
        raise ValueError(
            "Configure the WordPress URL, username and application password first"
        )
    with requests.Session() as client:
        client.trust_env = False
        url = config.WORDPRESS_API_URL.rstrip("/")
        if content.wordpress_id:
            url += f"/{content.wordpress_id}"
        response = client.post(
            url,
            auth=(config.WORDPRESS_USERNAME, config.WORDPRESS_PASSWORD),
            json=create_wordpress_post_data(content.topic, content.body, status),
            timeout=(5, 30),
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code not in {200, 201}:
            raise ValueError("WordPress returned an unexpected response")
        data = response.json()
        if not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] <= 0:
            raise ValueError('WordPress did not return a valid positive post ID; local content is preserved')
        returned_status = data.get('status', status)
        if not isinstance(returned_status, str) or returned_status not in {'draft', 'publish', 'pending', 'future', 'private', 'trash'}:
            raise ValueError('WordPress returned an invalid post status; review delivery before retrying')
        return {
            "id": data["id"],
            "url": data.get("link", ""),
            "status": returned_status,
        }
