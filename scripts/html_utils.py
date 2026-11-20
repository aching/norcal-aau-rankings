"""Context-aware escaping helpers for generated static HTML."""
import html
import json
from urllib.parse import urlsplit


def esc(value):
    """Escape text for HTML text nodes and quoted attribute values."""
    return html.escape(str(value), quote=True)


def safe_url(value):
    """Return an absolute HTTP(S) URL, or an empty string when unsafe."""
    url = str(value or "").strip()
    if not url or any(ord(c) < 32 or ord(c) == 127 for c in url):
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def external_link(url, text):
    """Render a safe external link, falling back to escaped plain text."""
    url = safe_url(url)
    if not url:
        return esc(text)
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def json_for_script(value):
    """Serialize JSON without letting data terminate an inline script."""
    return (json.dumps(value)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))
