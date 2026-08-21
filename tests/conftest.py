"""Shared pytest fixtures."""

import http.server
import threading
from pathlib import Path
import pytest


class QuietSimpleHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request log output to keep pytest output clean


@pytest.fixture(scope="session")
def test_server():
    """Spins up a local HTTP server serving the fixtures directory."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    
    class Handler(QuietSimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(fixtures_dir), **kwargs)
            
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    yield f"http://127.0.0.1:{port}"
    
    server.shutdown()
    server.server_close()
