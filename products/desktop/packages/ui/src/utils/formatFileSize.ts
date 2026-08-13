/** Byte count as a short label for artifact and attachment rows. */
export function formatFileSize(size: number | undefined): string | null {
  if (size === undefined) return null;
  if (size < 1_000) return `${size} B`;
  if (size < 1_000_000) return `${Math.round(size / 1_000)} KB`;
  return `${(size / 1_000_000).toFixed(1)} MB`;
}
