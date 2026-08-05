import { PathsV2Anchor, PathsV2AnchorType, PathsV2Item, PathsV2StepSource } from '~/queries/schema/schema-general'

/** The editor's chart-mode vocabulary: open mode, or an anchored mode by anchor type. */
export type JourneyShape = 'open' | PathsV2AnchorType

/** An anchored shape the user has chosen whose anchor item is not complete yet. While one is
 * pending, the committed query stays untouched, so the chart never runs a half-built anchor. */
export interface PendingAnchor {
    type: PathsV2AnchorType
    event: string | null
}

/**
 * Whether an anchor stays valid under these step sources: its event is one of them, and it carries
 * a label exactly when the source names by a property. Mirrors the server's ValidateAnchor, which
 * rejects the query outright — a surviving-but-wrong anchor would 400 every run of a saved insight.
 */
export function anchorSurvivesStepSources(anchor: PathsV2Anchor, stepSources: PathsV2StepSource[]): boolean {
    const source = stepSources.find(({ event }) => event === anchor.item.event)
    return !!source && !!source.namingProperty === (anchor.item.label != null)
}

// The backend matches excluded items on (event, label or ''), collapsing null and missing labels.
function itemTupleKey(item: PathsV2Item): string {
    return JSON.stringify([item.event, item.label ?? ''])
}

/** The exclude list without items deriving to the anchor, which the server rejects as a pair. */
export function exclusionsWithoutAnchor(
    excludedItems: PathsV2Item[],
    anchor: PathsV2Anchor
): { items: PathsV2Item[]; removed: boolean } {
    const anchorKey = itemTupleKey(anchor.item)
    const items = excludedItems.filter((item) => itemTupleKey(item) !== anchorKey)
    return { items, removed: items.length !== excludedItems.length }
}
