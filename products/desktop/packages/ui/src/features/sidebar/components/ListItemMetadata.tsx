import { CheckCircle, Queue, XCircle } from "@phosphor-icons/react";
import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import type { PrPipelineStatus } from "@posthog/shared";
import {
  type ListItemMetadataField,
  type ListItemMetadataSegment,
  type ListItemMetadataStatus,
  listItemMetadataSegments,
  taskMetadataSegments,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { Fragment, type ReactNode } from "react";

const MARK_CLASS = "mr-0.5 inline-block align-[-1px]";

/** The mark in front of a status segment, coloured by what it means. */
const STATUS_MARKS: Record<
  ListItemMetadataStatus,
  { mark: ReactNode; className: string }
> = {
  // Hidden from assistive tech: the text beside it already says "CI running",
  // and a list of status roles would announce every row.
  "ci-running": {
    mark: (
      <Spinner
        size="xs"
        role="presentation"
        aria-hidden="true"
        className={MARK_CLASS}
      />
    ),
    className: "text-amber-11",
  },
  "ci-failing": {
    mark: <XCircle size={10} className={MARK_CLASS} />,
    className: "text-red-11",
  },
  "ci-passing": {
    mark: <CheckCircle size={10} className={MARK_CLASS} />,
    className: "text-green-11",
  },
  queue: {
    mark: <Queue size={10} className={MARK_CLASS} />,
    className: "text-violet-11",
  },
  "queue-problem": {
    mark: <Queue size={10} className={MARK_CLASS} />,
    className: "text-red-11",
  },
};

/**
 * A segment's text, behind its status mark where it has one. The mark is an
 * inline box rather than a flex child, so the row's ellipsis still cuts the
 * text when the list is narrow.
 */
function segmentContent(segment: ListItemMetadataSegment): ReactNode {
  if (!segment.status) return segment.text;
  const { mark, className } = STATUS_MARKS[segment.status];
  return (
    <span className={className}>
      {mark}
      {segment.text}
    </span>
  );
}

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
function listItemMetadata(
  segments: readonly ListItemMetadataSegment[],
): ReactNode | undefined {
  if (segments.length === 0) return undefined;
  return segments.map((segment, index) => (
    // The separator sits outside the titled span: it belongs to neither
    // segment, and inside one it would split the segment's own text.
    <Fragment key={segment.field}>
      {index > 0 ? " · " : null}
      <span title={segment.title}>{segmentContent(segment)}</span>
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
  spaceName?: string,
  pipeline?: PrPipelineStatus | null,
): ReactNode | undefined {
  return listItemMetadata(
    taskMetadataSegments(task, creatorName, fields, spaceName, pipeline),
  );
}

/** A surface that resolved the values itself, like a space's session list. */
export function metadataFromValues(
  ...args: Parameters<typeof listItemMetadataSegments>
): ReactNode | undefined {
  return listItemMetadata(listItemMetadataSegments(...args));
}
