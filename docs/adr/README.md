# Architecture decision records

One file per decision that was hard to make and would be expensive to reverse. Each records the
context that forced the choice, the alternatives that were genuinely considered, and the
consequences, including the bad ones.

A decision that had no plausible alternative is not an ADR, it is a fact. Those live in the SRS.

| # | Decision | Status |
|---|---|---|
| [ADR-001](ADR-001-onnx-serving.md) | Serve the models as frozen ONNX graphs behind an interface | Accepted |
| [ADR-002](ADR-002-signed-url-upload.md) | Upload recordings direct to Cloud Storage via V4 signed URL | Accepted |
| [ADR-003](ADR-003-transductive-normalisation.md) | Normalise per session, transductively, over the whole recording | Accepted |
| [ADR-004](ADR-004-app-level-auth.md) | Authenticate at the application, not at the Cloud Run boundary | Accepted |
| [ADR-005](ADR-005-deploy-from-ci.md) | Deploy from GitHub Actions, gated on the full test suite | Accepted |
