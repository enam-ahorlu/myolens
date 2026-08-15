"""Injection surfaces (SRS §7, "Security": authorisation bypass, oversized upload, malformed
CSV, **injection**).

The first three were covered; injection was claimed and not tested. This file exists because
"we thought about injection" and "we checked" are different statements, and the SRS was making
the second one.

There is no SQL here, so the interesting surfaces are the ones a document store and a PDF
renderer actually have:

* **Log forging.** The refusal handler wrote a caller-controlled value into a log line that was
  assembled by interpolating into a JSON-shaped template. It was forgeable, and is fixed at the
  formatter rather than at the call site.
* **Identifiers in logs.** SRS §5.1 promises logs carry no participant identifier. The same
  handler was logging the concrete request path, which contains them.
* **Document-path injection.** Firestore document ids come from URL segments; a ``/`` in one
  addresses a subcollection rather than a document.
* **Report markup.** ``reportlab``'s ``Paragraph`` parses a small HTML dialect, so any
  caller-controlled string that reaches one is a markup-injection surface.
* **Stored payloads.** Whatever a clinician types must come back as data, byte for byte, and
  never as something the API has interpreted.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.adapters.firestore_repo import COLLECTIONS, get_document_store
from app.adapters.storage import get_object_store
from app.auth import CurrentUser, get_current_user
from app.main import JsonFormatter, app
from app.middleware.rate_limit import InProcessRateLimiter, get_rate_limiter
from tests.fakes import FakeDocumentStore

CLINICIAN = CurrentUser(uid="clinician-a", email="a@clinic.example", role="clinician")

#: Payloads chosen for what each one would break, not for looking dangerous.
HOSTILE_STRINGS = [
    '"},{"level":"CRITICAL","message":"forged',  # JSON structure
    "line one\nline two",  # log-line boundary
    "<script>alert(1)</script>",  # HTML/JS
    "<para><font color='red'>x</font></para>",  # reportlab markup
    "'; DROP TABLE participants; --",  # SQL, which this system does not have
    "{{7*7}}",  # template evaluation
    "../../etc/passwd",  # traversal
    "\x00truncated",  # NUL
]


class _Objects:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, name: str, data: bytes) -> None:
        self._objects[name] = data

    def signed_upload_url(self, name: str, content_type: str) -> str:
        return f"https://fake-bucket.example/{name}"

    def read_bytes(self, name: str) -> bytes:
        return self._objects[name]

    def size_bytes(self, name: str) -> int | None:
        blob = self._objects.get(name)
        return None if blob is None else len(blob)


@pytest.fixture
def store() -> FakeDocumentStore:
    return FakeDocumentStore()


@pytest.fixture
def client(store) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CLINICIAN
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_object_store] = lambda: _Objects()
    app.dependency_overrides[get_rate_limiter] = lambda: InProcessRateLimiter(limit_per_hour=1000)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def captured_logs():
    """Attach the production formatter to a buffer, so these assertions are about what the
    application actually emits and not about a test-local approximation of it."""
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("myolens")
    previous, previous_propagate = logger.handlers, logger.propagate
    logger.handlers, logger.propagate = [handler], False
    yield buffer
    logger.handlers, logger.propagate = previous, previous_propagate


# --- log forging -------------------------------------------------------------------------------


def test_a_hostile_request_path_cannot_forge_a_log_field(client, captured_logs):
    """Regression. This exact request used to emit:

        {"level":"INFO","message":"refusal code=not_found path=/v1/participants/a"b"forged":"yes"}

    -- a caller-authored key in a machine-read log.
    """
    client.get("/v1/participants/a%22b%0A%22forged%22:%22yes")

    lines = [line for line in captured_logs.getvalue().splitlines() if line.strip()]
    assert lines, "the refusal produced no log line at all"
    for line in lines:
        record = json.loads(line)  # raises if the caller broke the structure
        assert set(record) <= {"level", "logger", "message", "exception"}, (
            f"a caller-controlled value introduced a log field: {sorted(record)}"
        )
        assert "forged" not in record


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_no_hostile_value_can_break_the_log_structure(client, captured_logs, hostile):
    client.post(
        "/v1/participants",
        json={
            "code": hostile[:32],
            "age_band": "30_44",
            "sex": "female",
            "affected_side": "left",
            "notes": hostile,
        },
    )
    for line in captured_logs.getvalue().splitlines():
        if line.strip():
            json.loads(line)


def test_refusal_logs_name_the_route_not_the_identifier_i4(client, store, captured_logs):
    """SRS §5.1: "Logs carry no participant identifier -- a pseudonymous code plus a session time
    is still a re-identification surface." A concrete path defeats that promise by construction."""
    created = client.post(
        "/v1/participants",
        json={
            "code": "P-LOG",
            "age_band": "30_44",
            "sex": "female",
            "affected_side": "left",
            "notes": "",
        },
    )
    participant_id = created.json()["id"]
    client.delete(f"/v1/participants/{participant_id}")
    captured_logs.truncate(0)
    captured_logs.seek(0)

    client.get(f"/v1/participants/{participant_id}")  # soft-deleted -> refusal

    logged = captured_logs.getvalue()
    assert logged.strip(), "the refusal produced no log line"
    assert participant_id not in logged, (
        "the participant id reached the log; SRS §5.1 says it must not"
    )
    assert "{participant_id}" in logged, "the route template should be logged in its place"


# --- document-path injection -------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_id",
    [
        "a%2Fb",  # a slash addresses a subcollection, not a document
        "..%2F..%2Fadmin",
        "a%00b",
        "%2E%2E%2F",
    ],
)
def test_a_hostile_document_id_is_a_refusal_not_a_crash(client, raw_id):
    """Firestore document ids come straight from a URL segment. None of these may reach a 500 --
    an unhandled exception here would mean the id was interpreted rather than looked up."""
    response = client.get(f"/v1/participants/{raw_id}")
    assert response.status_code in (400, 404, 422), response.text
    assert response.status_code < 500


def test_a_hostile_id_cannot_reach_another_clinicians_record(client, store):
    """The traversal is meaningless as well as refused: ownership is a field comparison, not a
    path computation, so there is no parent directory to escape into."""
    from app.domain.participants import AffectedSide, AgeBand, Sex, new_participant

    victim = new_participant(
        code="P-B",
        age_band=AgeBand.Y30_44,
        sex=Sex.MALE,
        affected_side=AffectedSide.RIGHT,
        notes="",
        created_by="clinician-b",
    )
    store.set(COLLECTIONS.PARTICIPANTS, "victim", {**victim.to_document(), "id": "victim"})
    for raw_id in ("..%2Fvictim", "victim%2F..%2Fvictim", "victim"):
        response = client.get(f"/v1/participants/{raw_id}")
        assert response.status_code == 404, f"{raw_id} -> {response.status_code}"


# --- stored payloads ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_a_hostile_note_round_trips_as_data(client, hostile):
    """Stored, returned verbatim, never interpreted. The front end escapes on render (React does
    it by default and nothing in this codebase uses dangerouslySetInnerHTML); the API's job is to
    not corrupt the value on the way through."""
    created = client.post(
        "/v1/participants",
        json={
            "code": "P-XSS",
            "age_band": "30_44",
            "sex": "female",
            "affected_side": "left",
            "notes": hostile,
        },
    )
    assert created.status_code == 201, created.text
    fetched = client.get(f"/v1/participants/{created.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["notes"] == hostile


def test_the_code_field_still_refuses_what_it_always_refused(client):
    """Length bounds are the participant code's only constraint, and they still hold. The field
    is deliberately not charset-restricted: it is a pseudonymous code a clinic chooses, and a
    codebase that cannot store an apostrophe safely should fix its storage, not its alphabet."""
    for bad in ("", "x", "y" * 33):
        response = client.post(
            "/v1/participants",
            json={
                "code": bad,
                "age_band": "30_44",
                "sex": "female",
                "affected_side": "left",
                "notes": "",
            },
        )
        assert response.status_code == 422


# --- the PDF report ----------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", ["<para>x</para>", "<font color='red'>x</font>", "a & b < c"])
def test_report_markup_in_a_participant_code_does_not_break_the_pdf(hostile):
    """``reportlab``'s ``Paragraph`` parses a small HTML dialect; unbalanced or unexpected markup
    raises and would surface as a 500 on export (G1). The participant code reaches the report, so
    it is checked here directly rather than inferred from where it is currently rendered -- the
    guarantee should survive someone later moving that cell into a ``Paragraph``.
    """
    from tests.test_sessions import (
        FakeObjectStore,
        _client_as,
        _register_participant,
        _segmented_session,
    )

    store = FakeDocumentStore()
    objects = FakeObjectStore()
    client, session_id, _ = _segmented_session(store, objects)
    client.post(f"/v1/sessions/{session_id}/approve")

    session_doc = store.get(COLLECTIONS.SESSIONS, session_id)
    participant = store.get(COLLECTIONS.PARTICIPANTS, session_doc["participantId"])
    participant["code"] = hostile
    store.set(COLLECTIONS.PARTICIPANTS, participant["id"], participant)

    response = client.get(f"/v1/sessions/{session_id}/export")

    assert response.status_code == 200, response.text
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 1000
    app.dependency_overrides.clear()

    # Silence the unused-import linters without weakening the imports above.
    assert callable(_client_as) and callable(_register_participant)


def test_the_export_filename_is_server_generated(client, store):
    """The Content-Disposition header interpolates a filename. It is built from the session id --
    a server-side uuid4 -- and never from anything a caller supplies, so there is no CRLF to
    inject into a response header."""
    from tests.test_sessions import FakeObjectStore, _segmented_session

    local_store = FakeDocumentStore()
    objects = FakeObjectStore()
    local_client, session_id, _ = _segmented_session(local_store, objects)
    local_client.post(f"/v1/sessions/{session_id}/approve")

    response = local_client.get(f"/v1/sessions/{session_id}/export")
    disposition = response.headers["content-disposition"]

    assert disposition == f'attachment; filename="myolens-session-{session_id}.pdf"'
    assert "\r" not in disposition and "\n" not in disposition
    app.dependency_overrides.clear()
