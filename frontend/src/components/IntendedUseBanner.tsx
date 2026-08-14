/**
 * The intended-use banner.
 *
 * Present on every screen, below the top bar and above all content. Not a footer, not a modal
 * shown once, not a tooltip, and deliberately **not dismissible** -- there is no close control
 * and no prop to hide it.
 *
 * The reason is simple: a reader who screenshots any single screen of this system and sends it
 * to a colleague sends the disclaimer with it. That is the cheapest available answer to the
 * regulatory question, and it costs about thirty pixels.
 *
 * A test asserts the absence of a dismiss control, so a future "improvement" that adds one
 * fails the build rather than passing review.
 */

export function IntendedUseBanner() {
  return (
    <div className="intended-use" role="note" aria-label="Intended use">
      <svg
        className="intended-use__icon"
        width="16"
        height="16"
        viewBox="0 0 16 16"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="M8 1.5 15 14H1L8 1.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path d="M8 6v4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="8" cy="12" r="0.85" fill="currentColor" />
      </svg>
      <p className="intended-use__text">
        <strong>Not a medical device.</strong> MyoLens proposes a segmentation for a clinician to
        review and correct. It is not for diagnosis, treatment, or clinical decision-making. The
        model was developed on 40 healthy adults and has not been validated on any clinical
        population. Amplitudes are normalised to this participant&rsquo;s own calibration
        (%CAL) and are not comparable across sessions.
      </p>
    </div>
  );
}
