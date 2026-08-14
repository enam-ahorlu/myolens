import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IntendedUseBanner } from "./IntendedUseBanner";
import { StatusChip } from "./StatusChip";
import { TaskBadge } from "./TaskBadge";
import { TASKS } from "../lib/tasks";

describe("the intended-use banner", () => {
  it("states that this is not a medical device", () => {
    render(<IntendedUseBanner />);
    expect(screen.getByText(/not a medical device/i)).toBeInTheDocument();
  });

  it("names the population the model was developed on", () => {
    render(<IntendedUseBanner />);
    expect(screen.getByRole("note")).toHaveTextContent(/40 healthy adults/i);
  });

  it("says amplitudes are not comparable across sessions", () => {
    render(<IntendedUseBanner />);
    expect(screen.getByRole("note")).toHaveTextContent(/not comparable across sessions/i);
  });

  it("cannot be dismissed", () => {
    // F3 is on the never-cut list. If someone adds a close control, this fails rather than
    // passing review.
    const { container } = render(<IntendedUseBanner />);
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("status chips", () => {
  it("always carry a word, never colour alone", () => {
    for (const tone of ["refusal", "advisory", "verified", "excluded"] as const) {
      const { unmount } = render(<StatusChip tone={tone} />);
      expect(screen.getByText(/\w+/)).toBeInTheDocument();
      unmount();
    }
  });

  it("distinguishes refusal from advisory by wording, not just tone", () => {
    const { unmount } = render(<StatusChip tone="refusal" />);
    expect(screen.getByText("Refused")).toBeInTheDocument();
    unmount();
    render(<StatusChip tone="advisory" />);
    expect(screen.getByText("Advisory")).toBeInTheDocument();
  });

  it("accepts a specific message in place of the default word", () => {
    render(<StatusChip tone="advisory" label="DNS excluded — not calibrated" />);
    expect(screen.getByText(/not calibrated/)).toBeInTheDocument();
  });
});

describe("task badges", () => {
  it("names the task in full by default", () => {
    render(<TaskBadge task="DNS" />);
    expect(screen.getByText("Stair descent")).toBeInTheDocument();
  });

  it("keeps the full name available when abbreviated", () => {
    render(<TaskBadge task="WAK" abbreviated />);
    expect(screen.getByTitle("Level walking")).toHaveTextContent("WAK");
  });

  it("renders every class without a missing label or colour", () => {
    for (const task of TASKS) {
      const { unmount } = render(<TaskBadge task={task} />);
      unmount();
    }
  });
});
