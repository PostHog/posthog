/**
 * How long the new-task composer takes to slide from the middle of the page
 * down to where the chat's composer sits, once a task has been submitted.
 */
export const NEW_TASK_COMPOSER_EXIT_MS = 220;

/**
 * Resolves once that slide has had its full window, counted from the moment
 * the submit started. Pre-flight work spent inside the window costs nothing
 * extra, so a slow submit never gets slower than it already was.
 */
export function waitForComposerExit(submitStartedAt: number): Promise<void> {
  const remaining = NEW_TASK_COMPOSER_EXIT_MS - (Date.now() - submitStartedAt);
  if (remaining <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, remaining));
}
