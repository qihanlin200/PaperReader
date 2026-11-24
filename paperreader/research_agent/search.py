"""External discovery providers. Evidence levels describe what was retrieved."""
import json
import re
from time import monotonic
from urllib.parse import quote_plus, urlsplit

from paperreader.services.lazy import httpx, keyring
from paperreader.logger import get_logger, preview, response_size


log = get_logger(__name__)

SEARCH_ACCOUNTS = {"Bright Data": "search-brightdata"}
BRIGHTDATA_ZONE_ACCOUNT = "search-brightdata-serp-zone"
SEARCH_ENGINES = {"bing": "Bing", "google": "Google"}


def _source_label(url):
    """Keep diagnostic addresses useful without recording URL query credentials."""
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return "无效地址"
    return f"{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path or "未知地址"


def _safe_error_message(exc):
    message = str(exc)
    message = re.sub(r"https?://[^\s'\"<>]+", lambda match: _source_label(match.group()), message)
    return preview(message, 200)


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
    started = monotonic()
    log.info("网页搜索请求：Bright Data，搜索引擎 {}，起点 {}，查询 {}", engine, start, preview(query, 200))
    response = httpx.post(
        "https://api.brightdata.com/request",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"zone": zone, "url": url, "format": "json"},
        timeout=90,
    )
    log.info("网页搜索 HTTP 响应：{}，{} 字节，用时 {:.2f} 秒", response.status_code,
             response_size(response), monotonic() - started)
    if type(response.status_code) is int and response.status_code >= 400:
        log.warning("Bright Data 网页搜索返回 HTTP {}", response.status_code)
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
    log.info("网页搜索返回：{} 条；前 3 项 {}", len(results),
             [preview(item["title"], 100) for item in results[:3]])
    for rank, item in enumerate(results, start=1):
        log.debug("网页搜索候选：第 {} 条，站点 {}，标题 {}", rank,
                  urlsplit(item["url"]).hostname, preview(item["title"], 160))
    return results


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
        log.warning("公开资料未读取：没有可用原文地址，来源 {}，标题 {}", entry["kind"],
                    preview(entry.get("title", ""), 100))
        return entry
    url = urls[0]
    started = monotonic()
    parsed = None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            log.warning("公开资料未读取：地址格式或凭证不受支持，地址 {}", _source_label(url))
            return entry
        if parsed.port not in (None, 80, 443):
            log.warning("公开资料未读取：端口不受支持，地址 {}，端口 {}", _source_label(url), parsed.port)
            return entry
        if not all(ip_address(record[4][0]).is_global
                   for record in getaddrinfo(parsed.hostname, parsed.port or 443)):
            log.warning("公开资料未读取：目标解析到非公网地址，地址 {}", _source_label(url))
            return entry
        limit.check()
        log.info("公开资料请求 GET {}{}，来源 {}", parsed.netloc, parsed.path, entry["kind"])
        with httpx.stream("GET", url, timeout=4, follow_redirects=False, trust_env=False) as response:
            log.info("公开资料 HTTP 响应：{}，类型 {}", response.status_code,
                     response.headers.get("content-type", ""))
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                limit.check()
                data.extend(chunk)
                if len(data) > 6_000_000:
                    log.warning("公开资料未读取：响应超过 6000000 字节，地址 {}", _source_label(url))
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
            log.warning("公开资料未读取：学术来源不是 PDF，地址 {}，类型 {}", _source_label(url),
                        response.headers.get("content-type", ""))
            return entry
    except (httpx.HTTPError, OSError, ValueError, RuntimeError, LookupError) as exc:
        if isinstance(exc, httpx.HTTPStatusError):
            failed = exc.response
            log.warning("公开资料读取失败：HTTP {} {}，地址 {}，跳转地址 {}，用时 {:.2f} 秒",
                        failed.status_code, failed.reason_phrase, _source_label(failed.url),
                        _source_label(failed.headers.get("location")) if failed.headers.get("location") else "无",
                        monotonic() - started)
        else:
            log.warning("公开资料读取失败：{}，地址 {}，详情 {}，用时 {:.2f} 秒",
                        type(exc).__name__, _source_label(url), _safe_error_message(exc),
                        monotonic() - started)
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
        log.warning("公开资料未读取：已获取页面但未找到与查询匹配的段落，地址 {}，提取段落 {}，用时 {:.2f} 秒",
                    _source_label(url), len(passages), monotonic() - started)
        return entry
    ranked.sort(key=lambda item: item[0], reverse=True)
    excerpts = [f"第 {page} 页：{excerpt}" if page else excerpt for _, page, excerpt in ranked[:2]]
    result = dict(entry, level="原文", text="\n\n".join(excerpts), original_url=url)
    log.info("公开资料返回：{} 字节，{} 段原文，用时 {:.2f} 秒", len(data), len(excerpts),
             monotonic() - started)
    return result


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
