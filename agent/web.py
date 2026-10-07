"""Small, bounded web search and browser launch tools for the local agent."""
from html.parser import HTMLParser
import json
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import urllib.request
import webbrowser


SEARCH_URL = "https://html.duckduckgo.com/html/?q="
MAX_RESPONSE_BYTES = 1024 * 1024


class _SearchResults(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None
        self.collect_title = False
        self.collect_snippet = False

    @staticmethod
    def _classes(attrs):
        return set(dict(attrs).get("class", "").split())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self.current = {"title": "", "url": self._destination(attrs.get("href", "")), "snippet": ""}
            self.collect_title = True
        elif tag in {"a", "div", "td"} and "result__snippet" in classes and self.results:
            self.collect_snippet = True
            self.current = self.results[-1]

    def handle_endtag(self, tag):
        if tag == "a" and self.collect_title:
            if self.current and self.current.get("url"):
                self.results.append(self.current)
            self.current = None
            self.collect_title = False
        if tag in {"a", "div", "td"} and self.collect_snippet:
            self.collect_snippet = False
            self.current = None

    def handle_data(self, data):
        if self.current is None:
            return
        if self.collect_title:
            self.current["title"] += data
        elif self.collect_snippet:
            self.current["snippet"] += data

    @staticmethod
    def _destination(href):
        if not href:
            return ""
        parsed = urlparse(href)
        if parsed.path == "/l/" or parsed.path.endswith("/l/"):
            return parse_qs(parsed.query).get("uddg", [""])[0]
        if parsed.scheme in {"http", "https"}:
            return href
        return ""


def search_web(query):
    query = str(query or "").strip()
    if not query or len(query) > 500:
        raise ValueError("Enter a web search up to 500 characters")
    request = urllib.request.Request(
        SEARCH_URL + quote_plus(query),
        headers={"User-Agent": "FeatherOS/0.6 (local user initiated search)",
                 "Accept": "text/html"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Web search response exceeds size limit")
    parser = _SearchResults()
    parser.feed(data.decode("utf-8", "replace"))
    results = []
    for item in parser.results[:5]:
        url = unquote(item["url"]).strip()
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        results.append({"title": " ".join(item["title"].split())[:240],
                        "url": url[:1500], "snippet": " ".join(item["snippet"].split())[:700]})
    return {"query": query, "results": results}


def open_in_browser(url):
    url = str(url or "").strip()
    parsed = urlparse(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or len(url) > 2000):
        raise ValueError("Use a complete HTTP or HTTPS page address")
    opened = webbrowser.open_new_tab(url)
    return {"opened": bool(opened), "url": url,
            "message": "Opened in the default browser. Feather does not control page clicks or submissions."}
