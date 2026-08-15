"""Decoding an uploaded recording's bytes into a DataFrame, with a bound on how much memory
that is allowed to cost.

Shared by both upload paths deliberately. They previously disagreed: ``session_capture`` sniffed
gzip's magic bytes and decompressed, ``calibration_capture`` handed the raw bytes straight to
``pandas``, so the same clinician gzipping the same export succeeded for a session and failed for
a calibration -- and failed with ``unparseable_csv``, a montage rejection, which points at the
wrong thing entirely. C1's acceptance criterion exists to make the two paths behave identically
for "this recording doesn't match the montage"; behaving differently for "this recording is
gzipped" is the same defect wearing a different hat.

The bound is the other half. D2 caps a session at ten minutes, but that cap is expressed in
*samples* and can only be applied once the bytes are already decoded -- which is far too late to
be a defence. Two limits therefore apply before parsing:

* the stored object's size, checked by the router before it downloads anything at all
  (``ObjectStore.size_bytes``), and
* the decompressed size, checked here, because compression ratios of 1000:1 are ordinary for
  repetitive numeric CSV and a 200 KB object can otherwise become gigabytes in memory.

A ten-minute nine-channel recording at 1920 Hz is roughly 104 MB of plain CSV, and D1's
acceptance criterion names a 100 MB upload explicitly, so the ceiling has to sit above that.
"""

from __future__ import annotations

import gzip
import io

import pandas as pd

from app.errors import MontageRejected, UploadTooLarge

#: gzip's magic bytes. Sniffing the content rather than trusting the object name, which a
#: signed-URL upload never validates anyway.
GZIP_MAGIC = b"\x1f\x8b"


def decompress_bounded(raw_bytes: bytes, max_bytes: int) -> bytes:
    """Return the decompressed bytes, or raise :class:`UploadTooLarge` at the ceiling.

    Reads ``max_bytes + 1`` and refuses if it got them: the point is to stop *before* allocating
    an unbounded amount, so the check cannot be "decompress it and then measure it".
    """
    if raw_bytes[: len(GZIP_MAGIC)] != GZIP_MAGIC:
        return raw_bytes
    with gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)) as stream:
        decompressed = stream.read(max_bytes + 1)
    if len(decompressed) > max_bytes:
        raise UploadTooLarge(
            detail=(
                "the uploaded recording expands beyond the maximum accepted size when decompressed"
            ),
            max_bytes=max_bytes,
        )
    return decompressed


def read_upload_frame(raw_bytes: bytes, max_bytes: int) -> pd.DataFrame:
    """Decode CSV, or gzipped CSV, into a DataFrame.

    A parse failure surfaces as :class:`MontageRejected` rather than a 500: an unreadable upload
    is an upload defect the clinician can fix by re-exporting, which is the same class of problem
    as a channel mismatch and belongs in the same 409.
    """
    decoded = decompress_bounded(raw_bytes, max_bytes)
    try:
        return pd.read_csv(io.BytesIO(decoded))
    except Exception as exc:
        raise MontageRejected([{"reason": "unparseable_csv", "detail": str(exc)}]) from exc


__all__ = ["GZIP_MAGIC", "decompress_bounded", "read_upload_frame"]
