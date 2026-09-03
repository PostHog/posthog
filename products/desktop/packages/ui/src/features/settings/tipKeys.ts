/**
 * Every lesson the app teaches, keyed. The key is what `settingsStore.hints`
 * remembers an answer against, so a key names the lesson rather than the place
 * it is taught from: when the thing it points at moves, change the key here and
 * everyone is offered the lesson once more in its new home.
 *
 * Changing a key is the whole migration. The old key is left behind in a
 * person's saved hints, unread; people who switched tips off stay quiet either
 * way, which is what they asked for.
 */
export const TIP_KEYS = {
  /** Where a session's artifacts land. */
  sessionArtifactsLocation: "session-artifacts-location",
  /** Long pasted text became an inline block. */
  pasteInline: "paste-inline",
  /** Long pasted text became a file attachment. */
  pasteAsFile: "paste-as-file",
  /** Arrow keys walk back through your sent messages. */
  recallMessageNav: "recall-message-nav",
  /** A steered message waits for the run to reach a safe boundary. */
  steerSafeBoundary: "steer-safe-boundary",
} as const;

export type TipKey = (typeof TIP_KEYS)[keyof typeof TIP_KEYS];

/** How a lesson stops offering itself: answered, or out of showings. */
type TipShowings = { max: number };

/**
 * Every lesson's stopping rule, keyed the same way, so it is readable from
 * anywhere rather than only from the call site that teaches it. Settings needs
 * it to tell a tip that has stopped showing from one still waiting to be seen.
 */
export const TIP_SHOWINGS: Record<TipKey, TipShowings> = {
  [TIP_KEYS.sessionArtifactsLocation]: { max: 3 },
  [TIP_KEYS.pasteInline]: { max: 3 },
  [TIP_KEYS.pasteAsFile]: { max: 3 },
  [TIP_KEYS.recallMessageNav]: { max: 3 },
  [TIP_KEYS.steerSafeBoundary]: { max: 1 },
};
