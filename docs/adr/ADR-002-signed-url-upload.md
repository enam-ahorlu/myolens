# ADR-002: Upload recordings direct to Cloud Storage via V4 signed URL

**Status** Accepted · **Date** in-window, Phase 2

## Context

Nine channels sampled at roughly 2 kHz is about **9.7 MB per minute of CSV**. The product accepts
sessions up to ten minutes. **Cloud Run caps HTTP/1 request bodies at 32 MB.**

A real session therefore cannot be POSTed to the API. This is not a tuning problem; it is a hard
platform limit that the obvious design violates.

## Decision

The browser requests a V4 signed URL from the API, uploads the object **directly to Cloud
Storage**, and then tells the API the object name. The API reads the object server-side.

## Alternatives considered

**Chunked or resumable upload through the API.** Rejected. It works, but it puts a
hundred-megabyte stream through a container sized for inference, and it means writing and testing
a resumption protocol inside a 48-hour budget.

**Client-side gzip to squeeze under 32 MB.** Rejected as a decision that would have to be
un-made. Gzip does compress these files four- to five-fold, which makes a ten-minute session fit
until someone uploads a less compressible recording, or the cap changes, and the failure
arrives in production rather than in design. Gzip is still *accepted*, as a bandwidth saving; it
is just not load-bearing.

**Raise the limit.** Not available. HTTP/2 on Cloud Run lifts the body cap but changes the
streaming semantics, and the constraint would still bound the design.

## Consequences

**Good.** Uploads scale independently of the service. The API never buffers a large body. The
signed URL is short-lived and scoped to a single object, so the browser gets no standing bucket
access.

**Bad.** The upload path bypasses the API, so **validation cannot happen at upload time**. An
object can land in the bucket and only then be found non-conforming. That is why montage
validation (D3) is specified to run server-side *after* the object lands, and why a rejected
session still leaves an object behind. Orphan objects are a real consequence and are accepted:
a lifecycle rule is the correct fix and is out of scope for this version.

**Also bad.** Signing requires the runtime service account to be able to impersonate itself
(`Service Account Token Creator` on itself) and the IAM Service Account Credentials API to be
enabled. Both are easy to miss, and the failure is a confusing permissions error at runtime
rather than at deploy. Documented in the cloud setup runbook precisely because it cost time once.

**Architectural consequence.** This is why the deployment diagram draws the signed-URL endpoint
as its own node. A reader who does not see it will assume the API proxies uploads and will
mis-size the service.
