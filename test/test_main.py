from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_the_application_exposes_its_title_and_version_from_the_settings() -> None:
    assert app.title == settings.API_TITLE
    assert app.version == settings.API_VERSION


def test_the_openapi_schema_documents_the_health_endpoint(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


def test_every_exposed_response_field_carries_a_swagger_description(
    client: TestClient,
) -> None:
    # On RapidAPI the Swagger description *is* the documentation the client
    # buys — it has no access to the code (CLAUDE.md §4). This walks the served
    # schema rather than the models, so it keeps holding as endpoints are added.
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    undocumented = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        for field, spec in schema.get("properties", {}).items()
        if not spec.get("description")
    ]

    assert undocumented == []


def test_the_swagger_ui_is_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
