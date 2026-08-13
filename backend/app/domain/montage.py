"""The montage contract.

Nine channels, unilateral, in a fixed order. The contract is enforced by exact string equality
and nothing else.

There is deliberately **no fuzzy matching**. A near-miss on a channel name is far more likely to
be a genuinely different electrode placement than a typo, and the failure mode of guessing is a
silently mis-ordered montage: every metric computes cleanly, every number is wrong, and nothing
in the output looks unusual. A rejection is recoverable in thirty seconds. A silent reordering is
not recoverable at all, because nobody knows to look.

This is also why ENABL3S is not shipped despite being the thesis's second corpus: seven channels
at 1 kHz cannot satisfy this contract, and bending the contract to admit it would make the
contract decorative.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: The nine channels, in the order the feature extractor expects them.
MONTAGE: tuple[str, ...] = (
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

N_CHANNELS = len(MONTAGE)

#: Contract version. Recorded against every inference so that a future montage change is
#: distinguishable from a model change when results are compared.
MONTAGE_CONTRACT_VERSION = "1.0.0"


class MuscleGroup(str, Enum):
    """Functional groupings used by the co-contraction indices."""

    HIP_ABDUCTOR = "hip_abductor"
    KNEE_EXTENSOR = "knee_extensor"
    KNEE_FLEXOR = "knee_flexor"
    DORSIFLEXOR = "dorsiflexor"
    PLANTARFLEXOR = "plantarflexor"


#: Channel indices per group. Indices, not names, because everything downstream is an array.
GROUPS: dict[MuscleGroup, tuple[int, ...]] = {
    MuscleGroup.HIP_ABDUCTOR: (0,),
    MuscleGroup.KNEE_EXTENSOR: (1, 2),
    MuscleGroup.KNEE_FLEXOR: (3,),
    MuscleGroup.DORSIFLEXOR: (4, 5),
    MuscleGroup.PLANTARFLEXOR: (6, 7, 8),
}


class Side(str, Enum):
    """Which leg was recorded. Declared per session, never inferred."""

    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class MontageViolation:
    """One specific, named reason a recording was rejected."""

    reason: str
    expected: str | None = None
    received: str | None = None
    position: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            k: v
            for k, v in {
                "reason": self.reason,
                "expected": self.expected,
                "received": self.received,
                "position": self.position,
            }.items()
            if v is not None
        }


def validate_montage(columns: list[str]) -> list[MontageViolation]:
    """Check a recording's channel columns against the contract.

    Returns every violation found rather than the first, so that a user fixing an export gets
    the whole list in one pass instead of discovering the problems one upload at a time.

    An empty list means the montage conforms.
    """
    violations: list[MontageViolation] = []

    if len(columns) != N_CHANNELS:
        violations.append(
            MontageViolation(
                reason="channel_count",
                expected=str(N_CHANNELS),
                received=str(len(columns)),
            )
        )

    for position, expected in enumerate(MONTAGE):
        if position >= len(columns):
            violations.append(
                MontageViolation(reason="channel_missing", expected=expected, position=position)
            )
            continue
        received = columns[position]
        if received != expected:
            # Distinguish "wrong order" from "unknown channel". The first is a fixable export
            # setting; the second is a different electrode set and is not fixable at all.
            reason = "channel_out_of_order" if received in MONTAGE else "channel_unknown"
            violations.append(
                MontageViolation(
                    reason=reason, expected=expected, received=received, position=position
                )
            )

    for extra in columns[N_CHANNELS:]:
        violations.append(MontageViolation(reason="channel_unexpected", received=extra))

    return violations


def conforms(columns: list[str]) -> bool:
    """True when the columns satisfy the contract exactly."""
    return not validate_montage(columns)
