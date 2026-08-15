# Infrastructure that is not the container

## `storage-cors.json` — why the bucket needs a CORS policy at all

ADR-002 puts the recording on the bucket directly: the backend mints a V4 signed URL and the
browser `PUT`s to `storage.googleapis.com` itself, so a hundred-megabyte capture never passes
through Cloud Run. That is the right call for cost and for request timeouts, and it has one
consequence that is easy to miss — **the upload is a cross-origin request**, from
`https://myolens.web.app` to `storage.googleapis.com`. A Cloud Storage bucket has no CORS
configuration by default, so the preflight comes back `200` with no `Access-Control-Allow-Origin`
header and the browser refuses to send the `PUT`.

Nothing below an end-to-end test in a real browser can see this:

- the unit and integration suites substitute a fake object store;
- `scripts/seed_demo_data.py` uploads from Python, which has no same-origin policy, so it passes;
- `scripts/run_uat.py` does the same;
- the deploy job's own signing probe checks that the *route* answers, not that a browser could
  use the URL it returns.

All seven CI jobs were green, 261 backend and 88 front-end tests passed, and the deployed product
could not accept a single file from a clinician. It was found by signing in to the live
application as the examiner and pressing Upload.

`origin` lists the two Firebase Hosting domains and the Vite dev server. `responseHeader` has to
name `Content-Type` because the signed URL signs `content-type;host` — the browser sends that
header on the `PUT`, so the preflight must be told it is allowed. `PUT` is the upload; `GET`/`HEAD`
cost nothing and keep a future in-browser read from repeating this discovery.

## How it is applied

The `Deploy to Cloud Run` job applies it on every push to `main` (`gcloud storage buckets update
--cors-file`), then asserts the policy is live by issuing a real preflight and failing the build
if `Access-Control-Allow-Origin` does not come back. Applying without checking would have been
the same mistake one level up: a step that runs is not a policy that works.

The deployer service account needs `roles/storage.admin` (or at minimum
`storage.buckets.update`) on the bucket for the update to succeed.
