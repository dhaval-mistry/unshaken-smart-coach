"""Readiness HTTP contract and cleanup tests using clearly identified test doubles.

No PostgreSQL is contacted here. Live database behavior is covered by
tests/test_readiness_database.py.
"""

import asyncio
import logging
import socket
import threading
import time
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import exc as sa_exc

from app import main
from app.api import health
from app.db import readiness

SECRETS = ("hunter2", "SELECT", "postgresql://", "db.internal", ":5432", "Traceback")


@pytest.fixture
def client(monkeypatch):
    """Run the real app with telemetry replaced by do-nothing functions."""
    monkeypatch.setattr(main, "initialize", lambda **_: False)
    monkeypatch.setattr(main, "shutdown", lambda: True)
    monkeypatch.setattr(health, "_last_readiness_state", "ready")
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def stub_check(monkeypatch, result):
    """Replace the database check with a double returning or raising result."""

    async def double(_deadline):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(readiness, "check_readiness", double)


def assert_error(response, status_code, code):
    """Errors use the shared envelope, uncached, with matching request IDs."""
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    UUID(response.headers["x-request-id"])


def test_ready_returns_exact_success_body(client, monkeypatch):
    stub_check(monkeypatch, None)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["cache-control"] == "no-store"
    UUID(response.headers["x-request-id"])


@pytest.mark.parametrize("code", ["database_unavailable", "reference_data_unavailable"])
def test_ready_failures_use_shared_503_and_liveness_stays_up(client, monkeypatch, code):
    stub_check(monkeypatch, code)
    assert_error(client.get("/health/ready"), 503, code)
    assert client.get("/health/live").status_code == 200


def test_check_slower_than_budget_returns_503_at_budget(client, monkeypatch):
    async def never_finishes(_deadline):
        await asyncio.sleep(30)

    monkeypatch.setattr(readiness, "check_readiness", never_finishes)
    monkeypatch.setattr(health, "READINESS_BUDGET_SECONDS", 0.2)
    started = time.monotonic()
    response = client.get("/health/ready")
    assert time.monotonic() - started < 2
    assert_error(response, 503, "database_unavailable")


def test_unexpected_failure_is_safe_in_response_and_logs(client, monkeypatch, caplog):
    stub_check(
        monkeypatch,
        RuntimeError("password=hunter2 SELECT 1 postgresql://u:p@db.internal:5432/x"),
    )
    with caplog.at_level(logging.DEBUG):
        response = client.get("/health/ready")
    assert_error(response, 500, "internal_error")
    logged = caplog.text
    assert "RuntimeError" in logged  # Safe class name is retained for support.
    for private in SECRETS:
        assert private not in response.text
        assert private not in logged


def test_repeated_outage_polls_log_one_state_change(client, monkeypatch, caplog):
    stub_check(monkeypatch, "database_unavailable")
    with caplog.at_level(logging.INFO, logger="unshaken.api.health"):
        for _ in range(3):
            client.get("/health/ready")
    assert caplog.text.count("readiness.failed") == 1


@pytest.mark.parametrize(
    "extra", [{"params": {"foo": "secret"}}, {"content": b"secret"}], ids=["query", "body"]
)
def test_ready_rejects_input_before_touching_database(client, monkeypatch, extra):
    stub_check(monkeypatch, RuntimeError("must not run"))
    response = client.request("GET", "/health/ready", **extra)
    assert_error(response, 422, "invalid_request")
    assert "secret" not in response.text


def test_ready_wrong_method_keeps_allow_header(client):
    response = client.post("/health/ready")
    assert_error(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"


def test_openapi_documents_ready_success_and_errors(client):
    schema = client.get("/openapi.json").json()
    responses = schema["paths"]["/health/ready"]["get"]["responses"]
    assert set(responses) == {"200", "422", "500", "503"}

    def model(status):
        ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
        return schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]

    assert model("200")["properties"]["status"]["const"] == "ready"
    for status in ("422", "500", "503"):
        assert model(status)["required"] == ["error"]
    examples = responses["503"]["content"]["application/json"]["examples"]
    assert set(examples) == {"database_unavailable", "reference_data_unavailable"}
    assert set(responses["500"]["content"]["application/json"]["examples"]) == {"internal_error"}
    for status in responses:
        assert {"X-Request-ID", "Cache-Control"} <= set(responses[status]["headers"])


def test_guard_abandon_wakes_a_blocked_read():
    """A driver read that would block forever is released by abandon()."""
    reader, writer = socket.socketpair()
    guard = readiness._SocketGuard()
    assert guard.attach(reader.fileno())
    received = []
    worker = threading.Thread(target=lambda: received.append(reader.recv(1)))
    worker.start()
    time.sleep(0.05)
    guard.abandon()
    worker.join(2)
    assert not worker.is_alive()
    assert received == [b""]  # End of stream, as a disconnect looks to the driver.
    reader.close()
    writer.close()


def test_guard_never_touches_a_detached_socket():
    """After detach the connection may be reused, so abandon must leave it alone."""
    reader, writer = socket.socketpair()
    guard = readiness._SocketGuard()
    guard.attach(reader.fileno())
    guard.detach()
    guard.abandon()
    writer.sendall(b"x")
    assert reader.recv(1) == b"x"
    reader.close()
    writer.close()


def test_guard_refuses_attach_after_abandon():
    guard = readiness._SocketGuard()
    guard.abandon()
    assert guard.attach(123) is False


def test_guard_ignores_unrelated_socket_that_reuses_the_closed_number():
    """Regression: abandon after the driver closed its socket hits only that socket.

    Simulates SQLAlchemy invalidating the connection after a disconnect, which
    closes the driver's descriptor before the worker detaches. Another socket
    then receives the same descriptor number before the caller abandons.
    """
    driver_side, server_side = socket.socketpair()
    guard = readiness._SocketGuard()
    assert guard.attach(driver_side.fileno())
    closed_number = driver_side.fileno()
    driver_side.close()  # Invalidation frees the number; the guard keeps its duplicate.
    unrelated, peer = socket.socketpair()
    try:
        if closed_number not in (unrelated.fileno(), peer.fileno()):
            pytest.skip("the operating system did not reuse the descriptor number")
        guard.abandon()
        peer.sendall(b"x")
        assert unrelated.recv(1) == b"x"  # The unrelated socket still works.
        unrelated.sendall(b"y")
        assert peer.recv(1) == b"y"
        assert server_side.recv(1) == b""  # The guarded connection was shut down.
    finally:
        guard.detach()
        for sock in (unrelated, peer, server_side):
            sock.close()


class FakeConnection:
    """Context-managed connection double that records its release."""

    def __init__(self, record):
        self.record = record
        # A real socket, because the guard duplicates the driver's descriptor.
        self._sockets = socket.socketpair()
        pgconn = type("Pg", (), {"socket": self._sockets[0].fileno()})
        self.connection = type(
            "Fairy",
            (),
            {"driver_connection": type("Driver", (), {"pgconn": pgconn})},
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.record.append("released")
        for sock in self._sockets:
            sock.close()

    def rollback(self):
        self.record.append("rollback")


def use_fake_engine(monkeypatch, record):
    engine = type("Engine", (), {"connect": lambda _self: FakeConnection(record)})()
    monkeypatch.setattr(readiness, "shared_engine", lambda: engine)


def orig(sqlstate):
    return type("Orig", (Exception,), {"sqlstate": sqlstate})()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (sa_exc.OperationalError("s", {}, orig("08006")), "database_unavailable"),
        (sa_exc.OperationalError("s", {}, orig("57014")), "database_unavailable"),
        (sa_exc.InterfaceError("s", {}, orig(None)), "database_unavailable"),
        (sa_exc.TimeoutError(), "database_unavailable"),
        (sa_exc.ProgrammingError("s", {}, orig("42P01")), "reference_data_unavailable"),
    ],
    ids=["connection", "statement-timeout", "interface", "pool-timeout", "missing-table"],
)
def test_expected_database_errors_are_classified_and_released(monkeypatch, error, expected):
    record = []
    use_fake_engine(monkeypatch, record)

    def fails(*_):
        raise error

    monkeypatch.setattr(readiness, "_has_active_choices", fails)
    result = readiness._read_reference_data(readiness._SocketGuard(), time.monotonic() + 5)
    assert result == expected
    assert record == ["rollback", "released"]


def test_programming_error_is_not_reported_as_an_outage(monkeypatch):
    record = []
    use_fake_engine(monkeypatch, record)

    def fails(*_):
        raise sa_exc.ProgrammingError("s", {}, orig("42703"))

    monkeypatch.setattr(readiness, "_has_active_choices", fails)
    with pytest.raises(sa_exc.ProgrammingError):
        readiness._read_reference_data(readiness._SocketGuard(), time.monotonic() + 5)
    assert record == ["rollback", "released"]


def test_exhausted_deadline_releases_without_reading(monkeypatch):
    record = []
    use_fake_engine(monkeypatch, record)
    monkeypatch.setattr(readiness, "_has_active_choices", lambda *_: pytest.fail("read ran"))
    result = readiness._read_reference_data(readiness._SocketGuard(), time.monotonic() - 1)
    assert result == "database_unavailable"
    assert record == ["released"]


@pytest.mark.parametrize("cancel", [False, True], ids=["deadline", "client-cancel"])
def test_abandoned_check_breaks_blocked_read_and_releases(monkeypatch, cancel):
    """A driver call that asyncio cannot interrupt still ends and releases."""
    record = []
    reader, writer = socket.socketpair()
    connection = FakeConnection(record)
    connection.connection.driver_connection.pgconn.socket = reader.fileno()
    engine = type("Engine", (), {"connect": lambda _self: connection})()
    monkeypatch.setattr(readiness, "shared_engine", lambda: engine)
    finished = threading.Event()

    def blocked_read(*_):
        try:
            if reader.recv(1) == b"":
                raise sa_exc.OperationalError("s", {}, orig("08006"))
        finally:
            finished.set()

    monkeypatch.setattr(readiness, "_has_active_choices", blocked_read)

    async def scenario():
        task = asyncio.create_task(readiness.check_readiness(time.monotonic() + 30))
        await asyncio.sleep(0.05)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(task, 0.05)

    asyncio.run(scenario())
    assert finished.wait(2)
    deadline = time.monotonic() + 2
    while record != ["rollback", "released"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert record == ["rollback", "released"]
    reader.close()
    writer.close()
