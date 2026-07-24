export const isMac =
  typeof navigator !== "undefined" && /Mac/.test(navigator.platform);

export const isWindows =
  typeof navigator !== "undefined" && /Win/.test(navigator.platform);
