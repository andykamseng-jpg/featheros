"""Small, bounded web search and browser launch tools for the local agent."""
from html.parser import HTMLParser
import ipaddress
import socket
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
import urllib.request
import webbrowser


SEARCH_URL = "https://html.duckduckgo.com/html/?q="
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PAGE_TEXT = 12000


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title_parts = []
        self.skip_depth = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if not self.skip_depth and tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript", "svg", "template"} and self.skip_depth:
            self.skip_depth -= 1
        if not self.skip_depth and tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if not self.skip_depth:
            self.parts.append(data)


def _validate_public_https_url(url):
    parsed = urlparse(str(url or "").strip())
    host = parsed.hostname
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password or
            host == "localhost" or host.endswith((".localhost", ".local"))):
        raise ValueError("Read only public HTTPS pages")
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0])
                         for info in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)]
        except (OSError, ValueError) as exc:
            raise ValueError("The page host could not be resolved safely") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Read only public HTTPS pages")
    return url


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        target = urljoin(request.full_url, newurl)
        _validate_public_https_url(target)
        return super().redirect_request(request, response, code, message, headers, target)


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


def fetch_page(url):
    """Read a small public HTTPS page as text; never send cookies or credentials."""
    url = _validate_public_https_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "FeatherOS/0.6 (local user requested page read)",
                                                   "Accept": "text/html,text/plain;q=0.9"})
    opener = urllib.request.build_opener(_PublicRedirectHandler())
    with opener.open(request, timeout=15) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
        final_url = response.geturl()
        content_type = response.headers.get_content_type()
    _validate_public_https_url(final_url)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Page exceeds the 1 MiB read limit")
    if content_type not in {"text/html", "text/plain"}:
        raise ValueError("This first page reader supports HTML and plain text only")
    parser = _PageText()
    parser.feed(data.decode("utf-8", "replace"))
    title = " ".join(" ".join(parser.title_parts).split())[:240]
    text = " ".join(" ".join("".join(parser.parts).split()).split())[:MAX_PAGE_TEXT]
    return {"url": final_url, "title": title, "text": text}
