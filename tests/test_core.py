import tempfile
import unittest
from unittest.mock import patch
import fitz
import httpx
from paperreader.services.library import Library
from paperreader.services.network import pdf_url, complete


class CoreTests(unittest.TestCase):
    def test_storage_roundtrip_dedup(self):
        with tempfile.TemporaryDirectory() as root:
            doc = fitz.open(); doc.new_page().insert_text((72, 72), "Paper test")
            data = doc.tobytes(); doc.close()
            library = Library(root)
            paper = library.import_pdf(data, "test")
            paper["notes"] = "个人笔记"
            paper["marks"] = [{"page": 0, "text": "Paper", "rects": [[72, 60, 100, 75]], "comment": "批注"}]
            library.save(paper)
            self.assertEqual(library.import_pdf(data, "duplicate")["notes"], "个人笔记")
            self.assertEqual(len(library.all()), 1)
            library.db.close()
            reopened = Library(root)
            self.assertEqual(reopened.all()[0]["marks"][0]["comment"], "批注")
            self.assertTrue(reopened.pdf_path(paper).exists())
            reopened.db.close()

    def test_sources(self):
        self.assertEqual(pdf_url("https://arxiv.org/abs/2401.12345v2"), "https://arxiv.org/pdf/2401.12345v2")
        self.assertEqual(pdf_url("https://arxiv.org/pdf/hep-th/9901001.pdf"), "https://arxiv.org/pdf/hep-th/9901001")
        with self.assertRaises(ValueError): pdf_url("https://example.org/landing")
        with self.assertRaises(ValueError): pdf_url("http://example.org/a.pdf")

    def test_api_protocol(self):
        original = httpx.Client
        def respond(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers["Authorization"], "Bearer test")
            return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}}]})
        with patch("paperreader.services.network.httpx.Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)):
            self.assertEqual(complete({"endpoint": "https://example.org/v1", "model": "test"}, "test", [{"role": "user", "content": "hi"}]), "answer")


    def test_streaming(self):
        original = httpx.Client
        events = ('data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
                  'data: {"choices":[{"delta":{"content":"研究"}}]}\n\n'
                  'data: {"choices":[{"delta":{"content":"结果"}}]}\n\n'
                  'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                  'data: [DONE]\n\n')
        def respond(request):
            import json
            self.assertTrue(json.loads(request.content)["stream"])
            return httpx.Response(200, text=events, headers={"Content-Type": "text/event-stream"})
        chunks = []
        with patch("paperreader.services.network.httpx.Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)):
            result = complete({"endpoint": "https://example.org/v1", "model": "test"}, "", [], on_chunk=chunks.append)
        self.assertEqual(chunks, ["研究", "结果"])
        self.assertEqual(result, "研究结果")

    def test_stream_disconnect_keeps_chunks(self):
        original = httpx.Client
        def respond(request):
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
        chunks = []
        with patch("paperreader.services.network.httpx.Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw)):
            with self.assertRaisesRegex(ValueError, "提前结束"):
                complete({"endpoint": "https://example.org/v1", "model": "test"}, "", [], on_chunk=chunks.append)
        self.assertEqual(chunks, ["partial"])


    def test_soft_remove_restore_and_permanent_delete(self):
        with tempfile.TemporaryDirectory() as root:
            doc = fitz.open(); doc.new_page().insert_text((72,72), 'Title')
            data = doc.tobytes(); doc.close()
            lib = Library(root); paper = lib.import_pdf(data, 'test')
            paper.update(notes='notes', summary='analysis', messages=[{'role':'user','content':'question'}], marks=[{'comment':'note'}])
            lib.save(paper); path = lib.pdf_path(paper)
            lib.remove(paper)
            self.assertEqual(lib.all(), [])
            self.assertTrue(path.exists())
            restored = lib.import_pdf(data, 'again')
            self.assertEqual(restored['notes'], 'notes')
            self.assertEqual(len(lib.all()), 1)
            lib.remove(restored, permanent=True)
            self.assertEqual(lib.all(include_removed=True), [])
            self.assertFalse(path.exists())
            self.assertEqual(lib.import_pdf(data, 'new')['notes'], '')
            lib.db.close()


    def test_http_503_is_service_busy_not_credentials(self):
        from paperreader.services.network import api_error_message
        self.assertIn('繁忙', api_error_message(503))
        self.assertIn('密钥无效', api_error_message(401))
        self.assertIn('余额不足', api_error_message(402))


if __name__ == "__main__": unittest.main()
