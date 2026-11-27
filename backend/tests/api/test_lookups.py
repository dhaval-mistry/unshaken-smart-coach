"""HTTP and OpenAPI coverage for issue #14 exercise-choice lookups."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import lookups
from app.db.readiness import LookupResult, ReadinessState


@pytest.fixture
def client(monkeypatch):
    """Run the real app with telemetry disabled and no database."""
    monkeypatch.setattr(main, "initialize", lambda **_: False)
    monkeypatch.setattr(main, "shutdown", lambda: True)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_shared_headers(response) -> str:
    """Assert the shared uncached JSON and server-generated request contract."""
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    request_id = response.headers["x-request-id"]
    UUID(request_id)
    return request_id


def assert_error(response, status_code, code):
    assert response.status_code == status_code
    request_id = assert_shared_headers(response)
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == request_id


class FakeLookupResources:
    """Deterministic lookup outcomes for HTTP contract tests."""

    def __init__(self, state, items=()):
        self.result = LookupResult(state, tuple(items), 0.01)

    async def lookup(self, _table_name):
        return self.result


@pytest.mark.parametrize(
    ("path", "items"),
    [
        (
            "/api/v1/exercise-categories",
            [
                {"id": 1, "name": "Barbell", "sort_order": 1},
                {"id": 2, "name": "Dumbbell", "sort_order": 2},
            ],
        ),
        (
            "/api/v1/body-parts",
            [
                {"id": 1, "name": "None", "sort_order": 1},
                {"id": 2, "name": "Arms", "sort_order": 2},
            ],
        ),
    ],
)
def test_lookup_success_shape(client, monkeypatch, path, items):
    monkeypatch.setattr(
        lookups,
        "_get_database_resources",
        lambda _app: FakeLookupResources(ReadinessState.READY, items),
    )
    response = client.get(path)
    assert response.status_code == 200
    assert_shared_headers(response)
    assert response.json() == {"items": items}
    assert set(response.json()) == {"items"}
    for item in response.json()["items"]:
        assert set(item) == {"id", "name", "sort_order"}
        assert type(item["id"]) is int
        assert type(item["name"]) is str
        assert type(item["sort_order"]) is int


@pytest.mark.parametrize(
    ("state", "status_code", "code"),
    [
        (ReadinessState.DATABASE_UNAVAILABLE, 503, "database_unavailable"),
        (
            ReadinessState.REFERENCE_DATA_UNAVAILABLE,
            503,
            "reference_data_unavailable",
        ),
        (ReadinessState.INTERNAL_ERROR, 500, "internal_error"),
    ],
)
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/exercise-categories",
        "/api/v1/body-parts",
    ],
)
def test_lookup_safe_errors(
    client,
    monkeypatch,
    state,
    status_code,
    code,
    path,
):
    monkeypatch.setattr(
        lookups,
        "_get_database_resources",
        lambda _app: FakeLookupResources(state),
    )
    response = client.get(path)
    assert_error(response, status_code, code)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/exercise-categories",
        "/api/v1/body-parts",
    ],
)
def test_lookup_rejects_query_or_body(client, monkeypatch, path):
    monkeypatch.setattr(
        lookups,
        "_get_database_resources",
        lambda _app: FakeLookupResources(
            ReadinessState.READY,
            [{"id": 1, "name": "Synthetic", "sort_order": 1}],
        ),
    )
    assert_error(
        client.get(path, params={"filter": "private-value"}),
        422,
        "invalid_request",
    )
    assert_error(
        client.request("GET", path, content=b"private-body"),
        422,
        "invalid_request",
    )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/exercise-categories",
        "/api/v1/body-parts",
    ],
)
def test_lookup_wrong_method_keeps_allow_header(client, path):
    response = client.post(path)
    assert_error(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "GET"


@pytest.mark.parametrize(
    ("path", "required_name"),
    [
        (
            "/api/v1/exercise-categories",
            "LookupResponse",
        ),
        (
            "/api/v1/body-parts",
            "LookupResponse",
        ),
    ],
)
def test_lookup_openapi_contract(client, path, required_name):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][path]["get"]
    assert operation["summary"]
    assert operation["description"]
    assert set(operation["responses"]) >= {"200", "422", "500", "503"}

    success = operation["responses"]["200"]
    ref = success["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/LookupResponse"
    assert "X-Request-ID" in success["headers"]
    assert "Cache-Control" in success["headers"]

    response_model = schema["components"]["schemas"][required_name]
    assert set(response_model["required"]) == {"items"}
    item_ref = response_model["properties"]["items"]["items"]["$ref"]
    item_model = schema["components"]["schemas"][
        item_ref.rsplit("/", 1)[-1]
    ]
    assert set(item_model["required"]) == {"id", "name", "sort_order"}
    assert item_model["properties"]["id"]["type"] == "integer"
    assert item_model["properties"]["name"]["type"] == "string"
    assert item_model["properties"]["sort_order"]["type"] == "integer"

    examples = success["content"]["application/json"]["examples"]
    assert len(examples) == 1
