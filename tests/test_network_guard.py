"""The test suite cannot reach the network (pytest-socket, see conftest.py).

Without pytest-socket these tests are skipped, unless RAG_REQUIRE_SOCKET_GUARD=1
(set in CI), which turns a missing guard into a failure.
"""

import os
import socket

import pytest

from tests.conftest import pytest_socket


@pytest.fixture(autouse=True)
def guard_installed():
    if pytest_socket is None:
        if os.getenv("RAG_REQUIRE_SOCKET_GUARD") == "1":
            pytest.fail("pytest-socket is not installed: pip install -e '.[dev]'")
        pytest.skip("pytest-socket is not installed")


def test_connections_to_other_hosts_are_blocked():
    # 192.0.2.1 is reserved for documentation; the guard refuses before any packet
    # is sent, and pytest-socket also emits a warning naming the host.
    with pytest.warns(UserWarning, match="192.0.2.1"):
        with pytest.raises(pytest_socket.SocketConnectBlockedError):
            socket.create_connection(("192.0.2.1", 80), timeout=1)


def test_connections_to_this_machine_are_allowed():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            conn, _ = server.accept()
            conn.close()
