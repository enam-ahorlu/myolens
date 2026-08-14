import { describe, expect, it } from "vitest";
import {
  CONFIDENCE_OPACITY_FLOOR,
  TASKS,
  TASK_COLOUR_VAR,
  TASK_LABEL,
  byReviewPriority,
  confidenceOpacity,
} from "./tasks";

describe("the frozen class set", () => {
  it("matches the model's output order exactly", () => {
    // Duplicated from the backend on purpose. A mismatch would relabel every bout consistently
    // and silently, which is the worst failure this system could have.
    expect(TASKS).toEqual(["DNS", "STDUP", "UPS", "WAK"]);
  });

  it("has a label and a colour token for every class", () => {
    for (const task of TASKS) {
      expect(TASK_LABEL[task]).toBeTruthy();
      expect(TASK_COLOUR_VAR[task]).toMatch(/^var\(--task-/);
    }
  });

  it("uses design tokens rather than hex values", () => {
    // A hardcoded hex here would route around the palette gate in CI.
    for (const value of Object.values(TASK_COLOUR_VAR)) {
      expect(value).not.toMatch(/#[0-9a-f]{3,8}/i);
    }
  });
});

describe("confidence as opacity", () => {
  it("never draws a bout fainter than the floor", () => {
    // An invisible bout is one the reviewer cannot correct.
    expect(confidenceOpacity(0)).toBe(CONFIDENCE_OPACITY_FLOOR);
    expect(confidenceOpacity(-5)).toBe(CONFIDENCE_OPACITY_FLOOR);
  });

  it("draws a certain bout fully opaque", () => {
    expect(confidenceOpacity(1)).toBeCloseTo(1);
    expect(confidenceOpacity(99)).toBeCloseTo(1);
  });

  it("is monotonic, so fainter always means less certain", () => {
    const steps = [0, 0.25, 0.5, 0.75, 1].map(confidenceOpacity);
    for (let i = 1; i < steps.length; i += 1) {
      expect(steps[i]).toBeGreaterThan(steps[i - 1]);
    }
  });
});

describe("review ordering", () => {
  const bout = (id: string, meanConfidence: number, flags: string[] = []) => ({
    id,
    meanConfidence,
    flags,
  });

  it("puts the least certain bout first, not the earliest", () => {
    const ordered = byReviewPriority([bout("a", 0.95), bout("b", 0.41), bout("c", 0.72)]);
    expect(ordered.map((b) => b.id)).toEqual(["b", "c", "a"]);
  });

  it("surfaces flagged bouts ahead of merely low-confidence ones", () => {
    const ordered = byReviewPriority([bout("low", 0.30), bout("flagged", 0.88, ["dns_wak"])]);
    expect(ordered[0].id).toBe("flagged");
  });

  it("keeps time order between equally uncertain bouts", () => {
    const ordered = byReviewPriority([bout("first", 0.5), bout("second", 0.5)]);
    expect(ordered.map((b) => b.id)).toEqual(["first", "second"]);
  });

  it("does not mutate the input", () => {
    const input = [bout("a", 0.9), bout("b", 0.1)];
    byReviewPriority(input);
    expect(input.map((b) => b.id)).toEqual(["a", "b"]);
  });
});
