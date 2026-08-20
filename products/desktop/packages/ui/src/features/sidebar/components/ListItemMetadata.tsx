import type { ListItemMetadataSegment } from "@posthog/ui/features/sidebar/listItemAppearance";

/**
 * The second row under a session's name. A row of spans rather than one joined
 * string, because a segment can carry what its short form hides — the exact
 * moment behind "2h ago" — and only a span can hold that tooltip.
 *
 * A native `title` rather than a tooltip component: a list draws dozens of
 * these, and the browser's own is free.
 */
export function ListItemMetadata({
  segments,
}: {
  segments: readonly ListItemMetadataSegment[];
}) {
  if (segments.length === 0) return null;
  return (
    <>
      {segments.map((segment, index) => (
        <span key={segment.field}>
          {index > 0 ? " · " : null}
          <span title={segment.title}>{segment.text}</span>
        </span>
      ))}
    </>
  );
}
