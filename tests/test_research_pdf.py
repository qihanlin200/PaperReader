import unittest
from unittest.mock import patch

import httpx
import fitz

from paperreader.services.research_pdf import PDFDownloadBlocked, download_citation_pdf, page_pdf_links


class ResearchPDFTests(unittest.TestCase):
    def test_relative_links_metadata_viewer_and_json(self):
        html = """
        <base href="/article/">
        <meta name="citation_pdf_url" content="../files/full.pdf?x=1&amp;y=2">
        <iframe src="viewer/pdf?id=42"></iframe>
        <a href="download?id=42"><span>Download PDF</span></a>
        <script>{"pdfUrl":"/files/other.pdf"}</script>
        <a href="javascript:alert(1)">PDF</a>
        """
        self.assertEqual(page_pdf_links(html, "https://publisher.test/paper/42"), [
            "https://publisher.test/files/full.pdf?x=1&y=2",
            "https://publisher.test/article/viewer/pdf?id=42",
            "https://publisher.test/files/other.pdf",
            "https://publisher.test/article/download?id=42",
        ])

    def test_redirected_page_source_to_pdf_with_referer(self):
        with fitz.open() as document:
            document.new_page()
            data = document.tobytes()
        requests = []

        def serve(request):
            requests.append(request)
            if request.url.host == "doi.org":
                return httpx.Response(302, headers={"Location": "https://publisher.test/article/42"})
            if request.url.path == "/article/42":
                return httpx.Response(200, headers={"Content-Type": "text/html"},
                                      text='<meta name="citation_pdf_url" content="/download/42">')
            if request.url.path == "/download/42":
                self.assertEqual(request.headers["Referer"], "https://publisher.test/article/42")
                return httpx.Response(200, content=data, headers={"Content-Type": "application/pdf"})
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(serve), follow_redirects=True)
        with patch("paperreader.services.research_pdf.httpx.Client", return_value=client):
            result = download_citation_pdf({
                "id": "10.1234/demo", "url": "https://doi.org/10.1234/demo",
                "pdf_urls": ["https://doi.org/10.1234/demo"],
            })
        self.assertEqual(result, data)
        self.assertEqual(len(requests), 3)

    def test_unavailable_pdf_returns_none(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>No full text available</html>",
                                           headers={"Content-Type": "text/html"})))
        with patch("paperreader.services.research_pdf.httpx.Client", return_value=client):
            self.assertIsNone(download_citation_pdf({
                "id": "10.1234/demo", "url": "https://doi.org/10.1234/demo",
                "pdf_urls": ["https://publisher.test/article/42"],
            }))


    def test_extensionless_publisher_download_buttons(self):
        page = """
        <button onclick="window.open('/frontend/manuscript/abc123/download_pub')">Download</button>
        <a href="Delivery.cfm?abstractid=6796558&amp;mirid=1">Download this paper</a>
        <button data-pdf-url="/content/6796558">Read</button>
        """
        self.assertEqual(page_pdf_links(page, "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6796558"), [
            "https://papers.ssrn.com/frontend/manuscript/abc123/download_pub",
            "https://papers.ssrn.com/content/6796558",
            "https://papers.ssrn.com/sol3/Delivery.cfm?abstractid=6796558&mirid=1",
        ])

    def test_access_denied_is_reported_distinctly(self):
        client = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html><title>Access Denied</title></html>",
                                           headers={"Content-Type": "text/html"})))
        with patch("paperreader.services.research_pdf.httpx.Client", return_value=client):
            with self.assertRaises(PDFDownloadBlocked):
                download_citation_pdf({
                    "id": "10.1234/demo", "url": "https://www.preprints.org/manuscript/202608.0199",
                    "pdf_urls": ["https://www.preprints.org/manuscript/202608.0199"],
                })
