# ADR-005: Deploy from GitHub Actions, gated on the full test suite

**Status** Accepted · **Date** in-window, Phase 2

## Context

Something has to build the container and put a revision on Cloud Run. The obvious option is
`gcloud run deploy` from the developer's machine.

There is also a local reason: `gcloud` has half-installed twice on this machine, and fighting a
broken local SDK inside a 48-hour window is a poor use of the budget.

## Decision

Deploy from GitHub Actions using `google-github-actions/deploy-cloudrun`, building from source via
Cloud Build. The deploy job **runs only on `main`, and only after the technical-debt register,
palette, backend and front-end jobs have all passed.**

## Alternatives considered

**`gcloud run deploy` from the laptop.** Rejected. It works when it works, but the deployed
revision then has no verifiable relationship to any commit, anyone with the SDK and a key can
ship, and nothing prevents deploying code whose tests fail. It also reads considerably worse
against a Deployment and Maintenance assessment than a pipeline does.

**Deploy on every branch.** Rejected. One service, one environment; a feature-branch deploy would
overwrite the revision an examiner might be looking at.

**Workload Identity Federation instead of a service-account key.** Genuinely better, and the right
answer for anything long-lived, it removes the long-lived credential entirely. Not adopted here
because it is more setup than the window affords for a two-week deployment, and the key is already
provisioned, stored outside OneDrive and outside the repository, and held only as a GitHub secret.
**Recorded as a known weaker choice rather than presented as best practice.**

## Consequences

**Good.** Every revision traces to a commit. Nothing ships whose tests have not passed, the
gating is the point, because a pipeline that can ship an untested revision is an upload button
with extra steps. The test suite has somewhere real to run.

**Verification, not just deployment.** A green deploy step means Cloud Run *accepted* a revision,
not that it works. The job therefore curls `/v1/health` on the deployed URL and fails if the
service reports the wrong class order, the wrong channel count or the wrong sampling rate, which
is what a stale or mis-built image looks like from outside. Deploying and working are different
claims, so they are checked separately.

**What the first deploy taught, recorded rather than tidied away.** The first run of this job
failed with every test job green. The cause was `--require-hashes=false` in the Dockerfile.
`--require-hashes` is a boolean flag, so pip printed its usage banner and exited non-zero. The
image never built. Two changes followed. The backend job now runs `docker build`, because nothing
in a Python test suite executes a Dockerfile and so no amount of test coverage could have caught
it; that also moves the check onto pull requests, which never reach this job. And the deploy job
now dumps the Cloud Build log on failure, because `deploy-cloudrun` reports only "Build failed;
check build logs for details", a message that names the problem's location and nothing else.

**Bad.** A long-lived service-account key exists. It is a GitHub secret, it is not in the
repository, `.gitignore` refuses the filename patterns it would arrive under, and it was piped
into the secret from disk rather than pasted. That is mitigation, not elimination.

**Also bad.** Builds are slower than a local deploy. Cloud Build pulls and installs the dependency
set each time. Accepted; the gating is worth more than the minutes.

## Cost note

`min-instances` is **0** during development and is raised to **1 at submission**, so an examiner
never meets a cold start. `min-instances=1` bills whether or not anyone visits, roughly $15–25 a
month if left running. **Scale it back to zero once the mark is in.**
