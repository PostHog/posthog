import { getSourceProductMeta } from '../components/badges/sourceProductIcons'
import type { InboxSourceSelection } from '../logics/inboxFiltersLogic'
import { SignalSourceProduct } from '../types'
import { prettifyScoutSkillName, scoutDisplayName } from './scoutRunsWindow'

export interface InboxSourceChoice extends InboxSourceSelection {
    label: string
    /** The stored selection names a source or scout that the loaded configuration no longer has. */
    unavailable: boolean
}

export interface InboxSourceChoices {
    sources: InboxSourceChoice[]
    scouts: InboxSourceChoice[]
}

export function sourceProductLabel(sourceProduct: string): string {
    return getSourceProductMeta(sourceProduct)?.label ?? sourceProduct
}

function byLabel(a: InboxSourceChoice, b: InboxSourceChoice): number {
    return a.label.localeCompare(b.label)
}

/**
 * The Source filter choices: one per configured non-scout product, and one per scout config. Paused
 * sources and scouts stay in the list because their old reports still exist. A selected value that the
 * configuration does not contain stays in the list too, so the user can see it and clear it.
 */
export function buildInboxSourceChoices({
    sourceConfigs,
    scoutConfigs,
    sourceProductFilter,
    scoutFilter,
}: {
    sourceConfigs: { source_product: string }[] | null
    scoutConfigs: { skill_name: string; display_name?: string }[] | null
    sourceProductFilter: string[]
    scoutFilter: string[]
}): InboxSourceChoices {
    const configuredProducts = new Set(
        (sourceConfigs ?? [])
            .map((config) => config.source_product)
            .filter((product) => product !== SignalSourceProduct.SignalsScout)
    )
    const sources: InboxSourceChoice[] = [...configuredProducts].map((value) => ({
        kind: 'source_product',
        value,
        label: sourceProductLabel(value),
        unavailable: false,
    }))
    for (const value of sourceProductFilter) {
        if (!configuredProducts.has(value)) {
            sources.push({ kind: 'source_product', value, label: sourceProductLabel(value), unavailable: true })
        }
    }

    const labelCounts = new Map<string, number>()
    for (const config of scoutConfigs ?? []) {
        const label = scoutDisplayName(config)
        labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1)
    }
    const scouts: InboxSourceChoice[] = (scoutConfigs ?? []).map((config) => {
        const label = scoutDisplayName(config)
        return {
            kind: 'scout',
            value: config.skill_name,
            // Two scouts can share a display name. The skill name is unique, so it tells them apart.
            label: (labelCounts.get(label) ?? 0) > 1 ? `${label} (${config.skill_name})` : label,
            unavailable: false,
        }
    })
    const configuredScouts = new Set(scouts.map((scout) => scout.value))
    for (const value of scoutFilter) {
        if (!configuredScouts.has(value)) {
            scouts.push({ kind: 'scout', value, label: prettifyScoutSkillName(value), unavailable: true })
        }
    }

    return { sources: sources.sort(byLabel), scouts: scouts.sort(byLabel) }
}

/**
 * The one choice the stored selection represents, or null. A shared link from the old toolbar can
 * carry several products or scouts, and no single choice represents that.
 */
export function singleInboxSourceSelection(
    sourceProductFilter: string[],
    scoutFilter: string[]
): InboxSourceSelection | null {
    if (sourceProductFilter.length === 1 && scoutFilter.length === 0) {
        return { kind: 'source_product', value: sourceProductFilter[0] }
    }
    if (scoutFilter.length === 1 && sourceProductFilter.length === 0) {
        return { kind: 'scout', value: scoutFilter[0] }
    }
    return null
}

export function matchesInboxSourceSearch(choice: InboxSourceChoice, search: string): boolean {
    const query = search.trim().toLowerCase()
    return !query || choice.label.toLowerCase().includes(query) || choice.value.toLowerCase().includes(query)
}
