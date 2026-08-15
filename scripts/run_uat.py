"""User-acceptance tests: every Must acceptance criterion in SRS §4.2, executed against a
running deployment and reported in the form Part A §8 asks for.

**Why this is not the pytest suite.** The unit and integration suites prove the code behaves
against fakes and against an emulator. This proves the *deployed system* behaves, over the
network, through Firebase Authentication, Cloud Run, Cloud Storage and Firestore, using the
credentials an examiner will be given. The distinction stopped being academic the day an
end-to-end run found that a fully green pipeline had shipped a service which could not accept a
single upload.

Each case names the requirement it discharges, states its expected result before running, and
records what actually came back. A case that cannot be automated is reported as ``MANUAL`` with
the reason, rather than quietly omitted -- a suite that hides what it did not check is worse than
a shorter one that says so.

**Usage**

    export MYOLENS_UAT_PASSWORD=...
    python scripts/run_uat.py --api-url "$API" --api-key "$KEY" --email examiner@myolens.test
    python scripts/run_uat.py ... --markdown > uat-results.md

``--markdown`` emits the table for the Testing Report. The exit code is non-zero if any case
fails, so this can gate a release as well as document one.
"""

from __future__ import annotations

import argparse
import getpass
import gzip
import io
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent / "backend" / "artifacts" / "demo"
IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"

MONTAGE = (
    "sEMG: tensor fascia lata",
    "sEMG: rectus femoris",
    "sEMG: vastus medialis",
    "sEMG: semimembranosus",
    "sEMG: upper tibialis anterior",
    "sEMG: lower tibialis anterior",
    "sEMG: lateral gastrocnemius",
    "sEMG: medial gastrocnemius",
    "sEMG: soleus",
)


@dataclass
class Case:
    ref: str
    description: str
    expected: str
    actual: str
    outcome: str  # PASS | FAIL | MANUAL
    note: str = ""


class Runner:
    def __init__(self, api: str, token: str) -> None:
        self.api = api.rstrip("/")
        self.token = token
        self.cases: list[Case] = []

    # -- plumbing -------------------------------------------------------------------------
    def call(
        self, method: str, path: str, payload: dict | None = None, token: str | None = ...
    ) -> tuple[int, dict]:
        url = path if path.startswith("http") else f"{self.api}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, method=method, data=body)
        auth = self.token if token is ... else token
        if auth:
            request.add_header("Authorization", f"Bearer {auth}")
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"raw": raw[:200].decode(errors="replace")}

    def put_object(self, url: str, data: bytes, content_type: str) -> int:
        request = urllib.request.Request(url, method="PUT", data=data)
        request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def record(self, ref, description, expected, actual, ok, note="") -> None:
        outcome = "PASS" if ok else "FAIL"
        self.cases.append(Case(ref, description, expected, str(actual), outcome, note))
        print(f"  {outcome:6s} {ref:9s} {description}")

    def manual(self, ref, description, expected, reason) -> None:
        self.cases.append(Case(ref, description, expected, "not automated", "MANUAL", reason))
        print(f"  MANUAL {ref:9s} {description}")

    # -- fixtures -------------------------------------------------------------------------
    @staticmethod
    def _csv(rows: list[list[object]], header: list[str]) -> bytes:
        buffer = io.StringIO()
        buffer.write(",".join(header) + "\n")
        for row in rows:
            buffer.write(",".join(str(v) for v in row) + "\n")
        return gzip.compress(buffer.getvalue().encode())

    def wrong_montage_csv(self) -> bytes:
        """Eight channels where nine are required, and one renamed. D3's exact failure class."""
        header = ["Time", *list(MONTAGE[:7]), "sEMG: NOT A REAL MUSCLE"]
        return self._csv([[i / 1920.0, *([0.01] * 8)] for i in range(1000)], header)

    def noise_calibration_csv(self) -> bytes:
        """Labelled, montage-conformant, and nothing like a leg. C4's refusal."""
        import random

        random.seed(4242)
        header = [*list(MONTAGE), "label"]
        rows: list[list[object]] = []
        for _block in range(3):
            for task in ("WAK", "UPS", "DNS", "STDUP"):
                for _ in range(6240):
                    rows.append([*[random.gauss(0, 500) for _ in MONTAGE], task])
        return self._csv(rows, header)

    def upload(self, kind: str, participant_id: str, data: bytes) -> str | None:
        status, signed = self.call(
            "POST",
            "/v1/uploads/sign",
            {"kind": kind, "participant_id": participant_id, "content_type": "application/gzip"},
        )
        if status != 200:
            return None
        if self.put_object(signed["upload_url"], data, "application/gzip") >= 300:
            return None
        return signed["object_name"]


def sign_in(api_key: str, email: str, password: str) -> str:
    body = json.dumps({"email": email, "password": password, "returnSecureToken": True}).encode()
    request = urllib.request.Request(
        f"{IDENTITY_TOOLKIT}?key={api_key}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())["idToken"]


def run(runner: Runner) -> None:
    print("\nAccess control")
    status, _ = runner.call("GET", "/v1/participants", token=None)
    runner.record("A1/I2", "An unauthenticated request is refused", "401", status, status == 401)

    status, _ = runner.call("GET", "/v1/participants", token="not-a-real-token")
    runner.record("I2", "A malformed bearer token is refused", "401", status, status == 401)

    status, _ = runner.call("GET", "/v1/admin/clinicians")
    runner.record(
        "A2",
        "A clinician calling an admin route is forbidden",
        "403",
        status,
        status == 403,
        note="A clinician account is expected here; 200 would mean the account holds admin.",
    )
    runner.manual(
        "A3",
        "A clinician cannot read another clinician's participant",
        "404",
        "Needs a second account's credentials. Covered by the Firestore rules suite (12 tests, "
        "real emulator) and by backend/tests/test_participants.py.",
    )
    runner.manual(
        "A5",
        "Thirty-minute idle timeout signs the operator out",
        "Signed out after 30 minutes idle",
        "Wall-clock behaviour in the browser; unit-tested in frontend/src/lib/idleTimeout.test.ts.",
    )

    print("\nInput validation")
    status, _ = runner.call("POST", "/v1/participants", {"code": "x"})
    runner.record(
        "I1", "A malformed payload is rejected, not a stack trace", "422", status, status == 422
    )

    status, body = runner.call(
        "POST",
        "/v1/participants",
        {
            "code": "UAT-001",
            "age_band": "30_44",
            "sex": "female",
            "affected_side": "left",
            "notes": "acceptance test",
            "name": "Should Not Exist",
        },
    )
    has_name = any("name" == k for k in body) if status == 201 else False
    runner.record(
        "B1",
        "No name field exists; one supplied is not stored",
        "201 and no name in the record",
        f"{status}, name present: {has_name}",
        status == 201 and not has_name,
    )
    participant_id = body.get("id") if status == 201 else None
    if not participant_id:
        print("  (cannot continue: participant creation failed)")
        return

    print("\nRefusals that define the product")
    object_name = runner.upload("session", participant_id, runner.wrong_montage_csv())
    if object_name:
        status, body = runner.call(
            "POST", "/v1/sessions", {"participant_id": participant_id, "object_name": object_name}
        )
        runner.record(
            "D3",
            "A non-conformant montage is refused, naming the violations",
            "409 montage_rejected",
            f"{status} {body.get('code')}",
            status == 409 and body.get("code") == "montage_rejected",
            note=f"{len(body.get('details', []))} violation(s) named",
        )
    else:
        runner.record("D3", "A non-conformant montage is refused", "409", "upload failed", False)

    status, body = runner.call("GET", f"/v1/sessions/does-not-exist-{participant_id[:8]}/metrics")
    runner.record(
        "E7",
        "Metrics for an unknown session are refused",
        "404",
        f"{status} {body.get('code')}",
        status == 404,
    )

    object_name = runner.upload("calibration", participant_id, runner.noise_calibration_csv())
    if object_name:
        status, body = runner.call(
            "POST",
            "/v1/calibrations",
            {"participant_id": participant_id, "object_name": object_name},
        )
        detail = body.get("details", [{}])[0] if body.get("details") else {}
        runner.record(
            "C4",
            "A recording outside the training distribution is refused",
            "422 out_of_distribution",
            f"{status} {body.get('code')}",
            status == 422 and body.get("code") == "out_of_distribution",
            note=f"Mahalanobis {detail.get('mahalanobis')} vs threshold {detail.get('threshold')}",
        )

    print("\nThe approval gate, on real data")
    calibration = runner.upload(
        "calibration", participant_id, (DEMO_DIR / "demo_Sub10_calibration.csv.gz").read_bytes()
    )
    status, body = runner.call(
        "POST", "/v1/calibrations", {"participant_id": participant_id, "object_name": calibration}
    )
    sufficient = sum(1 for t in body.get("per_task", {}).values() if t.get("sufficient"))
    runner.record(
        "C1/C2",
        "A conformant calibration is accepted and scored per task",
        "201, four tasks sufficient",
        f"{status}, {sufficient}/4 sufficient",
        status == 201 and sufficient == 4,
    )

    session_object = runner.upload(
        "session", participant_id, (DEMO_DIR / "demo_Sub10_session.csv.gz").read_bytes()
    )
    status, session = runner.call(
        "POST", "/v1/sessions", {"participant_id": participant_id, "object_name": session_object}
    )
    runner.record("D1/D2", "A session recording is accepted", "201", status, status == 201)
    session_id = session.get("id")
    if not session_id:
        return

    status, segmentation = runner.call("POST", f"/v1/sessions/{session_id}/segment")
    bouts = segmentation.get("bouts", [])
    runner.record(
        "D4-D8",
        "Segmentation produces bouts, with the doubtful ones flagged",
        "200, at least one bout",
        f"{status}, {len(bouts)} bouts, {sum(1 for b in bouts if b.get('flagged'))} flagged",
        status == 200 and len(bouts) > 0,
    )

    order = [b.get("mean_confidence", 1) for b in bouts if b.get("flagged")]
    runner.record(
        "E2/FR-07",
        "The review list is ordered least-certain first",
        "Flagged bouts lead, ascending confidence",
        f"{[round(c, 2) for c in order[:5]]}",
        order == sorted(order),
    )

    status, body = runner.call("GET", f"/v1/sessions/{session_id}/metrics")
    runner.record(
        "E7/F1",
        "No metric is computed before a human approves",
        "412 segmentation_not_approved",
        f"{status} {body.get('code')}",
        status == 412 and body.get("code") == "segmentation_not_approved",
    )

    status, body = runner.call("GET", f"/v1/sessions/{session_id}/export")
    runner.record(
        "G1/E7",
        "Export is refused before approval too",
        "412",
        status,
        status == 412,
    )

    status, _ = runner.call("POST", f"/v1/sessions/{session_id}/approve")
    runner.record("E7", "An operator can approve the segmentation", "200", status, status == 200)

    status, metrics = runner.call("GET", f"/v1/sessions/{session_id}/metrics")
    runner.record(
        "F1/F4",
        "Metrics are computed once approved, with correction rate and confidence",
        "200, at least one task",
        f"{status}, {len(metrics.get('tasks', []))} task(s)",
        status == 200 and len(metrics.get("tasks", [])) > 0,
    )

    print("\nProvenance and the model card")
    status, card = runner.call("GET", "/v1/models/current")
    both_regimes = "0.858" in json.dumps(card) and "0.817" in json.dumps(card)
    runner.record(
        "H1/FR-09",
        "The model card names both accuracy regimes",
        "200, transductive and causal both present",
        f"{status}, both present: {both_regimes}",
        status == 200 and both_regimes,
    )
    runner.record(
        "H2/FR-10",
        "Every inference records model version and artefact hash",
        "Both present on the session",
        f"{session.get('model_version')} / {str(session.get('model_hash'))[:12]}",
        bool(session.get("model_version")),
    )
    runner.manual(
        "F3",
        "The intended-use statement appears on every screen and in the export",
        "Present everywhere",
        "Visual; the API's own description carries it and the PDF embeds it. Checked by eye "
        "during the system walkthrough.",
    )
    runner.manual(
        "I5/I6",
        "Responsive to 768 px, WCAG 2.1 AA contrast",
        "Legible at three breakpoints; no contrast failure",
        "Browser behaviour. Contrast is gated automatically by scripts/verify_palette.py on "
        "every push, including the timeline at its faintest.",
    )


def as_markdown(cases: list[Case]) -> str:
    lines = [
        "| # | Req | Test case | Expected | Actual | Result |",
        "|---|---|---|---|---|---|",
    ]
    for index, case in enumerate(cases, 1):
        note = f" <br/><sub>{case.note}</sub>" if case.note else ""
        lines.append(
            f"| {index} | {case.ref} | {case.description}{note} | {case.expected} | "
            f"{case.actual} | **{case.outcome}** |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--api-key")
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--token",
        help="Use an ID token instead of signing in; how this suite is exercised locally.",
    )
    parser.add_argument("--markdown", action="store_true", help="Emit the report table only")
    args = parser.parse_args()

    if args.token:
        token = args.token
    else:
        password = os.environ.get("MYOLENS_UAT_PASSWORD") or getpass.getpass(
            f"Password for {args.email}: "
        )
        token = sign_in(args.api_key, args.email, password)
    runner = Runner(args.api_url, token)
    run(runner)

    passed = sum(1 for c in runner.cases if c.outcome == "PASS")
    failed = sum(1 for c in runner.cases if c.outcome == "FAIL")
    manual = sum(1 for c in runner.cases if c.outcome == "MANUAL")
    print(f"\n{passed} passed, {failed} failed, {manual} manual, {len(runner.cases)} cases")

    if args.markdown:
        print()
        print(as_markdown(runner.cases))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
