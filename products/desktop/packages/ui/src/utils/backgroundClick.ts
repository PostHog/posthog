// A drag selection can end on container chrome, so preserve any live selection.
export function shouldFocusOnBackgroundClick(
  target: HTMLElement,
  ignoreSelector: string,
): boolean {
  if (target.closest(ignoreSelector)) return false;
  return window.getSelection()?.isCollapsed !== false;
}
