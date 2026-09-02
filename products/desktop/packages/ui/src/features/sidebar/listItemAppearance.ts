import { repositoryLabel } from "@posthog/core/sidebar/groupTasks";
import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { formatAbsoluteDateTime, formatRelativeAge } from "@posthog/shared";

export const LIST_ITEM_METADATA_FIELDS = [
  "repository",
  "branch",
  "creator",
  "activity",
] as const;

export type ListItemMetadataField = (typeof LIST_ITEM_METADATA_FIELDS)[number];

export const LIST_ITEM_METADATA_LABELS: Record<ListItemMetadataField, string> =
  {
    repository: "Repository",
    branch: "Branch",
    creator: "Creator",
    activity: "Last activity",
  };

/**
 * One field's value. `title` carries what the short text leaves out, which the
 * row hangs off a tooltip: "2h ago" is what a reader wants at a glance, and the
 * exact moment is what they want when the glance isn't enough.
 */
export interface ListItemMetadataValue {
  text: string;
  title?: string;
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
    const { text, title } =
      typeof value === "string" ? { text: value, title: undefined } : value;
    if (!text.trim()) continue;
    segments.push({ field, text: text.trim(), title });
  }
  return segments;
}

export function taskMetadataSegments(
  task: Pick<
    TaskData,
    "repository" | "branchName" | "linkedBranch" | "lastActivityAt"
  >,
  creatorName: string | undefined,
  fields: readonly ListItemMetadataField[],
): ListItemMetadataSegment[] {
  return listItemMetadataSegments(
    {
      repository: repositoryLabel(task.repository),
      branch: task.linkedBranch ?? task.branchName,
      creator: creatorName,
      activity: activityValue(task.lastActivityAt),
    },
    fields,
  );
}
