"""Tests for guardian.main.FrameBroadcaster WS handshake (audit #3 corrected).

The handler must:
  - reject Origin headers that aren't Tauri-internal (defense-in-depth)
  - accept the Tauri webview origins (`http://tauri.localhost`,
    `tauri://localhost`, `null`)
  - still require the token (the actual security gate)
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest


@pytest.fixture
def port():
    """Find a free port for the broadcaster."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_in_thread(coro_factory):
    """Run an async coroutine in a daemon thread, return the thread."""
    stop = threading.Event()
    result = {}

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result["future"] = asyncio.ensure_future(coro_factory(loop, stop))
            loop.run_until_complete(result["future"])
        except Exception as e:
            result["error"] = e
        finally:
            loop.close()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t, stop, result


def _wait_for_port(host: str, port: int, timeout: float = 2.0):
    import socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def test_handler_accepts_tauri_macos_origin(port):
    """macOS WKWebView sends Origin: http://tauri.localhost — must work."""
    from guardian.main import FrameBroadcaster

    fb = FrameBroadcaster(port=port, token="test-token-123")
    fb.start()
    try:
        assert _wait_for_port("127.0.0.1", port), "broadcaster did not bind"
        # Use the websockets client that ships with the dependency.
        import websockets

        async def probe():
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/?token=test-token-123",
                origin="http://tauri.localhost",
            ) as ws:
                # If we got here without close(1008), the handshake passed.
                return True

        ok = asyncio.run(probe())
        assert ok, "connection with Origin: http://tauri.localhost was rejected"
    finally:
        fb.stop()


def test_handler_accepts_tauri_linux_origin(port):
    """Linux WebView sends Origin: tauri://localhost — must work."""
    from guardian.main import FrameBroadcaster

    fb = FrameBroadcaster(port=port, token="tkn")
    fb.start()
    try:
        assert _wait_for_port("127.0.0.1", port)
        import websockets

        async def probe():
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/?token=tkn",
                origin="tauri://localhost",
            ):
                return True

        ok = asyncio.run(probe())
        assert ok
    finally:
        fb.stop()


def test_handler_accepts_null_origin(port):
    """Some Android/iOS setups send Origin: null — must work."""
    from guardian.main import FrameBroadcaster

    fb = FrameBroadcaster(port=port, token="tkn")
    fb.start()
    try:
        assert _wait_for_port("127.0.0.1", port)
        import websockets

        async def probe():
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/?token=tkn",
                origin="null",
            ):
                return True

        ok = asyncio.run(probe())
        assert ok
    finally:
        fb.stop()


def test_handler_accepts_no_origin(port):
    """Local CLI clients (no Origin header) must still be allowed when
    the token matches."""
    from guardian.main import FrameBroadcaster

    fb = FrameBroadcaster(port=port, token="tkn")
    fb.start()
    try:
        assert _wait_for_port("127.0.0.1", port)
        import websockets

        async def probe():
            # Pass extra_headers={} to suppress Origin entirely
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/?token=tkn",
            ):
                return True

        ok = asyncio.run(probe())
        assert ok
    finally:
        fb.stop()


def test_handler_rejects_cross_origin_webpage(port):
    """A real cross-origin web page (e.g. https://evil.example.com)
    must be rejected even if it presents a valid token — Origin check
    is defense-in-depth on top of the token gate."""
    from guardian.main import FrameBroadcaster

    fb = FrameBroadcaster(port=port, token="tkn")
    fb.start()
    try:
        assert _wait_for_port("127.0.0.1", port)
        import websockets
        from websockets.exceptions import ConnectionClosed, InvalidMessage

        async def probe():
            try:
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}/?token=tkn",
                    origin="https://evil.example.com",
                ) as ws:
                    # Handshake may have completed server-side; the
                    # server will close as soon as it sees the bad
                    # Origin. Wait for that close.
                    try:
                        await ws.recv()
                    except ConnectionClosed as e:
                        return e.code
                    return "still_open_after_recv"
            except ConnectionClosed as e:
                return e.code
            except InvalidMessage:
                # Pre-handshake close (server rejected before WS upgrade).
                return 1008

        code = asyncio.run(probe())
        assert code == 1008, f"expected close code 1008, got {code!r}"
    finally:
        fb.stop()


def test_handler_rejects_bad_token(port):
    """A connection with a wrong token must be rejected regardless of
    Origin (the token is the actual gate)."""
    from guardian.main import FrameBroadcaster

    fb = FrameBroadcaster(port=port, token="right")
    fb.start()
    try:
        assert _wait_for_port("127.0.0.1", port)
        import websockets
        from websockets.exceptions import ConnectionClosed, InvalidMessage

        async def probe():
            try:
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}/?token=wrong",
                    origin="http://tauri.localhost",
                ) as ws:
                    try:
                        await ws.recv()
                    except ConnectionClosed as e:
                        return e.code
                    return "still_open_after_recv"
            except ConnectionClosed as e:
                return e.code
            except InvalidMessage:
                return 1008

        code = asyncio.run(probe())
        assert code == 1008, f"expected close code 1008, got {code!r}"
    finally:
        fb.stop()