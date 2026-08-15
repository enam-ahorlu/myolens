"""CORS is what actually let a browser call this API at all (see the 2026-08-15 incident: the
deployed frontend and the deployed API sit on different origins, and with no CORS middleware
every browser request -- not just cross-site ones -- died at the preflight `OPTIONS` request
with a 405 before it ever reached a route handler; `curl`, `TestClient` and the CI suite never
noticed because none of them send a preflight). This test exercises the actual preflight a
browser sends, not just a plain request, so a regression here fails loudly again."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_preflight_from_the_deployed_frontend_is_allowed():
    response = client.options(
        "/v1/participants",
        headers={
            "Origin": "https://myolens.web.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://myolens.web.app"


def test_preflight_from_an_unlisted_origin_is_not_granted():
    response = client.options(
        "/v1/participants",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    # Starlette's CORSMiddleware still answers 200 to an unmatched-origin preflight, it just
    # omits the allow-origin header -- which is what actually stops the browser from proceeding.
    assert "access-control-allow-origin" not in response.headers
