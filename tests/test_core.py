import tempfile
import unittest
from unittest.mock import patch
import fitz
import httpx
from paperreader.services.library import Library
from paperreader.services.network import pdf_url, complete, client_options, api_error_message


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

    def test_http_intranet_api_and_invalid_address(self):
        original = httpx.Client
        def respond(request):
            self.assertEqual(str(request.url), "http://model.internal:8000/v1/chat/completions")
            self.assertNotIn("Authorization", request.headers)
            return httpx.Response(200, json={"choices": [{"message": {"content": "内网模型正常"}}]})
        def direct_client(**kwargs):
            self.assertFalse(kwargs["trust_env"])
            return original(transport=httpx.MockTransport(respond), **kwargs)
        with patch("paperreader.services.network.httpx.Client", direct_client):
            self.assertEqual(complete({"endpoint": "http://model.internal:8000/v1/", "model": "local"}, "", [],), "内网模型正常")
        for endpoint in ("ftp://model.internal/v1", "http://"):
            with self.assertRaisesRegex(ValueError, "HTTP 或 HTTPS"):
                complete({"endpoint": endpoint, "model": "local"}, "", [])

    def test_http_model_bypasses_environment_proxy(self):
        self.assertFalse(client_options("http://192.168.1.20:8000/v1/chat/completions")["trust_env"])
        self.assertTrue(client_options("https://api.example.org/v1/chat/completions")["trust_env"])
        self.assertIn("不能据此判断 API Key 无效", api_error_message(504))


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
            self.assertEqual(request.headers["Accept"], "text/event-stream")
            return httpx.Response(200, text=events, headers={"Content-Type": "text/event-stream"})
        chunks = []
        def direct_client(**kwargs):
            self.assertFalse(kwargs["trust_env"])
            return original(transport=httpx.MockTransport(respond), **kwargs)
        with patch("paperreader.services.network.httpx.Client", direct_client):
            result = complete({"endpoint": "http://192.168.1.20:8000/v1", "model": "test"}, "", [], on_chunk=chunks.append)
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

    def test_analysis_cancel_closes_waiting_stream(self):
        import asyncio
        from threading import Event
        from paperreader.services.analysis import AnalysisStopped

        cancel = Event()
        closed = Event()
        class WaitingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
                cancel.set()
                await asyncio.sleep(2)

            async def aclose(self):
                closed.set()

        original = httpx.AsyncClient
        def respond(request):
            return httpx.Response(200, stream=WaitingStream())
        chunks = []
        with patch("paperreader.services.network.httpx.AsyncClient",
                   lambda **kw: original(transport=httpx.MockTransport(respond), **kw)):
            with self.assertRaises(AnalysisStopped):
                complete({"endpoint": "https://example.org/v1", "model": "test"}, "", [],
                         on_chunk=chunks.append, cancel=cancel)
        self.assertTrue(closed.is_set())
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

    def test_paper_groups_persist_and_follow_remove_semantics(self):
        with tempfile.TemporaryDirectory() as root:
            doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Grouped paper')
            data = doc.tobytes(); doc.close()
            lib = Library(root)
            paper = lib.import_pdf(data, 'Grouped paper')
            group_id = lib.create_group('  研究   方法  ')
            self.assertEqual(lib.list_groups(), [{'id': group_id, 'name': '研究 方法', 'pinned': False}])
            with self.assertRaisesRegex(ValueError, '已存在'):
                lib.create_group('研究 方法')
            with self.assertRaisesRegex(ValueError, '不存在'):
                lib.set_group(paper['id'], 9999)
            lib.set_group(paper['id'], group_id)
            self.assertEqual(lib.list_metadata()[0]['group_id'], group_id)
            lib.db.close()

            lib = Library(root)
            self.assertEqual(lib.list_metadata()[0]['group_id'], group_id)
            lib.remove(paper)
            self.assertEqual(lib.list_metadata(), [])
            lib.import_pdf(data, 'Grouped paper')
            self.assertEqual(lib.list_metadata()[0]['group_id'], group_id)
            lib.set_group(paper['id'], None)
            self.assertIsNone(lib.list_metadata()[0]['group_id'])
            lib.remove(paper, permanent=True)
            self.assertEqual(lib.list_groups()[0]['id'], group_id)
            lib.db.close()

    def test_group_rename_pin_and_both_delete_choices(self):
        with tempfile.TemporaryDirectory() as root:
            lib = Library(root)
            first_doc = fitz.open(); first_doc.new_page().insert_text((72, 72), 'First')
            first = lib.import_pdf(first_doc.tobytes(), 'First'); first_doc.close()
            second_doc = fitz.open(); second_doc.new_page().insert_text((72, 72), 'Second')
            second = lib.import_pdf(second_doc.tobytes(), 'Second'); second_doc.close()
            first['notes'] = 'keep this note'; lib.save(first)
            ordinary = lib.create_group('Ordinary')
            pinned = lib.create_group('Pinned')
            lib.set_group(first['id'], ordinary)
            lib.set_group(second['id'], pinned)
            lib.rename_group(ordinary, 'Renamed')
            lib.set_group_pinned(pinned, True)
            self.assertEqual([g['name'] for g in lib.list_groups()], ['Pinned', 'Renamed'])
            self.assertTrue(lib.list_groups()[0]['pinned'])
            self.assertEqual(lib.paper_ids_in_group(ordinary), [first['id']])

            lib.delete_group(ordinary)
            self.assertIsNone(next(p for p in lib.list_metadata() if p['id'] == first['id'])['group_id'])
            self.assertEqual(lib.get(first['id'])['notes'], 'keep this note')
            self.assertTrue(lib.pdf_path(first).exists())
            lib.remove(second)
            deleted = lib.delete_group(pinned, permanent=True)
            self.assertEqual(deleted, [second['id']])
            self.assertFalse(lib.pdf_path(second).exists())
            self.assertEqual([p['id'] for p in lib.list_metadata()], [first['id']])
            self.assertEqual(lib.list_groups(), [])
            lib.db.close()

    def test_group_delete_restores_files_if_staging_fails(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            lib = Library(root)
            docs = []
            for title in ('One', 'Two'):
                doc = fitz.open(); doc.new_page().insert_text((72, 72), title)
                docs.append(lib.import_pdf(doc.tobytes(), title)); doc.close()
            group_id = lib.create_group('Keep')
            for paper in docs: lib.set_group(paper['id'], group_id)
            second_path = lib.pdf_path(docs[1])
            original_replace = Path.replace

            def fail_second(path, target):
                if path == second_path: raise OSError('file is busy')
                return original_replace(path, target)

            with patch.object(Path, 'replace', fail_second):
                with self.assertRaisesRegex(OSError, 'file is busy'):
                    lib.delete_group(group_id, permanent=True)
            self.assertEqual(len(lib.list_metadata()), 2)
            self.assertEqual(len(lib.list_groups()), 1)
            self.assertTrue(all(lib.pdf_path(paper).exists() for paper in docs))
            lib.db.close()

    def test_bulk_group_move_is_atomic(self):
        with tempfile.TemporaryDirectory() as root:
            lib = Library(root)
            doc = fitz.open(); doc.new_page().insert_text((72, 72), 'Move me')
            paper = lib.import_pdf(doc.tobytes(), 'Move me'); doc.close()
            group_id = lib.create_group('Target')
            with self.assertRaisesRegex(ValueError, '未移动任何论文'):
                lib.set_groups([paper['id'], 'missing-paper'], group_id)
            self.assertIsNone(lib.list_metadata()[0]['group_id'])
            lib.set_groups([paper['id'], paper['id']], group_id)
            self.assertEqual(lib.list_metadata()[0]['group_id'], group_id)
            lib.db.close()

    def test_group_drag_order_persists_and_updates_pin_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            lib = Library(root)
            first, second, third = (lib.create_group(name) for name in ('First', 'Second', 'Third'))
            lib.set_group_pinned(second, True)
            self.assertEqual([g['id'] for g in lib.list_groups()], [second, first, third])
            lib.reorder_group(third, first, after=False)
            self.assertEqual([g['id'] for g in lib.list_groups()], [second, third, first])
            lib.reorder_group(third, second, after=False)
            self.assertEqual([g['id'] for g in lib.list_groups()], [third, second, first])
            self.assertTrue(lib.list_groups()[0]['pinned'])
            lib.reorder_group(second, first, after=True)
            self.assertEqual([g['id'] for g in lib.list_groups()], [third, first, second])
            self.assertFalse(lib.list_groups()[-1]['pinned'])
            with self.assertRaisesRegex(ValueError, '不存在'):
                lib.reorder_group(third, 9999)
            lib.db.close()
            reopened = Library(root)
            self.assertEqual([g['id'] for g in reopened.list_groups()], [third, first, second])
            reopened.db.close()

    def test_existing_group_order_migrates_without_reordering(self):
        import sqlite3
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            db = sqlite3.connect(Path(root) / 'library.sqlite3')
            db.execute('CREATE TABLE paper_groups (id INTEGER PRIMARY KEY, name TEXT, pinned_rank INTEGER NOT NULL DEFAULT 0)')
            db.executemany('INSERT INTO paper_groups VALUES (?,?,?)',
                           [(1, 'Old A', 0), (2, 'Old B', 2), (3, 'Old C', 1)])
            db.commit(); db.close()
            lib = Library(root)
            self.assertEqual([g['id'] for g in lib.list_groups()], [2, 3, 1])
            lib.db.close()


    def test_http_503_is_service_busy_not_credentials(self):
        from paperreader.services.network import api_error_message
        self.assertIn('繁忙', api_error_message(503))
        self.assertIn('密钥无效', api_error_message(401))
        self.assertIn('余额不足', api_error_message(402))


    def test_metadata_list_never_reads_full_records_or_opens_pdf(self):
        import sqlite3, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            database = sqlite3.connect(Path(root)/'library.sqlite3')
            database.execute('CREATE TABLE papers (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            database.execute('INSERT INTO papers VALUES (?,?)', ('old', json.dumps(dict(id='old', title='2504.15228', notes='large note'*10000))))
            database.commit(); database.close()
            with patch('fitz.open', side_effect=AssertionError('Do not open PDF for list')):
                lib = Library(root)
                with patch('paperreader.services.library.json.loads', side_effect=AssertionError('Do not parse records for list')):
                    metadata = lib.list_metadata()
                self.assertEqual(metadata[0]['title'], '2504.15228')
                self.assertNotIn('notes', metadata[0])
            lib.db.close()


if __name__ == "__main__": unittest.main()
