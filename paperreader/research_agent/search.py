"""External discovery providers. Evidence levels describe what was retrieved."""
import json
from urllib.parse import quote_plus, urlsplit

from paperreader.services.lazy import httpx, keyring

SEARCH_ACCOUNTS = {"Bright Data": "search-brightdata", "OpenAlex": "search-openalex"}
BRIGHTDATA_ZONE_ACCOUNT = "search-brightdata-serp-zone"
SEARCH_ENGINES = {"bing": "Bing", "google": "Google"}


def search_key(provider):
    try:
        return keyring.get_password("PaperReader", SEARCH_ACCOUNTS[provider]) or ""
    except keyring.errors.KeyringError:
        return ""


def brightdata_zone():
    try:
        return keyring.get_password("PaperReader", BRIGHTDATA_ZONE_ACCOUNT) or ""
    except keyring.errors.KeyringError:
        return ""


def search_web(query, *, start=0, engine="bing"):
    if engine not in SEARCH_ENGINES:
        raise ValueError("不支持的 Bright Data 搜索引擎")
    key = search_key("Bright Data")
    if not key:
        raise ValueError("未配置 Bright Data API Key")
    zone = brightdata_zone()
    if not zone:
        raise ValueError("未配置 Bright Data SERP Zone")
    url = f"https://www.{engine}.com/search?q={quote_plus(query)}&brd_json=1"
    if start:
        url += f"&{'first' if engine == 'bing' else 'start'}={start + 1 if engine == 'bing' else start}"
    response = httpx.post(
        "https://api.brightdata.com/request",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"zone": zone, "url": url, "format": "json"},
        timeout=90,
    )
    response.raise_for_status()
    try:
        payload = response.json()
        if "body" in payload:
            if payload.get("status_code") != 200:
                raise ValueError(f"Bright Data 搜索失败（HTTP {payload.get('status_code')}）")
            payload = json.loads(payload["body"])
        organic = payload["organic"]
        if not isinstance(organic, list):
            raise ValueError("Bright Data 搜索结果格式异常")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Bright Data 未返回有效的搜索结果") from exc
    results = []
    for item in organic[:10]:
        if not isinstance(item, dict):
            continue
        target = item.get("link") or item.get("url")
        title = item.get("title")
        if not isinstance(target, str) or not isinstance(title, str) or not title.strip():
            continue
        parsed = urlsplit(target)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        results.append(dict(kind="web", id=target, url=target, title=title,
                            level="搜索摘要", text=item.get("description") or item.get("snippet") or ""))
    return results


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


def retrieve_web_evidence(query, limit, emit, *, search=search_web, read=read_public_source):
    """Read five SERP hits, extending to ten only when fewer than three yield original text."""
    limit.check()
    candidates = search(query)
    seen = set()
    unique = []
    for item in candidates:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    results = []
    for item in unique[:5]:
        limit.check()
        results.append(read(item, query, limit))
    valid = sum(item.get("level") == "原文" and bool(item.get("text")) for item in results)
    if valid >= 3:
        emit("trace", f"网页检索 · 前 {len(results)} 页读取到 {valid} 条原文")
        return results
    emit("trace", f"网页检索 · 前 {len(results)} 页仅 {valid} 条有效原文，扩展至前 10 页")
    if len(unique) < 10:
        limit.check()
        try:
            for item in search(query, start=10):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    unique.append(item)
                if len(unique) >= 10:
                    break
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            emit("trace", "网页检索 · 补充结果暂不可用，继续使用已取得的网页")
    for item in unique[5:10]:
        limit.check()
        results.append(read(item, query, limit))
    emit("trace", f"网页检索 · 共读取 {len(results)} 页，获得 "
         f"{sum(item.get('level') == '原文' and bool(item.get('text')) for item in results)} 条原文")
    return results
