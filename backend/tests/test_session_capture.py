"""Parsing an uploaded session recording (D2/D3)."""

from __future__ import annotations

import gzip
import io

import numpy as np
import pandas as pd
import pytest

from app.domain.montage import MONTAGE
from app.domain.session_capture import parse_session_csv
from app.errors import MontageRejected, SessionTooLong

RNG = np.random.default_rng(99)


def _csv_bytes(n_samples: int = 2000, *, gzip_it: bool = False) -> bytes:
    signal = RNG.normal(0.0, 50.0, size=(n_samples, len(MONTAGE)))
    frame = pd.DataFrame(signal, columns=list(MONTAGE))
    frame.insert(0, "Time", np.arange(n_samples) / 1920.0)
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    raw = buffer.getvalue()
    return gzip.compress(raw) if gzip_it else raw


def test_parses_a_well_formed_csv():
    signal = parse_session_csv(_csv_bytes(2000))
    assert signal.shape == (2000, len(MONTAGE))


def test_parses_a_gzipped_csv():
    signal = parse_session_csv(_csv_bytes(2000, gzip_it=True))
    assert signal.shape == (2000, len(MONTAGE))


def test_rejects_a_montage_mismatch():
    frame = pd.DataFrame(RNG.normal(size=(100, 3)), columns=["a", "b", "c"])
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)

    with pytest.raises(MontageRejected):
        parse_session_csv(buffer.getvalue())


def test_rejects_a_recording_beyond_the_ten_minute_cap(monkeypatch: pytest.MonkeyPatch):
    # exceeds_duration_cap reads windowing.MAX_SESSION_SECONDS as a module global at call time,
    # so patching it here (rather than generating an actual 10-minute, ~1.15M-row CSV) keeps
    # this test fast without touching the real frozen cap anywhere else.
    monkeypatch.setattr("app.domain.windowing.MAX_SESSION_SECONDS", 1)
    too_long = 2 * 1920  # 2 seconds, beyond the patched 1-second cap
    with pytest.raises(SessionTooLong):
        parse_session_csv(_csv_bytes(too_long))


def test_rejects_unparseable_bytes():
    with pytest.raises(MontageRejected):
        parse_session_csv(b"not a csv at all \x00\x01\x02")
