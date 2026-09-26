export type PreviewNavigationTarget =
  | { kind: "load"; path: string }
  | { kind: "external"; url: string };

const EXTERNAL_PROTOCOLS = new Set(["http:", "https:"]);

export function resolvePreviewNavigation(
  input: string,
  previewUrl: string,
  currentPath: string,
): PreviewNavigationTarget | null {
  const value = input.trim();
  if (!value) return null;
  let base: URL;
  try {
    base = new URL(currentPath || "/", new URL(previewUrl).origin);
  } catch {
    return null;
  }
  let target: URL;
  try {
    target = new URL(value, base);
  } catch {
    return null;
  }
  if (target.origin === base.origin) {
    return {
      kind: "load",
      path: `${target.pathname}${target.search}${target.hash}`,
    };
  }
  return EXTERNAL_PROTOCOLS.has(target.protocol)
    ? { kind: "external", url: target.toString() }
    : null;
}
