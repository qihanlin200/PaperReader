import io
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import httpx

from paperreader.logger import configure_logging, export_logs, get_logger, limits, shutdown_logging


class LoggerTests(unittest.TestCase):
    def tearDown(self):
        shutdown_logging()

    def test_console_all_levels_file_warning_and_caller_location(self):
        with tempfile.TemporaryDirectory() as directory:
            console = io.StringIO()
            with redirect_stderr(console):
                configure_logging(directory)
                log = get_logger("paperreader.tests")
                log.debug("调试 {}", 1)
                log.info("信息 {}", 2)
                line = __import__("inspect").currentframe().f_lineno + 1
                log.warning("警告 {}", 3)
                log.error("错误 {}", 4)
            output = console.getvalue()
            for word in ("调试 1", "信息 2", "警告 3", "错误 4"):
                self.assertIn(word, output)
            recorded = (Path(directory) / "logger" / "paperreader.log").read_text()
            self.assertNotIn("调试 1", recorded)
            self.assertNotIn("信息 2", recorded)
            self.assertIn("警告 3", recorded)
            self.assertIn("错误 4", recorded)
            self.assertIn(f"test_logger.py:{line}", recorded)

    def test_size_retention_and_export_all_remaining_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            with redirect_stderr(io.StringIO()):
                configure_logging(directory, size_mb=1, retention_days=14)
                folder = Path(directory) / "logger"
                old = folder / "paperreader-ancient.log"
                old.write_text("expired")
                os.utime(old, (1, 1))
                log = get_logger("paperreader.tests")
                for index in range(9):
                    log.warning("{} {}", index, "X" * 200000)
            files = list(folder.glob("paperreader*.log"))
            self.assertFalse(old.exists())
            self.assertLessEqual(sum(path.stat().st_size for path in files), 1024 * 1024)
            archive = Path(directory) / "all-logs.zip"
            self.assertEqual(export_logs(archive), len(files))
            with zipfile.ZipFile(archive) as contents:
                self.assertEqual(set(contents.namelist()), {path.name for path in files})

    def test_exception_stack_lines_keep_timestamp_and_location(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            configure_logging(directory)
            log = get_logger("paperreader.tests")
            try:
                raise ValueError("broken")
            except ValueError:
                log.error("解析失败", exc_info=True)
            lines = (Path(directory) / "logger" / "paperreader.log").read_text().splitlines()
            self.assertTrue(any("ValueError: broken" in line for line in lines))
            self.assertTrue(all(" ERROR test_logger.py:" in line for line in lines))

    def test_reject_invalid_limits(self):
        for size, days in ((0, 14), (101, 14), (10, 0), (10, 91)):
            with self.assertRaises(ValueError):
                limits(size, days)

    def test_pdf_download_failure_records_path_and_stack(self):
        from paperreader.services.network import download
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            configure_logging(directory)
            with patch("paperreader.services.network.httpx.stream", side_effect=httpx.ConnectTimeout("timeout")):
                with self.assertRaises(httpx.ConnectTimeout):
                    download("https://arxiv.org/abs/2408.08435")
            recorded = (Path(directory) / "logger" / "paperreader.log").read_text()
            self.assertIn("PDF 下载失败：arxiv.org/pdf/2408.08435", recorded)
            self.assertIn("httpx.ConnectTimeout: timeout", recorded)

    def test_redacts_common_credentials(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            configure_logging(directory)
            get_logger("paperreader.tests").error(
                "Request failed https://example.org/doc.pdf?api_key=hidden&token=alsohidden Bearer private")
            recorded = (Path(directory) / "logger" / "paperreader.log").read_text()
            self.assertNotIn("hidden", recorded)
            self.assertNotIn("private", recorded)
            self.assertIn("api_key=[redacted]", recorded)

    def test_model_request_and_return_are_visible_without_api_key(self):
        from paperreader.services.network import complete
        original = httpx.Client
        def respond(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "已得到分析结果"}}]})
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()) as console:
            configure_logging(directory)
            with patch("paperreader.services.network.httpx.Client",
                       lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs)):
                result = complete({"endpoint": "https://example.org/v1", "model": "mock-model"},
                                  "super-secret-key", [{"role": "user", "content": "请分析论文"}])
            self.assertEqual(result, "已得到分析结果")
            output = console.getvalue()
            self.assertIn("模型请求", output)
            self.assertIn("mock-model", output)
            self.assertIn("请分析论文", output)
            self.assertIn("HTTP 响应：200", output)
            self.assertIn("已得到分析结果", output)
            self.assertNotIn("super-secret-key", output)
            self.assertFalse((Path(directory) / "logger" / "paperreader.log").exists())


if __name__ == "__main__":
    unittest.main()
