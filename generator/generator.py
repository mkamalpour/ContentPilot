"""Article generation with optional source grounding in a single model request."""

from core.llm import build_prompt, generate_text


def generate_content(topic, source_text=None, source_url=None):
    topic = str(topic).strip()
    if not topic:
        raise ValueError("A topic is required")
    return generate_text(build_prompt(topic, source_text, source_url))


def generate_content_with_prompt(topic, custom_prompt):
    if not str(topic).strip() or not str(custom_prompt).strip():
        raise ValueError("Topic and prompt are required")
    return generate_text(custom_prompt)


def validate_generated_content(content):
    return isinstance(content, str) and bool(content.strip())
