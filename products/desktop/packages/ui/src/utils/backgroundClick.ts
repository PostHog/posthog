/**
 * Whether a click that reached a container should hand focus to the input it
 * wraps.
 *
 * Clicking the chrome around an input is meant to focus it. The catch is that
 * releasing a drag-select outside the input looks the same from the container:
 * `click` fires on the nearest common ancestor of press and release, so a
 * selection gesture that ends anywhere outside the input arrives with the
 * container as its target rather than the input. Focusing then would collapse
 * the selection the user just made, so a live selection marks the gesture as a
 * drag rather than a click.
 *
 * @param ignoreSelector elements that answer clicks themselves and should
 * never redirect focus into the input.
 */
export function shouldFocusOnBackgroundClick(
  target: HTMLElement,
  ignoreSelector: string,
): boolean {
  if (target.closest(ignoreSelector)) return false;
  return window.getSelection()?.isCollapsed !== false;
}
