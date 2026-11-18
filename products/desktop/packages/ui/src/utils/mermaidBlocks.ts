export const MERMAID_LANGUAGE = "mermaid";

export function isMermaidCodeBlock(node: unknown): boolean {
  if (typeof node !== "object" || node === null) return false;
  const className = (node as { properties?: { className?: unknown } })
    .properties?.className;
  return (
    Array.isArray(className) &&
    className.includes(`language-${MERMAID_LANGUAGE}`)
  );
}
