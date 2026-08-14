/**
 * A status chip.
 *
 * Status lives in a different visual register from the task colours: a pale tint behind dark
 * text, always carrying an icon and a word. It is never a large saturated block.
 *
 * That is not a stylistic preference. Seven mutually separable saturated colours do not exist
 * within the dichromatic gamut -- every candidate stair-ascent colour that cleared the other
 * three task fills collided with the verified-green or the advisory-amber. Moving status into a
 * lower-chroma, always-labelled register removes the collision by construction instead of by
 * tuning hexes. See docs/DESIGN_TOKENS.md.
 *
 * The consequence for this component: `label` is required and there is no icon-only variant.
 * Colour never carries the meaning alone.
 */

export type StatusTone = "refusal" | "advisory" | "verified" | "excluded";

const TONE_WORD: Record<StatusTone, string> = {
  refusal: "Refused",
  advisory: "Advisory",
  verified: "Verified",
  excluded: "Excluded",
};

function ToneIcon({ tone }: { tone: StatusTone }) {
  const common = { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": true } as const;
  switch (tone) {
    case "refusal":
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M3.6 3.6l4.8 4.8" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      );
    case "advisory":
      return (
        <svg {...common}>
          <path
            d="M6 1 11.2 10.5H0.8L6 1Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
          <path d="M6 4.6v2.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      );
    case "verified":
      return (
        <svg {...common}>
          <path
            d="M1.8 6.4l2.6 2.6L10.2 3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "excluded":
      return (
        <svg {...common}>
          <path d="M2 6h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
  }
}

export function StatusChip({ tone, label }: { tone: StatusTone; label?: string }) {
  const text = label ?? TONE_WORD[tone];
  return (
    <span className={`chip chip--${tone}`} data-tone={tone}>
      <ToneIcon tone={tone} />
      <span className="chip__label">{text}</span>
    </span>
  );
}
