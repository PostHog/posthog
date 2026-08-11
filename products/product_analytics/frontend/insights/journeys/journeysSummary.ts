import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PathsV2AnchorType, PathsV2Filter } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { journeyItemLabel } from './journeyGridModel'
import { presetForStepSources } from './stepSourcePresets'

function eventLabel(event: string): string {
    return getCoreFilterDefinition(event, TaxonomicFilterGroupType.Events)?.label ?? event
}

export function journeysSummaryParts(filter: PathsV2Filter | null | undefined): {
    /** Step sources as a phrase: the preset label ("page views"), or the picked events' labels. */
    sources: string
    /** Anchored-mode phrase pieces; null in open mode. */
    anchor: { verb: 'starting' | 'ending'; label: string } | null
} {
    // An empty source list is rejected server-side; treating it like the absent default keeps the
    // pageviews fallback encoded in one place (presetForStepSources).
    const stepSources = filter?.stepSources?.length ? filter.stepSources : undefined
    const preset = presetForStepSources(stepSources)
    const sources = preset
        ? preset.label.toLowerCase()
        : (stepSources ?? []).map((source) => eventLabel(source.event)).join(' and ')
    const anchor = filter?.anchor
    return {
        sources,
        anchor: anchor
            ? {
                  verb: anchor.type === PathsV2AnchorType.End ? 'ending' : 'starting',
                  label: journeyItemLabel(anchor.item),
              }
            : null,
    }
}

/** One-line journeys summary; doubles as the auto-generated insight name. Sync format with PathsV2Summary in InsightDetails. */
export function summarizeJourneys(filter: PathsV2Filter | null | undefined): string {
    const { sources, anchor } = journeysSummaryParts(filter)
    return `Journeys based on ${sources}${anchor ? ` ${anchor.verb} at ${anchor.label}` : ''}`
}
