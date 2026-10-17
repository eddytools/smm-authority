"""Turn raw source payloads into normalised items. Pure functions, no network, no DB."""

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from defusedxml import ElementTree as ET

MAX_ITEMS_PER_SOURCE = 50
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TRACKING = ("utm_", "fbclid", "gclid", "mc_", "ref")


class ParseError(Exception):
    pass


@dataclass
class RawItem:
    url: str
    title: str
    summary: str | None
    author: str | None
    published_at: datetime
    engagement: int = 0


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(_TRACKING)])
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def clean_text(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    text = _WS.sub(" ", html.unescape(_TAGS.sub(" ", value))).strip()
    return text[:limit] or None


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return url if urlparse(url).scheme in ("http", "https") and len(url) <= 1000 else None


def _parse_date(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return min(dt.astimezone(timezone.utc), fallback)  # never in the future


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, *names: str) -> str | None:
    for child in el:
        if _local(child.tag) in names:
            if (child.text or "").strip():
                return child.text
            if _local(child.tag) == "author":  # Atom: <author><name>Bob</name></author>
                nested = _child_text(child, "name")
                if nested:
                    return nested
    return None


def parse_feed(body: bytes, now: datetime) -> list[RawItem]:
    """RSS 2.0 and Atom."""
    try:
        root = ET.fromstring(body)
    except Exception as exc:  # malformed XML, or defusedxml refusing entity tricks
        raise ParseError(f"Not a valid feed ({type(exc).__name__})")
    entries = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    items: list[RawItem] = []
    for el in entries[:MAX_ITEMS_PER_SOURCE]:
        title = clean_text(_child_text(el, "title"), 500)
        link = None
        for child in el:
            if _local(child.tag) == "link":
                if child.get("href") and child.get("rel", "alternate") == "alternate":
                    link = child.get("href")
                    break
                if (child.text or "").strip():
                    link = child.text
                    break
        link = _safe_url(link)
        if not title or not link:
            continue
        items.append(
            RawItem(
                url=link,
                title=title,
                summary=clean_text(_child_text(el, "encoded", "description", "summary", "content"), 600),
                author=clean_text(_child_text(el, "creator", "author"), 200),
                published_at=_parse_date(_child_text(el, "pubDate", "published", "updated", "date"), now),
            )
        )
    if not entries:
        raise ParseError("No items found in feed")
    return items


def parse_reddit(body: bytes, now: datetime) -> list[RawItem]:
    try:
        children = json.loads(body)["data"]["children"]
    except (ValueError, KeyError, TypeError):
        raise ParseError("Unexpected Reddit response")
    items: list[RawItem] = []
    for child in children[:MAX_ITEMS_PER_SOURCE]:
        d = child.get("data", {}) if isinstance(child, dict) else {}
        if d.get("stickied") or d.get("over_18") or not d.get("title") or not d.get("permalink"):
            continue
        created = d.get("created_utc")
        published = datetime.fromtimestamp(created, tz=timezone.utc) if isinstance(created, (int, float)) else now
        items.append(
            RawItem(
                url="https://www.reddit.com" + d["permalink"],
                title=clean_text(d["title"], 500) or "",
                summary=clean_text(d.get("selftext"), 600),
                author=clean_text(d.get("author"), 200),
                published_at=min(published, now),
                engagement=int(d.get("score") or 0) + int(d.get("num_comments") or 0),
            )
        )
    return [i for i in items if i.title]


def build_url(source_type: str, target: str) -> str:
    if source_type == "rss":
        return target
    if source_type == "reddit":
        return f"https://www.reddit.com/r/{target}/hot.json?limit=30&raw_json=1"
    if source_type == "google_news":
        return f"https://news.google.com/rss/search?q={quote_plus(target)}&hl=en-US&gl=US&ceid=US:en"
    raise ValueError(f"unknown source type {source_type}")


def parse_for(source_type: str, body: bytes, now: datetime) -> list[RawItem]:
    return parse_reddit(body, now) if source_type == "reddit" else parse_feed(body, now)
