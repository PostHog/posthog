import { PathsV2AnchorType, PathsV2Filter } from '~/queries/schema/schema-general'

import { journeyItemLabel } from './journeyGridModel'
import { STEP_SOURCE_PRESETS, presetForStepSources } from './stepSourcePresets'

export interface JourneysSummaryParts {
    /** Step sources as a phrase: the preset label ("page views"), or the picked event names. */
    sources: string
    /** Anchored-mode phrase pieces; null in open mode. */
    anchor: { verb: 'starting' | 'ending'; label: string } | null
}

export function journeysSummaryParts(filter: PathsV2Filter | null | undefined): JourneysSummaryParts {
    const stepSources = filter?.stepSources
    const preset = presetForStepSources(stepSources ?? undefined)
    const sources = preset
        ? preset.label.toLowerCase()
        : stepSources && stepSources.length > 0
          ? stepSources.map((source) => source.event).join(' and ')
          : // An empty list is rejected server-side; showing the runner's default beats an empty phrase.
            STEP_SOURCE_PRESETS.pageViews.label.toLowerCase()
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
