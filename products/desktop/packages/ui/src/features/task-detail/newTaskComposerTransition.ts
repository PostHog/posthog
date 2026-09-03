/**
 * How long the new-task composer takes to fade out once its task has been
 * submitted, and how long the pending chat takes to fade back in over it.
 */
export const NEW_TASK_COMPOSER_FADE_MS = 160;

/** Resolves once the composer's fade-out has had its full window. */
export function waitForComposerExit(): Promise<void> {
  return new Promise((resolve) =>
    setTimeout(resolve, NEW_TASK_COMPOSER_FADE_MS),
  );
}
