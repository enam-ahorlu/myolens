import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BoutOut } from "../lib/api";
import { SessionTimeline } from "./SessionTimeline";

function bout(overrides: Partial<BoutOut>): BoutOut {
  return {
    id: "b1",
    task: "WAK",
    start_ms: 0,
    end_ms: 1000,
    window_count: 4,
    mean_confidence: 0.9,
    flagged: false,
    flag_reasons: [],
    excluded: false,
    exclusion_reason: null,
    corrected: false,
    original_task: null,
    ...overrides,
  };
}

describe("SessionTimeline (E1)", () => {
  it("renders one segment per bout, positioned by its share of the session duration", () => {
    const bouts = [
      bout({ id: "a", task: "WAK", start_ms: 0, end_ms: 1000 }),
      bout({ id: "b", task: "DNS", start_ms: 1000, end_ms: 4000, mean_confidence: 0.4 }),
    ];
    render(<SessionTimeline bouts={bouts} />);

    const track = screen.getByRole("list", { name: /segmentation timeline/i });
    const segments = track.querySelectorAll(".timeline-bout");
    expect(segments).toHaveLength(2);
    // Total duration is 4000ms (the later bout's end_ms): the first bout is the first quarter.
    expect((segments[0] as HTMLElement).style.left).toBe("0%");
    expect((segments[0] as HTMLElement).style.width).toBe("25%");
    expect((segments[1] as HTMLElement).style.left).toBe("25%");
  });

  it("colours each segment by task and fades it by confidence", () => {
    render(
      <SessionTimeline
        bouts={[bout({ id: "a", task: "DNS", mean_confidence: 0.5, end_ms: 1000 })]}
      />,
    );

    const segment = document.querySelector(".timeline-bout") as HTMLElement;
    expect(segment.style.backgroundColor).toBe("var(--task-dns)");
    // confidenceOpacity(0.5) = 0.70 + 0.30*0.5 = 0.85. The floor is 0.70 rather than 0.42
    // because below it a bout fails WCAG 1.4.11 against the track -- see lib/tasks.ts.
    expect(segment.style.opacity).toBe("0.85");
  });

  it("marks a flagged bout distinctly from an unflagged one", () => {
    render(
      <SessionTimeline
        bouts={[
          bout({ id: "flagged", flagged: true, flag_reasons: ["low_confidence"], end_ms: 1000 }),
        ]}
      />,
    );

    expect(document.querySelector(".timeline-bout--flagged")).toBeInTheDocument();
  });

  it("marks an excluded bout distinctly, without opacity carrying its own meaning there", () => {
    render(
      <SessionTimeline
        bouts={[bout({ id: "excluded", excluded: true, exclusion_reason: "artefact", end_ms: 1000 })]}
      />,
    );

    const segment = document.querySelector(".timeline-bout--excluded") as HTMLElement;
    expect(segment).toBeInTheDocument();
    expect(segment.style.opacity).toBe("");
  });

  it("renders nothing for an empty bout list", () => {
    const { container } = render(<SessionTimeline bouts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  // Regression guard. The track used to be role="img", which collapses it to a leaf in the
  // accessibility tree and silently discards every child's aria-label -- so the per-bout labels
  // below existed in the markup and reached nobody. A test asserting only that the container
  // has an accessible name passed happily throughout. This one asserts the children.
  it("exposes every bout to assistive technology, not just the track", () => {
    render(
      <SessionTimeline
        bouts={[
          bout({ id: "a", task: "WAK", start_ms: 0, end_ms: 1000, mean_confidence: 0.9 }),
          bout({ id: "b", task: "DNS", start_ms: 1000, end_ms: 2000, mean_confidence: 0.4 }),
        ]}
      />,
    );

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveAccessibleName(/level walking/i);
    expect(items[1]).toHaveAccessibleName(/stair descent/i);
    expect(items[1]).toHaveAccessibleName(/40% confidence/i);
  });
});
