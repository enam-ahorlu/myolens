"""Drive the full clinical journey against a running MyoLens, for the three held-out subjects.

Two jobs in one script, deliberately.

**Seeding.** An examiner who signs in to an empty application has been given a login, not a
demonstration. This registers three participants, calibrates each, uploads and segments a
session, and leaves one session approved so the metrics screen (F1/F2) has something on it.

**End-to-end evidence.** Every request is timed and its status recorded, and the run prints a
step-by-step transcript. That transcript is the system-test record: it exercises the deployed
service over the network, through Firebase Authentication, Cloud Storage signed URLs, Cloud Run
and Firestore, in the order a clinician would. A green transcript is a stronger statement than a
screenshot, because it names what was asked and what came back.

Nothing here bypasses the API. Seeding straight into Firestore with the Admin SDK would be
faster and would prove nothing: it would create documents the application itself might refuse,
and would skip precisely the boundaries worth testing (auth, ownership, montage validation, the
out-of-distribution guard, the approval gate).

**Usage**

    export MYOLENS_SEED_PASSWORD=...      # the demo clinician's password
    python scripts/seed_demo_data.py \\
        --api-url https://myolens-api-...run.app \\
        --api-key <Firebase Web API key> \\
        --email demo-clinician@example.com

The Web API key is the browser config value, which Firebase's own documentation classifies as
not secret; the password is read from the environment or prompted for, never passed as an
argument. Create the account first with ``scripts/bootstrap_accounts.py``.

``--dry-run`` prints the plan and touches nothing.

**Not idempotent.** Each run registers three more participants; participant codes are not unique
by design (B1 leaves the clinic to choose them). Run it once against the deployment, and if you
need a clean slate, soft-delete the demo participants from the UI first.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent / "backend" / "artifacts" / "demo"
SUBJECTS = ("Sub10", "Sub13", "Sub22")

#: Pseudonymous, banded, and carrying no name -- B1's schema has no field for one.
PARTICIPANTS = {
    "Sub10": {
        "code": "DEMO-010",
        "age_band": "30_44",
        "sex": "female",
        "affected_side": "left",
    },
    "Sub13": {
        "code": "DEMO-013",
        "age_band": "45_59",
        "sex": "male",
        "affected_side": "right",
    },
    "Sub22": {
        "code": "DEMO-022",
        "age_band": "18_29",
        "sex": "female",
        "affected_side": "right",
    },
}

IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"


@dataclass
class Step:
    name: str
    method: str
    target: str
    status: int
    ms: float
    note: str = ""


@dataclass
class Transcript:
    steps: list[Step] = field(default_factory=list)

    def record(self, *args, **kwargs) -> Step:
        step = Step(*args, **kwargs)
        self.steps.append(step)
        flag = "ok " if 200 <= step.status < 300 else "FAIL"
        suffix = f" -- {step.note}" if step.note else ""
        print(f"  {flag} {step.status:3d}  {step.ms:7.0f} ms  {step.name}{suffix}")
        return step

    @property
    def ok(self) -> bool:
        return all(200 <= s.status < 300 for s in self.steps)


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method=method, data=body)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, str(exc).encode()


def _json(method: str, url: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    status, raw = _request(
        method,
        url,
        token=token,
        body=body,
        content_type="application/json" if payload is not None else None,
    )
    try:
        return status, json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return status, {"raw": raw[:400].decode(errors="replace")}


def sign_in(api_key: str, email: str, password: str) -> str:
    """Exchange email/password for a Firebase ID token, exactly as the browser does."""
    body = json.dumps({"email": email, "password": password, "returnSecureToken": True}).encode()
    status, raw = _request(
        "POST",
        f"{IDENTITY_TOOLKIT}?key={api_key}",
        body=body,
        content_type="application/json",
    )
    if status != 200:
        raise SystemExit(
            f"Sign-in failed ({status}). Check the API key and that the account exists -- "
            f"create it with scripts/bootstrap_accounts.py. Response: {raw[:200]!r}"
        )
    return json.loads(raw)["idToken"]


def _upload(
    api: str,
    token: str,
    kind: str,
    participant_id: str,
    path: Path,
    transcript: Transcript,
) -> str | None:
    """Sign, PUT to the bucket, and return the object name -- D1's direct-to-storage path."""
    started = time.perf_counter()
    status, signed = _json(
        "POST",
        f"{api}/v1/uploads/sign",
        token,
        {
            "kind": kind,
            "participant_id": participant_id,
            "content_type": "application/gzip",
        },
    )
    transcript.record(
        f"sign {kind} upload",
        "POST",
        "/v1/uploads/sign",
        status,
        (time.perf_counter() - started) * 1000,
    )
    if status != 200:
        return None

    started = time.perf_counter()
    put_status, _ = _request(
        "PUT",
        signed["upload_url"],
        body=path.read_bytes(),
        content_type="application/gzip",
    )
    transcript.record(
        f"PUT {kind} to bucket",
        "PUT",
        "signed URL",
        put_status,
        (time.perf_counter() - started) * 1000,
        note=f"{path.stat().st_size // 1024} KB, direct to Cloud Storage (D1)",
    )
    return signed["object_name"] if 200 <= put_status < 300 else None


def seed_subject(api: str, token: str, subject: str, transcript: Transcript, approve: bool) -> None:
    print(f"\n{subject}")
    started = time.perf_counter()
    status, participant = _json(
        "POST",
        f"{api}/v1/participants",
        token,
        {
            **PARTICIPANTS[subject],
            "notes": f"Held-out demonstration subject {subject} (SRS §6).",
        },
    )
    transcript.record(
        "register participant",
        "POST",
        "/v1/participants",
        status,
        (time.perf_counter() - started) * 1000,
        note=PARTICIPANTS[subject]["code"],
    )
    if status != 201:
        return
    participant_id = participant["id"]

    calibration_object = _upload(
        api,
        token,
        "calibration",
        participant_id,
        DEMO_DIR / f"demo_{subject}_calibration.csv.gz",
        transcript,
    )
    if not calibration_object:
        return
    started = time.perf_counter()
    status, calibration = _json(
        "POST",
        f"{api}/v1/calibrations",
        token,
        {"participant_id": participant_id, "object_name": calibration_object},
    )
    sufficiency = calibration.get("per_task", {})
    transcript.record(
        "register calibration",
        "POST",
        "/v1/calibrations",
        status,
        (time.perf_counter() - started) * 1000,
        note=(
            f"{sum(1 for t in sufficiency.values() if t.get('sufficient'))}/4 tasks sufficient "
            f"(C2), Mahalanobis {calibration.get('mahalanobis', float('nan')):.2f} (C4)"
            if status == 201
            else str(calibration)[:160]
        ),
    )
    if status != 201:
        return

    session_object = _upload(
        api,
        token,
        "session",
        participant_id,
        DEMO_DIR / f"demo_{subject}_session.csv.gz",
        transcript,
    )
    if not session_object:
        return
    started = time.perf_counter()
    status, session = _json(
        "POST",
        f"{api}/v1/sessions",
        token,
        {"participant_id": participant_id, "object_name": session_object},
    )
    transcript.record(
        "register session",
        "POST",
        "/v1/sessions",
        status,
        (time.perf_counter() - started) * 1000,
        note=f"{session.get('duration_seconds', 0):.1f} s recording" if status == 201 else "",
    )
    if status != 201:
        return
    session_id = session["id"]

    started = time.perf_counter()
    status, segmentation = _json("POST", f"{api}/v1/sessions/{session_id}/segment", token)
    bouts = segmentation.get("bouts", [])
    transcript.record(
        "segment",
        "POST",
        "/v1/sessions/{id}/segment",
        status,
        (time.perf_counter() - started) * 1000,
        note=(
            f"{len(bouts)} bouts, {sum(1 for b in bouts if b.get('flagged'))} flagged for review"
            if status == 200
            else str(segmentation)[:160]
        ),
    )
    if status != 200:
        return

    # E7: metrics must be refused before approval. Asserted here because a seeded system that
    # silently lost the gate would look perfectly healthy.
    started = time.perf_counter()
    gate_status, _ = _json("GET", f"{api}/v1/sessions/{session_id}/metrics", token)
    transcript.record(
        "metrics before approval must refuse",
        "GET",
        "/v1/sessions/{id}/metrics",
        200 if gate_status == 412 else gate_status,
        (time.perf_counter() - started) * 1000,
        note=f"got {gate_status}, expected 412 -- E7's approval gate",
    )

    if not approve:
        return
    started = time.perf_counter()
    status, _ = _json("POST", f"{api}/v1/sessions/{session_id}/approve", token)
    transcript.record(
        "approve segmentation",
        "POST",
        "/v1/sessions/{id}/approve",
        status,
        (time.perf_counter() - started) * 1000,
    )
    if status != 200:
        return
    started = time.perf_counter()
    status, metrics = _json("GET", f"{api}/v1/sessions/{session_id}/metrics", token)
    transcript.record(
        "metrics after approval",
        "GET",
        "/v1/sessions/{id}/metrics",
        status,
        (time.perf_counter() - started) * 1000,
        note=f"{len(metrics.get('tasks', []))} task(s) reported" if status == 200 else "",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True, help="Base URL of the deployed API")
    parser.add_argument("--api-key", help="Firebase Web API key (browser config value)")
    parser.add_argument("--email", help="Account to sign in as; omit when using --token")
    parser.add_argument(
        "--token",
        help=(
            "Use an ID token directly instead of signing in. Accepts one from the browser's "
            "devtools, and is how this script is exercised against a local server without "
            "standing up Firebase Authentication."
        ),
    )
    parser.add_argument("--subjects", nargs="*", default=list(SUBJECTS), choices=list(SUBJECTS))
    parser.add_argument(
        "--no-approve",
        action="store_true",
        help="Leave every session awaiting review instead of approving the first.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api = args.api_url.rstrip("/")

    if args.dry_run:
        who = args.email or "a supplied token"
        print(f"DRY RUN  would seed {', '.join(args.subjects)} into {api} as {who}")
        for subject in args.subjects:
            for name in ("calibration", "session"):
                path = DEMO_DIR / f"demo_{subject}_{name}.csv.gz"
                print(f"  {'found  ' if path.exists() else 'MISSING'} {path.name}")
        return 0

    if args.token:
        token = args.token
        print("Using the supplied ID token")
    else:
        if not (args.api_key and args.email):
            parser.error("--api-key and --email are required unless --token or --dry-run is used")
        password = os.environ.get("MYOLENS_SEED_PASSWORD") or getpass.getpass(
            f"Password for {args.email}: "
        )
        print(f"Signing in as {args.email}")
        token = sign_in(args.api_key, args.email, password)

    transcript = Transcript()
    started = time.perf_counter()
    status, health = _json("GET", f"{api}/v1/health", token)
    transcript.record(
        "health",
        "GET",
        "/v1/health",
        status,
        (time.perf_counter() - started) * 1000,
        note=f"predictor={health.get('predictor')} classes={health.get('classes')}",
    )

    for index, subject in enumerate(args.subjects):
        seed_subject(api, token, subject, transcript, approve=not args.no_approve and index == 0)

    total = sum(step.ms for step in transcript.steps)
    print(f"\n{len(transcript.steps)} steps, {total / 1000:.1f} s total")
    if transcript.ok:
        print("PASS  every step returned a success status.")
        return 0
    print("FAIL  at least one step did not succeed; see the transcript above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
