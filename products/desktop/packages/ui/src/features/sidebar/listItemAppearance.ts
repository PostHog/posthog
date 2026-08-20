import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";

export const LIST_ITEM_METADATA_FIELDS = [
  "repository",
  "branch",
  "creator",
] as const;

export type ListItemMetadataField = (typeof LIST_ITEM_METADATA_FIELDS)[number];

export const LIST_ITEM_METADATA_LABELS: Record<ListItemMetadataField, string> =
  {
    repository: "Repository",
    branch: "Branch",
    creator: "Creator",
  };

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

export function formatListItemMetadata(
  task: Pick<TaskData, "repository" | "branchName" | "linkedBranch">,
  creatorName: string | undefined,
  fields: readonly ListItemMetadataField[],
): string | undefined {
  const repository = task.repository
    ? task.repository.organization
      ? `${task.repository.organization}/${task.repository.name}`
      : task.repository.name
    : undefined;
  const values: Partial<Record<ListItemMetadataField, string | undefined>> = {
    repository,
    branch: task.linkedBranch ?? task.branchName ?? undefined,
    creator: creatorName,
  };
  const visibleValues = fields
    .map((field) => values[field]?.trim())
    .filter((value): value is string => Boolean(value));

  return visibleValues.length > 0 ? visibleValues.join(" · ") : undefined;
}
