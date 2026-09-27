const WEB_PROTOCOLS = new Set(["http:", "https:"]);
const LOCAL_HOST_PATTERN = /^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i;

export function resolveBrowserAddress(input: string): string | null {
  const value = input.trim();
  if (!value || /\s/.test(value)) return null;
  const hasScheme =
    /^[a-z][a-z0-9+.-]*:\/\//i.test(value) ||
    /^(javascript|data|file|mailto|about|blob|vbscript|chrome):/i.test(value);
  const withScheme = hasScheme
    ? value
    : `${LOCAL_HOST_PATTERN.test(value) ? "http" : "https"}://${value}`;
  try {
    const url = new URL(withScheme);
    if (!WEB_PROTOCOLS.has(url.protocol) || !url.hostname) return null;
    if (url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function browserTabLabel(url: string, title?: string): string {
  const trimmed = title?.trim();
  if (trimmed) return trimmed;
  try {
    return new URL(url).host || "New tab";
  } catch {
    return "New tab";
  }
}

export function siteName(origin: string): string {
  try {
    const url = new URL(origin);
    return url.protocol === "https:" ? url.host : url.origin;
  } catch {
    return origin;
  }
}

export function originOf(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}
