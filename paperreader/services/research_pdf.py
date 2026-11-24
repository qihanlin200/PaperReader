"""Resolve and download a readable PDF for an academic citation."""
from collections import deque
from html import unescape
from html.parser import HTMLParser
import re
from time import monotonic
from urllib.parse import quote, urljoin, urlsplit

from .lazy import fitz, httpx
from paperreader.logger import get_logger, preview, response_size


log = get_logger(__name__)

MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_REQUESTS = 10


class PDFDownloadBlocked(RuntimeError):
    """The publisher returned an access restriction or verification page."""


def is_pdf_endpoint(url):
    path = urlsplit(url).path.lower()
    return bool(re.search(
        r"(?:\.pdf(?:$)|/pdf(?:/|$)|/download_pub/?$|(?:^|/)delivery\.cfm(?:/|$))", path)
        or re.search(r"[?&](?:format|type)=pdf(?:&|$)", url, re.I))


def blocked_page(html):
    lowered = html.lower()
    return any(marker in lowered for marker in (
        "<title>access denied", "<title>just a moment", "cf-chl-", "verify you are human",
        "you don't have permission to access", "enable javascript and cookies to continue",
    ))


def pdf_links(item):
    return [
        link["URL"] for link in (item.get("link") or [])
        if isinstance(link, dict) and isinstance(link.get("URL"), str)
        and (str(link.get("content-type", "")).lower().startswith("application/pdf")
             or is_pdf_endpoint(link["URL"]))
    ]


class PDFPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.base = ""
        self.links = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ("data-pdf-url", "data-pdf", "data-download-url", "data-download", "data-url", "data-href"):
            value = attrs.get(name)
            if value:
                self.add(value, priority=1, explicit=name in ("data-pdf-url", "data-pdf", "data-download-url"))
        for value in re.findall(r"""['"]([^'"]+)['"]""", attrs.get("onclick") or ""):
            self.add(value, priority=1)
        if tag == "base" and not self.base:
            self.base = attrs.get("href", "")
        elif tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            if name in ("citation_pdf_url", "wkhealth_pdf_url", "eprints.document_url",
                        "dc.relation", "dc.identifier"):
                self.add(attrs.get("content"), priority=0, explicit="pdf" in name)
        elif tag == "link":
            self.add(attrs.get("href"), priority=1,
                     explicit="application/pdf" in (attrs.get("type") or "").lower())
        elif tag in ("iframe", "embed", "object"):
            self.add(attrs.get("src") or attrs.get("data"), priority=1,
                     explicit="application/pdf" in (attrs.get("type") or "").lower())
        elif tag == "a":
            self.anchor = [attrs.get("href", ""), ""]
            title = " ".join(str(attrs.get(key) or "") for key in ("title", "aria-label", "type"))
            self.add(attrs.get("href"), priority=2, explicit="pdf" in title.lower())

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor[1] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            url, label = self.anchor
            self.add(url, priority=2, explicit="pdf" in label.lower())
            self.anchor = None

    def add(self, url, *, priority, explicit=False):
        if isinstance(url, str) and url.strip():
            if explicit or is_pdf_endpoint(url):
                self.links.append((priority, url.strip()))


def page_pdf_links(html, page_url):
    parser = PDFPageParser()
    parser.feed(html)
    base = urljoin(page_url, parser.base) if parser.base else page_url
    links = list(parser.links)
    # Some PDF viewers declare their source in JSON rather than HTML elements.
    for match in re.finditer(
            r'["\'](?:pdfUrl|pdf_url|pdfDownloadUrl|downloadPdfUrl|download_url|downloadUrl)["\']\s*:\s*["\']([^"\']+)["\']',
            html, re.I):
        value = match[1].replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=")
        links.append((1, value))
    # Download buttons may be defined in script strings instead of anchor tags.
    for match in re.finditer(r"""["']([^"'<>\s]+)["']""", html):
        value = match[1].replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=")
        if is_pdf_endpoint(value):
            links.append((2, value))
    result = []
    seen = set()
    for _, value in sorted(links, key=lambda item: item[0]):
        url = urljoin(base, unescape(value))
        parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname and url not in seen:
            seen.add(url)
            result.append(url)
    return result[:12]


def read_pdf_or_page(response, progress=None):
    content_type = response.headers.get("content-type", "").lower()
    data = bytearray()
    pdf = False
    reported = 0
    total = response.headers.get("content-length", "")
    for chunk in response.iter_bytes(chunk_size=8192):
        data.extend(chunk)
        pdf = b"%PDF-" in data[:1024]
        limit = MAX_PDF_BYTES if pdf else MAX_HTML_BYTES
        if pdf and progress and (not reported or len(data) - reported >= 256 * 1024):
            reported = len(data)
            progress(reported, int(total) if total.isdigit() else 0)
        if len(data) > limit:
            return None, []
        if not pdf and ("image/" in content_type or "application/zip" in content_type):
            return None, []
    if pdf:
        try:
            with fitz.open(stream=data, filetype="pdf") as document:
                if len(document) and not document.needs_pass:
                    return bytes(data), []
        except (RuntimeError, ValueError, OSError):
            return None, []
    if "html" in content_type or b"<html" in data[:2048].lower() or b"<!doctype html" in data[:2048].lower():
        encoding = response.encoding or "utf-8"
        try:
            html = data.decode(encoding, errors="replace")
        except LookupError:
            html = data.decode("utf-8", errors="replace")
        if blocked_page(html):
            raise PDFDownloadBlocked()
        return None, page_pdf_links(html, str(response.url))
    return None, []


def download_citation_pdf(source, *, progress=None):
    doi = source["id"]
    candidates = list(source.get("pdf_urls", []))
    log.info("引文 PDF 获取开始：{}，候选 {} 条", preview(doi, 120), len(candidates))
    if doi.lower().startswith("10.48550/arxiv."):
        candidates.insert(0, "https://arxiv.org/pdf/" + quote(doi[len("10.48550/arxiv."):], safe="/"))
    with httpx.Client(timeout=5, follow_redirects=True, max_redirects=5) as client:
        if not candidates:
            try:
                started = monotonic()
                log.info("引文元数据请求：Crossref {}", preview(doi, 120))
                response = client.get("https://api.crossref.org/works/" + quote(doi, safe="/"))
                log.info("引文元数据 HTTP 响应：{}，{} 字节，用时 {:.2f} 秒",
                         response.status_code, response_size(response), monotonic() - started)
                if type(response.status_code) is int and response.status_code >= 400:
                    log.warning("引文元数据返回 HTTP {}", response.status_code)
                response.raise_for_status()
                candidates.extend(pdf_links(response.json()["message"]))
                log.info("引文元数据返回：{} 条 PDF 候选", len(candidates))
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                log.warning("引文元数据获取失败：{}", type(exc).__name__)
                pass
        candidates = list(dict.fromkeys(candidates))[:3]
        pending = deque((url, "", 0) for url in dict.fromkeys([*candidates, source["url"]]))
        visited = set()
        blocked = False
        while pending and len(visited) < MAX_REQUESTS:
            url, referer, depth = pending.popleft()
            if url in visited or urlsplit(url).scheme != "https":
                continue
            visited.add(url)
            headers = {"Accept": "application/pdf, text/html;q=0.9, */*;q=0.5",
                       "User-Agent": "PaperReader/1.0"}
            if referer:
                headers["Referer"] = referer
            try:
                started = monotonic()
                parsed = urlsplit(url)
                log.info("引文 PDF 请求 GET {}{}，深度 {}", parsed.netloc, parsed.path, depth)
                with client.stream("GET", url, headers=headers) as response:
                    log.info("引文 PDF HTTP 响应：{}，类型 {}，用时 {:.2f} 秒",
                             response.status_code, response.headers.get("content-type", ""),
                             monotonic() - started)
                    if response.status_code in (401, 403, 429):
                        blocked = True
                    response.raise_for_status()
                    data, discovered = read_pdf_or_page(response, progress)
                    if data is not None:
                        log.info("引文 PDF 返回：{} 字节，来源 {}{}", len(data), parsed.netloc, parsed.path)
                        return data
                    log.info("引文页面返回：发现 {} 条 PDF 链接", len(discovered))
                    if depth < 2:
                        for target in reversed(discovered):
                            if target not in visited:
                                pending.appendleft((target, str(response.url), depth + 1))
            except PDFDownloadBlocked:
                log.warning("引文 PDF 页面访问受限：{}{}", parsed.netloc, parsed.path)
                blocked = True
            except (httpx.HTTPError, RuntimeError, ValueError, OSError) as exc:
                log.warning("引文 PDF 请求失败：{}，{}{}", type(exc).__name__, parsed.netloc, parsed.path)
                continue
        if blocked:
            raise PDFDownloadBlocked()
    log.info("引文 PDF 获取结束：未找到可用文件，已访问 {} 个地址", len(visited))
    return None
