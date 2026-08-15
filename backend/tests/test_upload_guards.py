"""Guards on the upload → register path: C1 byte ceiling, C3 caller binding, C4 validation,
C2 rate limiting (SRS §4.2 C, D, I1, I3).

The property under test is that an ``object_name`` in a request body proves something. Before
these guards it proved nothing: it was a free string handed straight to ``ObjectStore.read_bytes``,
so a caller could name any object in the bucket, and ``MontageRejected`` -- which reports the
column headers it actually found -- would read the first line of it back to them. Object names
embed a ``uuid4``, so guessing someone else's was infeasible in practice. These tests exist
because "infeasible in practice" is not the answer one wants to give about an authorisation
boundary that costs three string comparisons.

``_never_read`` is the assertion that matters most in this file: several of these cases must be
refused *before* anything is downloaded, and a test that only checked the status code would pass
just as happily if the object were read first and rejected afterwards.
"""

from __future__ import annotations

import gzip
import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.adapters.firestore_repo import COLLECTIONS, get_document_store
from app.adapters.storage import get_object_store, new_object_name, parse_object_name
from app.auth import CurrentUser, get_current_user
from app.domain.montage import MONTAGE
from app.domain.participants import AffectedSide, AgeBand, Sex, new_participant
from app.main import app
from app.middleware.rate_limit import (
    BUCKET_SEGMENT,
    BUCKET_SESSION_CREATE,
    BUCKET_UPLOAD_SIGN,
    InProcessRateLimiter,
    get_rate_limiter,
)
from tests.fakes import FakeDocumentStore

CLINICIAN_A = CurrentUser(uid="clinician-a", email="a@clinic.example", role="clinician")
CLINICIAN_B = CurrentUser(uid="clinician-b", email="b@clinic.example", role="clinician")

RNG = np.random.default_rng(90210)


class RecordingObjectStore:
    """A fake that remembers whether anything was ever *read* from it.

    The distinction between "refused" and "refused before the download" is the entire point of
    C1, and only this store can tell the two apart.
    """

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._sizes: dict[str, int] = {}
        self.reads: list[str] = []

    def put(self, object_name: str, data: bytes, declared_size: int | None = None) -> None:
        self._objects[object_name] = data
        self._sizes[object_name] = declared_size if declared_size is not None else len(data)

    def signed_upload_url(self, object_name: str, content_type: str) -> str:
        return f"https://fake-bucket.example/{object_name}"

    def read_bytes(self, object_name: str) -> bytes:
        self.reads.append(object_name)
        return self._objects[object_name]

    def size_bytes(self, object_name: str) -> int | None:
        return self._sizes.get(object_name)


def _session_csv(n_samples: int = 6000) -> bytes:
    signal = RNG.normal(0.0, 50.0, size=(n_samples, len(MONTAGE)))
    frame = pd.DataFrame(signal, columns=list(MONTAGE))
    frame.insert(0, "Time", np.arange(n_samples) / 1920.0)
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


def _client_as(
    user: CurrentUser,
    store: FakeDocumentStore,
    objects: RecordingObjectStore,
    limiter: InProcessRateLimiter | None = None,
) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_document_store] = lambda: store
    app.dependency_overrides[get_object_store] = lambda: objects
    app.dependency_overrides[get_rate_limiter] = lambda: (
        limiter or InProcessRateLimiter(limit_per_hour=1000)
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _register_participant(store: FakeDocumentStore, owner: str = "clinician-a") -> str:
    participant = new_participant(
        code="P-001",
        age_band=AgeBand.Y30_44,
        sex=Sex.FEMALE,
        affected_side=AffectedSide.LEFT,
        notes="",
        created_by=owner,
    )
    store.set(COLLECTIONS.PARTICIPANTS, participant.id, participant.to_document())
    return participant.id


def _never_read(objects: RecordingObjectStore) -> None:
    assert objects.reads == [], (
        f"the object was downloaded before being refused: {objects.reads}. The guard has to run "
        "before read_bytes, or it is not a guard."
    )


# --- C4: validation at the boundary that reaches Cloud Storage ---------------------------------


@pytest.mark.parametrize(
    "participant_id",
    [
        "../../etc/passwd",  # traversal-shaped
        "a/b",  # would introduce a path segment
        "with space",
        "dots.are.excluded",  # would introduce an extension
        "",
        "x" * 65,
    ],
)
def test_sign_rejects_a_participant_id_that_could_reshape_the_object_name_i1(participant_id):
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post(
        "/v1/uploads/sign",
        json={"kind": "session", "participant_id": participant_id, "content_type": "text/csv"},
    )
    assert response.status_code == 422


def test_sign_rejects_a_content_type_outside_the_allow_list_i1():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post(
        "/v1/uploads/sign",
        json={"kind": "session", "participant_id": "p1", "content_type": "text/html"},
    )
    assert response.status_code == 422


def test_sign_accepts_the_content_types_a_browser_actually_produces():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    client = _client_as(CLINICIAN_A, store, objects)
    for content_type in ("text/csv", "application/gzip", "application/octet-stream"):
        response = client.post(
            "/v1/uploads/sign",
            json={"kind": "session", "participant_id": "p1", "content_type": content_type},
        )
        assert response.status_code == 200, content_type


# --- C3: the object name is bound to the clinician it was minted for ---------------------------


def test_a_minted_name_carries_the_owner_and_the_participant():
    name = new_object_name("session", "clinician-a", "p1")
    parsed = parse_object_name(name)
    assert parsed.kind == "session"
    assert parsed.owner_uid == "clinician-a"
    assert parsed.participant_id == "p1"


def test_sign_mints_a_name_owned_by_the_caller():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post("/v1/uploads/sign", json={"kind": "session", "participant_id": "p1"})
    assert response.status_code == 200
    assert parse_object_name(response.json()["object_name"]).owner_uid == "clinician-a"


def test_registering_another_clinicians_object_is_a_404_not_a_read():
    """The disclosure oracle, closed. B's object is refused without being opened."""
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    participant_id = _register_participant(store, owner="clinician-a")
    stolen = new_object_name("session", CLINICIAN_B.uid, participant_id)
    objects.put(stolen, _session_csv())

    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": stolen}
    )
    assert response.status_code == 404
    _never_read(objects)


@pytest.mark.parametrize(
    "object_name",
    [
        "../../etc/passwd",
        "session/one.csv",  # the old two-segment shape
        "session/clinician-a/p1/one.txt",  # not a csv
        "backups/clinician-a/p1/one.csv",  # not a kind this API mints
        "session/clinician-a/p1/../../secret.csv",
    ],
)
def test_a_malformed_object_name_is_refused_without_being_read(object_name):
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    participant_id = _register_participant(store)
    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": object_name}
    )
    assert response.status_code == 422
    _never_read(objects)


def test_an_object_minted_for_another_participant_is_refused():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    mine = _register_participant(store)
    theirs = _register_participant(store)
    name = new_object_name("session", CLINICIAN_A.uid, theirs)
    objects.put(name, _session_csv())

    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post("/v1/sessions", json={"participant_id": mine, "object_name": name})
    assert response.status_code == 422
    _never_read(objects)


def test_a_calibration_object_cannot_be_registered_as_a_session():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    participant_id = _register_participant(store)
    name = new_object_name("calibration", CLINICIAN_A.uid, participant_id)
    objects.put(name, _session_csv())

    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": name}
    )
    assert response.status_code == 422
    _never_read(objects)


# --- C1: the byte ceiling, applied before the download -----------------------------------------


def test_an_oversized_object_is_refused_before_it_is_downloaded_c1():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    participant_id = _register_participant(store)
    name = new_object_name("session", CLINICIAN_A.uid, participant_id)
    # Small on disk here, but declared enormous: the router must believe the metadata and refuse,
    # rather than downloading it to find out. D2's ten-minute cap cannot help -- it is expressed
    # in samples and is only reachable after the bytes are already in memory.
    objects.put(name, b"x", declared_size=2 * 1024 * 1024 * 1024)

    client = _client_as(CLINICIAN_A, store, objects)
    response = client.post(
        "/v1/sessions", json={"participant_id": participant_id, "object_name": name}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
    _never_read(objects)


def test_a_gzip_bomb_is_refused_at_the_decompression_ceiling_c1():
    """A small object that expands without bound. The size check passes; this is the second net."""
    from app.domain.csv_upload import decompress_bounded
    from app.errors import UploadTooLarge

    bomb = gzip.compress(b"A" * 50_000_000)
    assert len(bomb) < 100_000, "the fixture should be small compressed, or it proves nothing"
    with pytest.raises(UploadTooLarge):
        decompress_bounded(bomb, max_bytes=1_000_000)


def test_a_recording_within_the_ceiling_still_decodes():
    from app.domain.csv_upload import read_upload_frame

    csv = _session_csv(n_samples=500)
    assert read_upload_frame(csv, max_bytes=100_000_000).shape[0] == 500
    assert read_upload_frame(gzip.compress(csv), max_bytes=100_000_000).shape[0] == 500


def test_gzipped_and_plain_uploads_decode_identically():
    """Regression: the two upload paths handled compression differently.

    ``session_capture`` sniffed gzip and decompressed; ``calibration_capture`` handed the raw
    bytes to pandas, so the same clinician gzipping the same export succeeded for a session and
    failed for a calibration -- with ``unparseable_csv``, a montage rejection, which points at
    the wrong thing entirely. Both now share ``read_upload_frame``.
    """
    from app.domain.csv_upload import read_upload_frame

    csv = _session_csv(n_samples=200)
    plain = read_upload_frame(csv, max_bytes=100_000_000)
    zipped = read_upload_frame(gzip.compress(csv), max_bytes=100_000_000)
    pd.testing.assert_frame_equal(plain, zipped)


# --- C2: the cheap routes are bounded too ------------------------------------------------------


def test_signing_is_rate_limited_on_its_own_bucket_c2():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    limiter = InProcessRateLimiter(limit_per_hour=1000, limits={BUCKET_UPLOAD_SIGN: 2})
    client = _client_as(CLINICIAN_A, store, objects, limiter)

    body = {"kind": "session", "participant_id": "p1"}
    assert client.post("/v1/uploads/sign", json=body).status_code == 200
    assert client.post("/v1/uploads/sign", json=body).status_code == 200
    refused = client.post("/v1/uploads/sign", json=body)
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limited"


def test_session_registration_is_rate_limited_c2():
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    participant_id = _register_participant(store)
    limiter = InProcessRateLimiter(limit_per_hour=1000, limits={BUCKET_SESSION_CREATE: 1})
    client = _client_as(CLINICIAN_A, store, objects, limiter)

    name = new_object_name("session", CLINICIAN_A.uid, participant_id)
    objects.put(name, _session_csv())
    body = {"participant_id": participant_id, "object_name": name}

    assert client.post("/v1/sessions", json=body).status_code == 201
    assert client.post("/v1/sessions", json=body).status_code == 429


def test_the_buckets_do_not_share_a_quota():
    """Exhausting signing must not lock a clinician out of segmenting what they already uploaded.

    One shared counter would make a heavy uploader unable to analyse their own recordings, which
    is the wrong failure: the expensive route is segmentation, and it has its own ceiling.
    """
    limiter = InProcessRateLimiter(
        limit_per_hour=1000, limits={BUCKET_UPLOAD_SIGN: 1, BUCKET_SEGMENT: 1}
    )
    assert limiter.check("u1", bucket=BUCKET_UPLOAD_SIGN)[0] is True
    assert limiter.check("u1", bucket=BUCKET_UPLOAD_SIGN)[0] is False
    # The segmentation bucket is untouched by the above.
    assert limiter.check("u1", bucket=BUCKET_SEGMENT)[0] is True


def test_rate_limits_remain_per_user():
    limiter = InProcessRateLimiter(limit_per_hour=1000, limits={BUCKET_SESSION_CREATE: 1})
    assert limiter.check("clinician-a", bucket=BUCKET_SESSION_CREATE)[0] is True
    assert limiter.check("clinician-a", bucket=BUCKET_SESSION_CREATE)[0] is False
    assert limiter.check("clinician-b", bucket=BUCKET_SESSION_CREATE)[0] is True


# --- deployment configuration -------------------------------------------------------------------


def test_an_unconfigured_bucket_fails_at_construction_not_at_the_first_upload():
    """Regression, and the most expensive defect found in this project.

    ``MYOLENS_STORAGE_BUCKET`` was absent from the Cloud Run deployment, so ``storage_bucket``
    took its empty-string default. The service started, answered ``/v1/health`` with a cheerful
    ``{"status":"ok"}``, served the front end, authenticated users and created participants --
    and returned 500 from every single upload. It had never accepted a recording in production.

    Nothing caught it because every test in this suite substitutes a fake object store, so the
    one line that reads the setting was never executed outside a developer's machine. The store
    now refuses to exist without a bucket, which turns a per-request 500 into a startup failure
    that a deploy cannot ignore.
    """
    from app.adapters.storage import GcsObjectStore

    with pytest.raises(RuntimeError, match="MYOLENS_STORAGE_BUCKET"):
        GcsObjectStore("")


def test_production_refuses_to_start_without_the_storage_configuration():
    """The startup check that would actually have caught the outage.

    The unauthenticated CI probe could not: ``get_current_user`` refuses before the object-store
    dependency is ever constructed, so a request without a token never touches the setting. Only
    a check at start-up turns a missing variable into a revision that fails to become healthy,
    which Cloud Run reports as a failed deploy.
    """
    from app.config import Settings
    from app.main import _require_deployable_configuration

    with pytest.raises(RuntimeError, match="MYOLENS_STORAGE_BUCKET"):
        _require_deployable_configuration(
            Settings(environment="production", storage_bucket="", gcp_project_id="myolens")
        )

    # Development is exempt: a local uvicorn for front-end work has no bucket and needs none.
    _require_deployable_configuration(
        Settings(environment="development", storage_bucket="", gcp_project_id="")
    )
    # A fully configured production deployment passes.
    _require_deployable_configuration(
        Settings(environment="production", storage_bucket="b", gcp_project_id="myolens")
    )


def test_health_does_not_imply_the_service_can_accept_an_upload():
    """The lesson, written down as an assertion.

    ``/v1/health`` reports the predictor, the class set and the montage contract -- everything
    except whether the storage the workflow depends on is reachable. It was green throughout the
    outage above. This test exists so nobody later concludes that a green health check means a
    working system; the deploy job now probes the signing route for that.
    """
    store, objects = FakeDocumentStore(), RecordingObjectStore()
    client = _client_as(CLINICIAN_A, store, objects)
    body = client.get("/v1/health").json()
    assert "storage" not in body
    assert body["status"] == "ok"
