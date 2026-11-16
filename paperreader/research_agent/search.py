"""External discovery providers. Evidence levels describe what was retrieved."""
from paperreader.services.lazy import httpx, keyring

SEARCH_ACCOUNTS = {"Brave Search": "search-brave", "OpenAlex": "search-openalex"}


def search_key(provider):
    try:
        return keyring.get_password("PaperReader", SEARCH_ACCOUNTS[provider]) or ""
    except keyring.errors.KeyringError:
        return ""


def search_web(query):
    key = search_key("Brave Search")
    if not key:
        raise ValueError("未配置 Brave Search API Key")
    response = httpx.get("https://api.search.brave.com/res/v1/web/search",
                         headers={"X-Subscription-Token": key}, params={"q": query, "count": 6}, timeout=8)
    response.raise_for_status()
    return [dict(kind="web", id=item["url"], url=item["url"], title=item["title"],
                 level="搜索摘要", text=item.get("description", ""))
            for item in response.json().get("web", {}).get("results", [])
            if item.get("url") and item.get("title")]


def search_openalex(query):
    key = search_key("OpenAlex")
    if not key:
        return []
    response = httpx.get("https://api.openalex.org/works", timeout=8,
                         params={"api_key": key, "search": query, "per-page": 5})
    response.raise_for_status()
    entries = []
    for item in response.json().get("results", []):
        title, url = item.get("title"), item.get("doi") or item.get("id")
        if not title or not url:
            continue
        inverted = item.get("abstract_inverted_index") or {}
        words = sorted((position, word) for word, positions in inverted.items() for position in positions)
        pdf = (item.get("best_oa_location") or {}).get("pdf_url")
        entries.append(dict(kind="academic", id=url.removeprefix("https://doi.org/"), title=title,
                            url=url, pdf_urls=[pdf] if pdf else [],
                            level="摘要" if words else "题录",
                            text=" ".join(word for _, word in words)[:6000] or
                                 str(item.get("publication_year") or "")))
    return entries


def read_public_source(entry, query, limit):
    """Read a bounded public page or open PDF, retaining discovery metadata on failure."""
    from html.parser import HTMLParser
    from ipaddress import ip_address
    from socket import getaddrinfo
    from urllib.parse import urlsplit

    from paperreader.services.lazy import fitz
    from paperreader.services.retrieval import terms

    class PageText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "head", "nav", "footer"):
                self.hidden += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style", "head", "nav", "footer"):
                self.hidden = max(0, self.hidden - 1)

        def handle_data(self, data):
            if not self.hidden and len(data.strip()) >= 45:
                self.parts.append(" ".join(data.split()))

    urls = entry.get("pdf_urls", []) if entry["kind"] == "academic" else [entry["url"]]
    if not urls:
        return entry
    url = urls[0]
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            return entry
        if parsed.port not in (None, 80, 443):
            return entry
        if not all(ip_address(record[4][0]).is_global
                   for record in getaddrinfo(parsed.hostname, parsed.port or 443)):
            return entry
        limit.check()
        with httpx.stream("GET", url, timeout=4, follow_redirects=False, trust_env=False) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                limit.check()
                data.extend(chunk)
                if len(data) > 6_000_000:
                    return entry
            encoding = response.encoding or "utf-8"
        if data.startswith(b"%PDF"):
            with fitz.open(stream=bytes(data), filetype="pdf") as document:
                passages = [(page + 1, " ".join(document[page].get_text().split()))
                            for page in range(min(24, len(document)))]
        elif entry["kind"] == "web":
            parser = PageText()
            parser.feed(data.decode(encoding, errors="replace"))
            passages = [(None, part) for part in parser.parts]
        else:
            return entry
    except (httpx.HTTPError, OSError, ValueError, RuntimeError, LookupError):
        return entry
    keywords = set(terms(query))
    ranked = []
    for page, passage in passages:
        for offset in range(0, min(len(passage), 20_000), 650):
            excerpt = passage[offset:offset + 800]
            score = len(keywords.intersection(terms(excerpt)))
            if score:
                ranked.append((score, page, excerpt))
    if not ranked:
        return entry
    ranked.sort(key=lambda item: item[0], reverse=True)
    excerpts = [f"第 {page} 页：{excerpt}" if page else excerpt for _, page, excerpt in ranked[:2]]
    return dict(entry, level="原文", text="\n\n".join(excerpts), original_url=url)
