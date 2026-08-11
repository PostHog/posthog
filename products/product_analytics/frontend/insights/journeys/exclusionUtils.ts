import { PathsV2Item, PathsV2StepSource } from '~/queries/schema/schema-general'

/** Whether an excluded item is editable through a source's exclusion row: it targets a current
 * naming-property source with a non-empty label. Empty and missing labels mean the same excluded
 * item, (event, ''), which the chip groups cover instead. */
function isEditableThrough(item: PathsV2Item, source: PathsV2StepSource): boolean {
    return !!source.namingProperty && source.event === item.event && !!item.label
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

export interface ExcludedItemChips {
    /** Exclusions the backend applies but no exclusion row can edit: the (event, '') items, which
     * for a source without a naming property mean the whole event and for one with a naming
     * property mean the item whose property value is missing. */
    active: PathsV2Item[]
    /** Exclusions no derivable item can equal, which the backend keeps inert: their event is not a
     * step source, or they name a label on a source without a naming property. */
    inert: PathsV2Item[]
}

/** Split the exclusions no row edits into chips, mirroring the backend's (event, label or '')
 * matching so the editor never claims an applied exclusion is inert or the other way around. */
export function excludedItemChips(excludedItems: PathsV2Item[], stepSources: PathsV2StepSource[]): ExcludedItemChips {
    const chips: ExcludedItemChips = { active: [], inert: [] }
    for (const item of excludedItems) {
        const source = stepSources.find(({ event }) => event === item.event)
        if (!source) {
            chips.inert.push(item)
        } else if (!item.label) {
            chips.active.push(item)
        } else if (!source.namingProperty) {
            chips.inert.push(item)
        }
        // Otherwise the item is editable through its source's exclusion row.
    }
    return chips
}
