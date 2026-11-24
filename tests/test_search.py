"""Bright Data SERP request and result mapping."""
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QUrl

from paperreader.research_agent.operations import RunLimit
from paperreader.research_agent.search import read_public_source, retrieve_web_evidence, search_web
from paperreader.research_agent.workflow import execute
from paperreader.ui.research import ResearchWorkspace


class SearchTests(unittest.TestCase):
    def test_public_source_http_status_logs_status_and_safe_redirect(self):
        import httpx

        url = "https://example.org/article?token=secret"
        response = httpx.Response(403, headers={"location": "https://example.org/login?key=private"},
                                  request=httpx.Request("GET", url))
        entry = dict(kind="web", url=url, title="Example", level="搜索摘要", text="Summary")
        with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.215.14", 443))]), \
             patch("paperreader.research_agent.search.httpx.stream", return_value=nullcontext(response)), \
             patch("paperreader.research_agent.search.log") as log:
            result = read_public_source(entry, "example", RunLimit())

        self.assertIs(result, entry)
        message = log.warning.call_args.args[0].format(*log.warning.call_args.args[1:])
        self.assertIn("HTTP 403", message)
        self.assertIn("example.org/article", message)
        self.assertIn("example.org/login", message)
        self.assertNotIn("secret", message)
        self.assertNotIn("private", message)

    def test_brightdata_serp_results_become_web_evidence(self):
        response = Mock()
        response.json.return_value = {"status_code": 200, "body": json.dumps({"organic": [
            {"link": "https://example.org/one", "title": "First", "description": "Summary"},
            {"link": "https://example.org/untitled"},
            {"link": "https://example.org/two", "title": "Second"},
        ]})}
        post = Mock(return_value=response)
        with patch("paperreader.research_agent.search.search_key", return_value="test-key"), \
             patch("paperreader.research_agent.search.brightdata_zone", return_value="test-zone"), \
             patch("paperreader.research_agent.search.httpx", SimpleNamespace(post=post)):
            results = search_web("学术 研究")

        response.raise_for_status.assert_called_once_with()
        self.assertEqual(post.call_args.args, ("https://api.brightdata.com/request",))
        self.assertEqual(post.call_args.kwargs["json"], {
            "zone": "test-zone", "url": "https://www.bing.com/search?q=%E5%AD%A6%E6%9C%AF+%E7%A0%94%E7%A9%B6&brd_json=1",
            "format": "json",
        })
        self.assertEqual([(item["url"], item["text"]) for item in results], [
            ("https://example.org/one", "Summary"),
            ("https://example.org/two", ""),
        ])

    def test_brightdata_requires_key_and_zone(self):
        with patch("paperreader.research_agent.search.search_key", return_value=""):
            with self.assertRaisesRegex(ValueError, "API Key"):
                search_web("test")

    def test_google_engine_uses_google_serp_and_page_offset(self):
        response = Mock()
        response.json.return_value = {"status_code": 200, "body": json.dumps({"organic": [
            {"link": "https://example.org/google", "title": "Google result", "snippet": "Excerpt"},
        ]})}
        post = Mock(return_value=response)
        with patch("paperreader.research_agent.search.search_key", return_value="test-key"), \
             patch("paperreader.research_agent.search.brightdata_zone", return_value="test-zone"), \
             patch("paperreader.research_agent.search.httpx", SimpleNamespace(post=post)):
            results = search_web("research agents", start=10, engine="google")
        self.assertEqual(post.call_args.kwargs["json"]["url"],
                         "https://www.google.com/search?q=research+agents&brd_json=1&start=10")
        self.assertEqual(results[0]["text"], "Excerpt")

    def test_bing_second_page_uses_first_parameter(self):
        response = Mock()
        response.json.return_value = {"organic": []}
        post = Mock(return_value=response)
        with patch("paperreader.research_agent.search.search_key", return_value="test-key"), \
             patch("paperreader.research_agent.search.brightdata_zone", return_value="test-zone"), \
             patch("paperreader.research_agent.search.httpx", SimpleNamespace(post=post)):
            search_web("test", start=10)
        self.assertIn("&first=11", post.call_args.kwargs["json"]["url"])

    def test_workflow_uses_run_search_engine(self):
        run = {"workflow": {}, "evidence": [], "scanned": 0, "academic": False,
               "paper_search": False, "web_search": True, "search_engine": "google",
               "question": "research agents", "history": "", "plan": "", "query": "research agents"}
        captured = []

        def web_evidence(query, limit, emit, *, search):
            search("test", start=10)
            return []

        def model(config, key, messages, on_chunk=None, *, cancel=None):
            if "domain_skills（" in messages[0]["content"]:
                return '{"mode":"chat","source":"model"}'
            return "完成。"

        with patch("paperreader.research_agent.workflow.retrieve_web_evidence", side_effect=web_evidence), \
             patch("paperreader.research_agent.workflow.search_web",
                   side_effect=lambda query, **kwargs: captured.append(kwargs) or []):
            execute(run, [], {"model": "fake"}, "", "dark", RunLimit(),
                    lambda *args: None, model=model, academic=lambda query: [])
        self.assertEqual(captured, [{"engine": "google", "start": 10}])
        with patch("paperreader.research_agent.search.search_key", return_value="test-key"), \
             patch("paperreader.research_agent.search.brightdata_zone", return_value=""):
            with self.assertRaisesRegex(ValueError, "SERP Zone"):
                search_web("test")

    def test_brightdata_inner_error_is_not_treated_as_empty_results(self):
        response = Mock()
        response.json.return_value = {"status_code": 403, "body": ""}
        with patch("paperreader.research_agent.search.search_key", return_value="test-key"), \
             patch("paperreader.research_agent.search.brightdata_zone", return_value="test-zone"), \
             patch("paperreader.research_agent.search.httpx", SimpleNamespace(post=Mock(return_value=response))):
            with self.assertRaisesRegex(ValueError, "HTTP 403"):
                search_web("test")

    def test_web_search_stops_at_five_when_three_pages_have_original_text(self):
        pages = [dict(id=str(i), kind="web", level="搜索摘要", text="snippet") for i in range(10)]
        calls = []

        def read(item, query, limit):
            calls.append(item["id"])
            return dict(item, level="原文") if int(item["id"]) < 3 else item

        results = retrieve_web_evidence("question", Mock(), lambda *args: None,
                                        search=lambda query: pages, read=read)
        self.assertEqual(calls, [str(i) for i in range(5)])
        self.assertEqual(len(results), 5)

    def test_web_search_extends_to_ten_when_original_text_is_scarce(self):
        pages = [dict(id=str(i), kind="web", level="搜索摘要", text="snippet") for i in range(10)]
        calls = []

        def read(item, query, limit):
            calls.append(item["id"])
            return dict(item, level="原文") if item["id"] == "0" else item

        results = retrieve_web_evidence("question", Mock(), lambda *args: None,
                                        search=lambda query: pages, read=read)
        self.assertEqual(calls, [str(i) for i in range(10)])
        self.assertEqual(len(results), 10)

    def test_failed_second_serp_page_keeps_first_page_evidence(self):
        pages = [dict(id=str(i), kind="web", level="搜索摘要", text="snippet") for i in range(7)]

        def search(query, *, start=0):
            if start:
                raise ValueError("second page unavailable")
            return pages

        results = retrieve_web_evidence("question", Mock(), lambda *args: None,
                                        search=search, read=lambda item, *_: item)
        self.assertEqual(len(results), 7)

    def test_both_search_buttons_use_web_and_crossref(self):
        run = {"workflow": {}, "evidence": [], "scanned": 0, "academic": True,
               "paper_search": True, "web_search": True, "question": "research agents",
               "history": "", "plan": "", "query": "research agents"}
        web = dict(id="https://example.org/web", url="https://example.org/web", kind="web",
                   title="Web", text="web evidence", level="原文")
        paper = dict(id="paper", url="https://example.org/paper", kind="academic",
                     title="Paper", text="paper evidence", level="题录")
        web_search = Mock(return_value=[web])
        crossref = Mock(return_value=[paper])

        def model(config, key, messages, on_chunk=None, *, cancel=None):
            if "domain_skills（" in messages[0]["content"]:
                return '{"mode":"chat","source":"model"}'
            return "两条来源均已查阅。"

        with patch("paperreader.research_agent.workflow.retrieve_web_evidence", web_search), \
             patch("paperreader.research_agent.workflow.read_public_source", side_effect=lambda item, *_: item):
            status, _ = execute(run, [], {"model": "fake"}, "", "dark", RunLimit(),
                                lambda *args: None, model=model, academic=crossref)
        self.assertEqual(status, "已完成")
        web_search.assert_called_once()
        crossref.assert_called_once()

    def test_web_citation_has_detail_and_source_links_without_showing_url(self):
        workspace = SimpleNamespace(selected=lambda: {"runs": [{"evidence": [
            {"kind": "web", "url": "https://example.org/article"},
            {"kind": "academic", "url": "https://example.org/paper"},
        ]}]})
        self.assertEqual(ResearchWorkspace.citation_href(workspace, 0, 1), "research-content:0-1")
        self.assertEqual(ResearchWorkspace.web_citation_href(workspace, 0, 1), "research-web:0-1")
        self.assertEqual(ResearchWorkspace.citation_href(workspace, 0, 2), "research-content:0-2")
        self.assertEqual(ResearchWorkspace.web_citation_href(workspace, 0, 2), "")
        run = workspace.selected()["runs"][0]
        detail = SimpleNamespace(selected=workspace.selected, content=object(),
                                 show_detail=Mock())
        ResearchWorkspace.open_detail(detail, QUrl("research-content:0-1"))
        detail.show_detail.assert_called_once_with((run, 1, None), detail.content)
        detail.open_detail = Mock()
        ResearchWorkspace.open_pdf(detail, QUrl("research-web:0-1"))
        detail.open_detail.assert_called_once()
