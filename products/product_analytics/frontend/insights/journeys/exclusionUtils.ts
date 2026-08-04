import { PathsV2Item, PathsV2StepSource } from '~/queries/schema/schema-general'

/** Whether an excluded item is editable through a source's exclusion row: it targets a current
 * naming-property source and carries the label pinning which item it is. */
function isEditableThrough(item: PathsV2Item, source: PathsV2StepSource): boolean {
    return !!source.namingProperty && source.event === item.event && item.label != null
}

/** The excluded labels of one naming-property source, in exclude-list order. */
export function excludedLabelsForSource(excludedItems: PathsV2Item[], source: PathsV2StepSource): string[] {
    return excludedItems.filter((item) => isEditableThrough(item, source)).map((item) => item.label as string)
}

/** Replace one source's excluded labels, leaving every other exclusion untouched. */
export function withExcludedLabels(
    excludedItems: PathsV2Item[],
    source: PathsV2StepSource,
    labels: string[]
): PathsV2Item[] {
    return [
        ...excludedItems.filter((item) => !isEditableThrough(item, source)),
        ...labels.map((label) => ({ event: source.event, label })),
    ]
}

/** Exclusions no exclusion row can edit: their event is not a current naming-property source, or
 * they carry no label. The backend keeps them inert, so they surface as removable chips instead of
 * silently sticking to the query. */
export function staleExcludedItems(excludedItems: PathsV2Item[], stepSources: PathsV2StepSource[]): PathsV2Item[] {
    return excludedItems.filter((item) => !stepSources.some((source) => isEditableThrough(item, source)))
}
