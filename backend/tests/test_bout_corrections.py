"""Bout correction domain functions (E3-E6): relabel, exclude, split, merge."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.bouts import (
    Bout,
    ExclusionReason,
    exclude_bout,
    merge_bouts,
    relabel_bout,
    split_bout,
)
from app.domain.windowing import window_time_ms


def _bout(**overrides) -> Bout:
    defaults = dict(
        id=str(uuid4()),
        session_id="s1",
        task="WAK",
        start_window=0,
        end_window=10,
        start_ms=window_time_ms(0)[0],
        end_ms=window_time_ms(9)[1],
        window_count=10,
        mean_confidence=0.8,
        flagged=False,
        flag_reasons=(),
    )
    defaults.update(overrides)
    return Bout(**defaults)


def test_relabel_sets_corrected_and_original_task():
    bout = _bout(task="WAK")
    relabeled = relabel_bout(bout, "STDUP")

    assert relabeled.task == "STDUP"
    assert relabeled.corrected is True
    assert relabeled.original_task == "WAK"


def test_relabeling_to_the_same_task_is_a_no_op():
    bout = _bout(task="WAK")
    result = relabel_bout(bout, "WAK")
    assert result == bout
    assert result.corrected is False


def test_relabel_preserves_the_first_original_task_across_multiple_corrections():
    bout = _bout(task="WAK")
    once = relabel_bout(bout, "STDUP")
    twice = relabel_bout(once, "UPS")

    assert twice.task == "UPS"
    assert twice.original_task == "WAK"  # not "STDUP" -- the model's actual original proposal


def test_relabel_rejects_an_unknown_task():
    bout = _bout(task="WAK")
    with pytest.raises(ValueError):
        relabel_bout(bout, "NOT_A_TASK")


def test_exclude_marks_excluded_and_retains_the_record():
    bout = _bout()
    excluded = exclude_bout(bout, ExclusionReason.ARTEFACT)

    assert excluded.excluded is True
    assert excluded.exclusion_reason == "artefact"
    # The rest of the record survives -- excluding is not deleting.
    assert excluded.task == bout.task
    assert excluded.window_count == bout.window_count


def test_split_produces_two_bouts_with_no_window_lost():
    bout = _bout(start_window=0, end_window=10, window_count=10)
    first, second = split_bout(bout, at_window=4)

    assert first.start_window == 0
    assert first.end_window == 4
    assert first.window_count == 4
    assert second.start_window == 4
    assert second.end_window == 10
    assert second.window_count == 6
    assert first.window_count + second.window_count == bout.window_count
    assert first.id == bout.id  # the earlier half keeps the original id
    assert second.id != bout.id


def test_split_rejects_a_boundary_outside_the_bout():
    bout = _bout(start_window=0, end_window=10)
    with pytest.raises(ValueError):
        split_bout(bout, at_window=0)  # would leave the first half empty
    with pytest.raises(ValueError):
        split_bout(bout, at_window=10)  # would leave the second half empty
    with pytest.raises(ValueError):
        split_bout(bout, at_window=20)  # outside the bout entirely


def test_merge_combines_adjacent_same_task_bouts():
    first = _bout(start_window=0, end_window=5, window_count=5, mean_confidence=0.6, task="STDUP")
    second = _bout(
        start_window=5, end_window=15, window_count=10, mean_confidence=0.9, task="STDUP"
    )

    merged = merge_bouts(first, second)

    assert merged.start_window == 0
    assert merged.end_window == 15
    assert merged.window_count == 15
    # Weighted average: (0.6*5 + 0.9*10) / 15
    assert merged.mean_confidence == pytest.approx((0.6 * 5 + 0.9 * 10) / 15)


def test_merge_unions_flag_reasons_rather_than_dropping_them():
    first = _bout(
        start_window=0, end_window=5, window_count=5, flagged=True, flag_reasons=("low_confidence",)
    )
    second = _bout(
        start_window=5,
        end_window=10,
        window_count=5,
        flagged=True,
        flag_reasons=("dns_wak_margin",),
    )

    merged = merge_bouts(first, second)

    assert merged.flagged is True
    assert set(merged.flag_reasons) == {"low_confidence", "dns_wak_margin"}


def test_merge_rejects_different_tasks():
    first = _bout(start_window=0, end_window=5, task="WAK")
    second = _bout(start_window=5, end_window=10, task="STDUP")
    with pytest.raises(ValueError, match="same task"):
        merge_bouts(first, second)


def test_merge_rejects_non_adjacent_bouts():
    first = _bout(start_window=0, end_window=5, task="WAK")
    second = _bout(start_window=8, end_window=12, task="WAK")
    with pytest.raises(ValueError, match="not adjacent"):
        merge_bouts(first, second)
