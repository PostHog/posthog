import { repositoryLabel } from "@posthog/core/sidebar/groupTasks";
import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import {
  formatAbsoluteDateTime,
  formatRelativeAge,
  type PrCiSummary,
  type PrMergeQueueState,
  type PrPipelineStatus,
} from "@posthog/shared";

export const LIST_ITEM_METADATA_FIELDS = [
  "space",
  "repository",
  "branch",
  "creator",
  "activity",
  "ci",
  "mergeQueue",
] as const;

export type ListItemMetadataField = (typeof LIST_ITEM_METADATA_FIELDS)[number];

export const LIST_ITEM_METADATA_LABELS: Record<ListItemMetadataField, string> =
  {
    space: "Space",
    repository: "Repository",
    branch: "Branch",
    creator: "Creator",
    activity: "Last activity",
    ci: "CI status",
    mergeQueue: "Merge queue",
  };

/** Fields a row can only fill by asking GitHub about the session's PR. */
export const PR_PIPELINE_METADATA_FIELDS: readonly ListItemMetadataField[] = [
  "ci",
  "mergeQueue",
];

/**
 * The mark a status segment carries in front of its text. Named by meaning
 * rather than by icon, so the pure segment logic stays free of React.
 */
export type ListItemMetadataStatus =
  | "ci-running"
  | "ci-failing"
  | "ci-passing"
  | "queue"
  | "queue-problem";

/**
 * One field's value. `title` carries what the short text leaves out, which the
 * row hangs off a tooltip: "2h ago" is what a reader wants at a glance, and the
 * exact moment is what they want when the glance isn't enough.
 */
export interface ListItemMetadataValue {
  text: string;
  title?: string;
  status?: ListItemMetadataStatus;
}

export interface ListItemMetadataSegment extends ListItemMetadataValue {
  field: ListItemMetadataField;
}

export function sanitizeListItemMetadataFields(
  value: unknown,
): ListItemMetadataField[] {
  if (!Array.isArray(value)) return [];

  const knownFields = new Set<string>(LIST_ITEM_METADATA_FIELDS);
  const seen = new Set<ListItemMetadataField>();
  const result: ListItemMetadataField[] = [];

  for (const field of value) {
    if (typeof field !== "string" || !knownFields.has(field)) continue;
    const typedField = field as ListItemMetadataField;
    if (seen.has(typedField)) continue;
    seen.add(typedField);
    result.push(typedField);
  }

  return result;
}

export function moveListItemMetadataField(
  fields: readonly ListItemMetadataField[],
  sourceId: string,
  targetId: string,
): ListItemMetadataField[] {
  const sourceIndex = fields.indexOf(sourceId as ListItemMetadataField);
  const targetIndex = fields.indexOf(targetId as ListItemMetadataField);
  if (sourceIndex === -1 || targetIndex === -1 || sourceIndex === targetIndex) {
    return [...fields];
  }

  const next = [...fields];
  const [source] = next.splice(sourceIndex, 1);
  next.splice(targetIndex, 0, source);
  return next;
}

/** When something last happened, as a phrase with the moment behind it. */
export function activityValue(
  timestamp: number | null | undefined,
): ListItemMetadataValue | undefined {
  if (!timestamp) return undefined;
  return {
    text: formatRelativeAge(timestamp),
    title: formatAbsoluteDateTime(timestamp),
  };
}

/**
 * The second row's parts, from values a surface has already resolved. Lists
 * that hold different session shapes (the Code sidebar's `TaskData`, a space's
 * channel item) share the order this way rather than each deciding it.
 */
export function listItemMetadataSegments(
  values: Partial<
    Record<ListItemMetadataField, ListItemMetadataValue | string | null>
  >,
  fields: readonly ListItemMetadataField[],
): ListItemMetadataSegment[] {
  const segments: ListItemMetadataSegment[] = [];
  for (const field of fields) {
    const value = values[field];
    if (!value) continue;
    const { text, title, status } =
      typeof value === "string"
        ? { text: value, title: undefined, status: undefined }
        : value;
    if (!text.trim()) continue;
    segments.push({ field, text: text.trim(), title, status });
  }
  return segments;
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** CI on the PR's head commit, as one phrase with the counts behind it. */
export function ciValue(
  ci: PrCiSummary | null | undefined,
): ListItemMetadataValue | undefined {
  if (!ci) return undefined;
  const counts = [
    ci.failed > 0 ? `${ci.failed} failed` : null,
    ci.pending > 0 ? `${ci.pending} running` : null,
  ].filter(Boolean);
  const title = counts.length
    ? `${counts.join(", ")} of ${plural(ci.total, "check")}`
    : `${plural(ci.total, "check")}, none failed`;
  switch (ci.state) {
    case "failing":
      return {
        text: plural(ci.failed, "CI failure"),
        title,
        status: "ci-failing",
      };
    case "running":
      return { text: "CI running", title, status: "ci-running" };
    case "passing":
      return { text: "CI passed", title, status: "ci-passing" };
  }
}

const MERGE_QUEUE_VALUES: Record<PrMergeQueueState, ListItemMetadataValue> = {
  queuing: {
    text: "Queuing",
    title:
      "Submitted to the merge queue. It joins the queue when checks and approvals pass.",
    status: "queue",
  },
  queued: {
    text: "In queue",
    title: "In the merge queue, waiting for its turn",
    status: "queue",
  },
  testing: {
    text: "Merging soon",
    title: "The merge queue is testing this pull request",
    status: "queue",
  },
  failed: {
    text: "Queue failed",
    title: "The merge queue could not merge this pull request",
    status: "queue-problem",
  },
  removed: {
    text: "Removed from queue",
    title: "Removed from the merge queue. Submit it again when it is ready.",
    status: "queue-problem",
  },
};

export function mergeQueueValue(
  state: PrMergeQueueState | null | undefined,
): ListItemMetadataValue | undefined {
  return state ? MERGE_QUEUE_VALUES[state] : undefined;
}

export function taskMetadataSegments(
  task: Pick<
    TaskData,
    "repository" | "branchName" | "linkedBranch" | "lastActivityAt"
  >,
  creatorName: string | undefined,
  fields: readonly ListItemMetadataField[],
  spaceName?: string,
  pipeline?: PrPipelineStatus | null,
): ListItemMetadataSegment[] {
  return listItemMetadataSegments(
    {
      space: spaceName,
      repository: repositoryLabel(task.repository),
      branch: task.linkedBranch ?? task.branchName,
      creator: creatorName,
      activity: activityValue(task.lastActivityAt),
      ci: ciValue(pipeline?.ci),
      mergeQueue: mergeQueueValue(pipeline?.mergeQueue),
    },
    fields,
  );
}
