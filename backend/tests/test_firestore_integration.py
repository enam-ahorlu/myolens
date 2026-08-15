"""The full journey against a real Firestore, not a fake (SRS §7, "Integration").

**Why this exists.** SRS §7 claimed integration coverage "signed URL → object → features →
normalise → infer → smooth → bouts → approve → metrics", and the plan of record said it ran
against the Firestore emulator. Neither was true: every other test in this suite substitutes
``FakeDocumentStore``, so ``FirestoreDocumentStore`` -- the only code that actually talks to the
database -- had no test at all. A fake that is more permissive than the real store is the classic
way an integration bug survives a green suite, and this one is: the fake treats a collection name
as an opaque dictionary key, so a malformed collection path, an unsupported query, or a value
Firestore refuses to serialise all pass silently.

**The assertion that matters most is the last one.** ``firestore.rules`` protects
``/bouts/{boutId}``, and ``firestore/rules.test.mjs`` proves those rules behave -- but it proves
it about a path *it* chooses, using a client it sets up itself. Nothing connected that to where
the application actually writes. If a refactor moved bouts under ``sessions/{id}/bouts``, the
rules suite would stay green, the backend suite would stay green, and H3's guarantee would
quietly stop covering real data. This test writes through the application and then reads the
collections back by name, so the two halves are pinned to each other.

Requires ``FIRESTORE_EMULATOR_HOST``; skipped otherwise, so a developer without a JVM still gets
a clean local run. CI provides it -- see the ``firestore`` job in ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.adapters.firestore_repo import COLLECTIONS, FirestoreDocumentStore, get_document_store
from app.adapters.storage import get_object_store, new_object_name
from app.auth import CurrentUser, get_current_user
from app.main import app
from app.middleware.rate_limit import InProcessRateLimiter, get_rate_limiter

ARTEFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DEMO_DIR = ARTEFACT_DIR / "demo"

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"),
    reason="needs a Firestore emulator; set FIRESTORE_EMULATOR_HOST (CI does)",
)

CLINICIAN = CurrentUser(uid="integration-clinician", email="i@clinic.example", role="clinician")


class InMemoryObjectStore:
    """Cloud Storage stays faked. The boundary under test here is the *database*.

    Signed-URL minting is a pure function of its inputs and is covered by ``test_upload_guards``;
    standing up a GCS emulator as well would add a second moving part without adding a second
    thing proved.
    """

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, object_name: str, data: bytes) -> None:
        self._objects[object_name] = data

    def signed_upload_url(self, object_name: str, content_type: str) -> str:
        return f"https://fake-bucket.example/{object_name}"

    def read_bytes(self, object_name: str) -> bytes:
        return self._objects[object_name]

    def size_bytes(self, object_name: str) -> int | None:
        blob = self._objects.get(object_name)
        return None if blob is None else len(blob)


def _demo_bytes(subject: str, kind: str) -> bytes:
    path = DEMO_DIR / f"demo_{subject}_{kind}.csv.gz"
    return path.read_bytes()


def _calibration_bytes() -> bytes:
    """The real held-out calibration capture, gzipped, exactly as it ships.

    An earlier draft synthesised random noise instead and C4 refused it outright -- Mahalanobis
    15.89 against a threshold of 12.0. The guard was right and the fixture was wrong: noise is
    genuinely not a lower limb. Using the real capture also means this test exercises the gzipped
    calibration path, which was broken until the two upload parsers were unified.
    """
    return _demo_bytes("Sub10", "calibration")


@pytest.fixture
def store() -> FirestoreDocumentStore:
    # A unique project per run, so concurrent CI jobs and repeated local runs cannot see each
    # other's documents. The emulator creates projects on demand.
    return FirestoreDocumentStore(project=f"myolens-it-{uuid4().hex[:8]}")


@pytest.fixture
def objects() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def client(store, objects) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CLINICIAN
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_object_store] = lambda: objects
    app.dependency_overrides[get_rate_limiter] = lambda: InProcessRateLimiter(limit_per_hour=1000)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_real_store_round_trips_a_document_and_answers_a_filtered_query(store):
    """``FirestoreDocumentStore`` itself, before any router is involved.

    ``query`` builds its filters positionally, which the client library has been deprecating;
    a warning today is a removal tomorrow, and nothing else in this suite would notice.
    """
    collection = f"probe-{uuid4().hex[:8]}"
    store.set(collection, "a", {"id": "a", "owner": "x", "n": 1})
    store.set(collection, "b", {"id": "b", "owner": "y", "n": 2})

    assert store.get(collection, "a") == {"id": "a", "owner": "x", "n": 1}
    assert store.get(collection, "missing") is None

    store.update(collection, "a", {"n": 99})
    assert store.get(collection, "a")["n"] == 99

    mine = store.query(collection, owner="x")
    assert [d["id"] for d in mine] == ["a"]

    store.delete(collection, "a")
    assert store.get(collection, "a") is None
    # Idempotent, as the protocol's docstring promises.
    store.delete(collection, "a")


def test_the_full_journey_persists_in_firestore(client, store, objects):
    """Participant → calibration → session → segment → correct → approve → metrics."""
    created = client.post(
        "/v1/participants",
        json={
            "code": "IT-001",
            "age_band": "30_44",
            "sex": "female",
            "affected_side": "left",
            "notes": "integration",
        },
    )
    assert created.status_code == 201, created.text
    participant_id = created.json()["id"]
    assert store.get(COLLECTIONS.PARTICIPANTS, participant_id) is not None

    calibration_object = new_object_name("calibration", CLINICIAN.uid, participant_id)
    objects.put(calibration_object, _calibration_bytes())
    calibrated = client.post(
        "/v1/calibrations",
        json={"participant_id": participant_id, "object_name": calibration_object},
    )
    assert calibrated.status_code == 201, calibrated.text
    assert store.query(COLLECTIONS.CALIBRATIONS, participantId=participant_id), (
        "the calibration was accepted but is not queryable by participant in the real store"
    )

    session_object = new_object_name("session", CLINICIAN.uid, participant_id)
    objects.put(session_object, _demo_bytes("Sub10", "session"))
    session = client.post(
        "/v1/sessions",
        json={"participant_id": participant_id, "object_name": session_object},
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    segmented = client.post(f"/v1/sessions/{session_id}/segment")
    assert segmented.status_code == 200, segmented.text
    bouts = segmented.json()["bouts"]
    assert bouts, "segmentation produced no bouts"

    # E7: the gate holds against the real store too, not only against the fake.
    assert client.get(f"/v1/sessions/{session_id}/metrics").status_code == 412

    approved = client.post(f"/v1/sessions/{session_id}/approve")
    assert approved.status_code == 200, approved.text

    metrics = client.get(f"/v1/sessions/{session_id}/metrics")
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["tasks"], "approved session produced no per-task metrics"


def test_the_application_writes_into_the_collections_the_rules_protect(client, store, objects):
    """Pins ``firestore.rules`` to reality.

    ``firestore/rules.test.mjs`` proves the rules behave for ``/participants``, ``/sessions``,
    ``/bouts`` and ``/audit`` -- but it writes those documents itself, so it proves nothing about
    where the *application* puts them. Move bouts under ``sessions/{id}/bouts`` in a refactor and
    both suites stay green while H3's guarantee silently stops covering real data.
    """
    created = client.post(
        "/v1/participants",
        json={
            "code": "IT-002",
            "age_band": "30_44",
            "sex": "male",
            "affected_side": "right",
            "notes": "",
        },
    )
    participant_id = created.json()["id"]

    calibration_object = new_object_name("calibration", CLINICIAN.uid, participant_id)
    objects.put(calibration_object, _calibration_bytes())
    calibrated = client.post(
        "/v1/calibrations",
        json={"participant_id": participant_id, "object_name": calibration_object},
    )
    assert calibrated.status_code == 201, calibrated.text

    session_object = new_object_name("session", CLINICIAN.uid, participant_id)
    objects.put(session_object, _demo_bytes("Sub10", "session"))
    session_id = client.post(
        "/v1/sessions",
        json={"participant_id": participant_id, "object_name": session_object},
    ).json()["id"]
    client.post(f"/v1/sessions/{session_id}/segment")

    # Each of these collection names appears verbatim in firestore.rules. Reading them back by
    # name is what ties the two together.
    assert store.get(COLLECTIONS.PARTICIPANTS, participant_id) is not None
    assert store.get(COLLECTIONS.SESSIONS, session_id) is not None
    assert store.query(COLLECTIONS.BOUTS, sessionId=session_id), (
        "bouts are not in the top-level 'bouts' collection that firestore.rules protects"
    )
    assert store.query(COLLECTIONS.AUDIT, targetId=session_id), (
        "no audit entry for the session in the top-level 'audit' collection (H3)"
    )


def test_a_bout_document_carries_the_field_the_rules_join_on(client, store, objects):
    """H3's bout rule resolves ownership by ``get()``-ing the parent session via ``sessionId``.

    If a bout were ever written without that field, the rule would fail closed and a clinician
    would silently lose read access to their own bouts -- a failure mode no unit test reaches,
    because the fake store neither enforces nor inspects document shape.
    """
    created = client.post(
        "/v1/participants",
        json={
            "code": "IT-003",
            "age_band": "30_44",
            "sex": "female",
            "affected_side": "left",
            "notes": "",
        },
    )
    participant_id = created.json()["id"]

    calibration_object = new_object_name("calibration", CLINICIAN.uid, participant_id)
    objects.put(calibration_object, _calibration_bytes())
    calibrated = client.post(
        "/v1/calibrations",
        json={"participant_id": participant_id, "object_name": calibration_object},
    )
    assert calibrated.status_code == 201, calibrated.text
    session_object = new_object_name("session", CLINICIAN.uid, participant_id)
    objects.put(session_object, _demo_bytes("Sub10", "session"))
    session_id = client.post(
        "/v1/sessions",
        json={"participant_id": participant_id, "object_name": session_object},
    ).json()["id"]
    client.post(f"/v1/sessions/{session_id}/segment")

    stored = store.query(COLLECTIONS.BOUTS, sessionId=session_id)
    assert stored
    for bout in stored:
        assert bout.get("sessionId") == session_id
    session_doc = store.get(COLLECTIONS.SESSIONS, session_id)
    assert session_doc.get("createdBy") == CLINICIAN.uid, (
        "the rules resolve a bout's owner through the parent session's createdBy"
    )
