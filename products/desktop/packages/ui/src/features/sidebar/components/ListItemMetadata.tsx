import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import {
  type ListItemMetadataField,
  type ListItemMetadataSegment,
  listItemMetadataSegments,
  taskMetadataSegments,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import { Fragment, type ReactNode } from "react";

/**
 * The second row under a session's name, or nothing where the reader chose no
 * fields. Returns the node rather than exporting a component, because a row's
 * height turns on whether it has a second row: a component always hands
 * `SidebarItem` something truthy, and every row grows a blank line.
 *
 * The parts are spans rather than one joined string so a segment can carry what
 * its short form hides — the exact moment behind "2h ago". A native `title`
 * rather than a tooltip component: a list draws dozens of these, and the
 * browser's own costs nothing.
 */
export function listItemMetadata(
  segments: readonly ListItemMetadataSegment[],
): ReactNode | undefined {
  if (segments.length === 0) return undefined;
  return segments.map((segment, index) => (
    // The separator sits outside the titled span: it belongs to neither
    // segment, and inside one it would split the segment's own text.
    <Fragment key={segment.field}>
      {index > 0 ? " · " : null}
      <span title={segment.title}>{segment.text}</span>
    </Fragment>
  ));
}

/** The Code sidebar's rows, which hold a `TaskData`. */
export function taskMetadata(
  task: Pick<
    TaskData,
    "repository" | "branchName" | "linkedBranch" | "lastActivityAt"
  >,
  creatorName: string | undefined,
  fields: readonly ListItemMetadataField[],
): ReactNode | undefined {
  return listItemMetadata(taskMetadataSegments(task, creatorName, fields));
}

/** A surface that resolved the values itself, like a space's session list. */
export function metadataFromValues(
  ...args: Parameters<typeof listItemMetadataSegments>
): ReactNode | undefined {
  return listItemMetadata(listItemMetadataSegments(...args));
}
