const OVERLAY_SELECTORS = [
  "[role='dialog']",
  "[role='alertdialog']",
  "[role='menu']",
  "[data-radix-popper-content-wrapper]",
  "[data-overlay]",
].join(",");

export function hasOpenOverlay(): boolean {
  return document.querySelector(OVERLAY_SELECTORS) !== null;
}

export const FOCUSABLE_SELECTOR =
  'button, a, input, textarea, select, [role="button"], [role="link"], [role="combobox"], [role="menuitem"], [contenteditable="true"], [data-interactive]';
