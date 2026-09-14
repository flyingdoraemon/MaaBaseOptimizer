import contextlib
import errno
import io
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import app


class QuietHandler(app.Handler):
    def log_message(self, *args):
        pass


class OtherHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'{"app":"AnotherApp","app_revision":"1"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def running_server(handler=QuietHandler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class AppStartupTests(unittest.TestCase):
    def test_duplicate_start_reuses_healthy_service_and_respects_no_browser(self):
        with running_server() as port:
            output = io.StringIO()
            with patch("sys.argv", ["app.py", "--port", str(port), "--no-browser"]), \
                    patch("app.webbrowser.open") as browser, contextlib.redirect_stdout(output):
                app.main()
            browser.assert_not_called()
            self.assertIn(f"已在运行：http://127.0.0.1:{port}", output.getvalue())
            self.assertEqual(app._running_app_revision("127.0.0.1", port), app.APP_REVISION)

    def test_duplicate_start_opens_browser_and_reports_old_revision(self):
        with running_server() as port:
            output = io.StringIO()
            with patch("sys.argv", ["app.py", "--port", str(port)]), \
                    patch("app._running_app_revision", return_value="older-version"), \
                    patch("app.webbrowser.open") as browser, contextlib.redirect_stdout(output):
                app.main()
            browser.assert_called_once_with(f"http://127.0.0.1:{port}")
            self.assertIn("正在运行的是旧版本", output.getvalue())

    def test_unrelated_service_is_not_reused_or_stopped(self):
        with running_server(OtherHandler) as port:
            output = io.StringIO()
            with patch("sys.argv", ["app.py", "--port", str(port)]), \
                    patch("app.webbrowser.open") as browser, contextlib.redirect_stderr(output), \
                    self.assertRaises(SystemExit) as caught:
                app.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("python app.py --port 8766", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())
            browser.assert_not_called()
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/")
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                connection.close()

    def test_unresponsive_or_invalid_health_check_is_not_reused(self):
        for error in (TimeoutError(), app.HTTPException("closed")):
            with self.subTest(error=type(error).__name__), patch("app.HTTPConnection") as factory:
                factory.return_value.getresponse.side_effect = error
                self.assertIsNone(app._running_app_revision("127.0.0.1", 8765))
                factory.return_value.close.assert_called_once()
        for body in (b"not json", b"[]", b'{"app":"MaaBaseOptimizer"}'):
            with self.subTest(body=body), patch("app.HTTPConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status = 200
                response.read.return_value = body
                self.assertIsNone(app._running_app_revision("127.0.0.1", 8765))

    def test_other_bind_errors_are_preserved(self):
        error = OSError(errno.EACCES, "Permission denied")
        with patch("sys.argv", ["app.py", "--no-browser"]), \
                patch("app.ThreadingHTTPServer", side_effect=error), \
                self.assertRaises(OSError) as caught:
            app.main()
        self.assertIs(caught.exception, error)

    def test_normal_shutdown_closes_server_and_reports_assigned_port(self):
        server = MagicMock()
        server.server_address = ("0.0.0.0", 12345)
        server.serve_forever.side_effect = KeyboardInterrupt
        output = io.StringIO()
        with patch("sys.argv", ["app.py", "--host", "0.0.0.0", "--port", "0", "--no-browser"]), \
                patch("app.ThreadingHTTPServer", return_value=server), \
                contextlib.redirect_stdout(output):
            app.main()
        server.server_close.assert_called_once()
        self.assertIn("http://127.0.0.1:12345", output.getvalue())

    def test_closed_launcher_output_does_not_abort_http_response(self):
        with running_server(app.Handler) as port, patch("builtins.print", side_effect=BrokenPipeError):
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response)["app"], "MaaBaseOptimizer")
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
