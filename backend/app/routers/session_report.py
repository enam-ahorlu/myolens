"""Rendering the PDF export (G1, SRS §4.2 G).

This is presentation code, not domain logic: it formats numbers ``routers.sessions`` has already
computed and gated (via ``_load_or_compute_metrics``) into a document. It lives next to the
router rather than under ``app/domain`` for that reason -- there is no algorithm here that a
test would want to exercise independent of the response models it's built from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

if TYPE_CHECKING:
    from app.domain.bouts import Bout
    from app.domain.calibration_record import CalibrationRecord
    from app.domain.sessions import Session
    from app.routers.sessions import SessionMetricsOut

#: Verbatim copy of ``frontend/src/components/IntendedUseBanner.tsx``'s text. F3 requires the
#: same statement on every screen *and* in the export -- kept in sync by hand, since the two
#: codebases don't share a string table. If one changes, change both.
INTENDED_USE_STATEMENT = (
    "Not a medical device. MyoLens proposes a segmentation for a clinician to review and "
    "correct. It is not for diagnosis, treatment, or clinical decision-making. The model was "
    "developed on 40 healthy adults and has not been validated on any clinical population. "
    "Amplitudes are normalised to this participant's own calibration (%CAL) and are not "
    "comparable across sessions."
)


def _fmt(value: float | None, decimals: int = 1) -> str:
    """A missing metric (a dead calibration channel, or a null CCI) prints as an em dash, never
    as a blank cell or a stray "None" -- G1's "every field populated" means every field has
    *something* legible in it, including an explicit statement that a value doesn't exist."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}"


def _cci_cell(cci: object) -> str:
    value = cci.value  # type: ignore[attr-defined]
    if value is None:
        windows_total = cci.windows_total  # type: ignore[attr-defined]
        return f"null (0/{windows_total} windows qualified)"
    windows_used = cci.windows_used  # type: ignore[attr-defined]
    windows_total = cci.windows_total  # type: ignore[attr-defined]
    return f"{value:.1f} ({windows_used}/{windows_total} windows)"


def render_session_report_pdf(
    *,
    participant_code: str,
    session: Session,
    calibration: CalibrationRecord,
    bouts: list[Bout],
    metrics: SessionMetricsOut,
) -> bytes:
    """G1: participant code, session metadata, segmentation summary, metric tables, model
    version and artefact hash, calibration version, and the intended-use statement -- every
    field the requirement names, in one document."""
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]
    banner_style = ParagraphStyle(
        "IntendedUse",
        parent=body_style,
        borderColor=colors.HexColor("#B4400F"),
        borderWidth=1,
        borderPadding=8,
        backColor=colors.HexColor("#FDF2EC"),
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title=f"MyoLens session report: {session.id}",
    )

    story: list[object] = []
    story.append(Paragraph("MyoLens Segmentation Report", title_style))
    story.append(
        Paragraph(
            f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            body_style,
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph(INTENDED_USE_STATEMENT, banner_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Session", heading_style))
    excluded_count = sum(1 for b in bouts if b.excluded)
    metadata_rows = [
        ["Participant code", participant_code],
        ["Session ID", session.id],
        ["Recorded", f"{session.duration_seconds:.1f} s ({session.sample_count} samples)"],
        ["Status", session.status.value],
        ["Model version", session.model_version or "—"],
        ["Model hash", session.model_hash or "—"],
        ["Calibration version", str(session.calibration_version)],
        ["Calibration difficulty band", calibration.difficulty_band],
        [
            "Segmentation summary",
            (
                f"{len(bouts)} bout(s) total, {excluded_count} excluded, "
                f"{metrics.flagged_count} flagged for review"
            ),
        ],
    ]
    metadata_table = Table(metadata_rows, colWidths=[55 * mm, 110 * mm])
    metadata_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ]
        )
    )
    story.append(metadata_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Metrics — §3.3, approved segmentation only", heading_style))
    if not metrics.tasks:
        story.append(
            Paragraph(
                "No task has an approved, non-excluded bout in this session.",
                body_style,
            )
        )
    for task_metrics in metrics.tasks:
        story.append(Paragraph(task_metrics.task, styles["Heading3"]))

        summary_rows = [
            ["Bouts", str(task_metrics.bout_count)],
            ["Total bout duration", f"{task_metrics.bout_duration_total_s:.1f} s"],
            ["Mean confidence (pre-correction)", f"{task_metrics.model_confidence_mean:.2f}"],
            ["Correction rate", f"{task_metrics.correction_rate_pct:.1f} %"],
            ["CCI (knee: RF+VM vs SM)", _cci_cell(task_metrics.cci_knee)],
            ["CCI (ankle: TA vs LG+MG+SOL)", _cci_cell(task_metrics.cci_ankle)],
        ]
        summary_table = Table(summary_rows, colWidths=[55 * mm, 110 * mm])
        summary_table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 4))

        channel_rows = [["Channel", "Mean %CAL", "Peak %CAL", "Duty cycle %"]]
        for channel, mean, peak, duty in zip(
            metrics.channels,
            task_metrics.amp_mean,
            task_metrics.amp_peak,
            task_metrics.duty_cycle,
            strict=True,
        ):
            channel_rows.append([channel, _fmt(mean), _fmt(peak), _fmt(duty)])
        channel_table = Table(channel_rows, colWidths=[55 * mm, 38 * mm, 38 * mm, 34 * mm])
        channel_table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(channel_table)
        story.append(Spacer(1, 12))

    doc.build(story)
    return buffer.getvalue()
