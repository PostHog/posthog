import type { ExperimentListSegment } from '@/api/experiments'
import { track } from '@/lib/analytics'

import type { ExperimentStatus } from './experimentModel'

// Typed wrappers for the experiments list events, so every screen sends the same property names and values. The
// detail and action events have their own wrappers next to their screens.

export type ExperimentsChrome = 'tab' | 'stack'
export type ExperimentOpenSource = 'list' | 'link' | 'other'
export type ExperimentsErrorKind = 'list_failed' | 'load_more_failed' | 'row_results_failed'

const OPEN_SOURCES: readonly ExperimentOpenSource[] = ['list', 'link', 'other']

/** The `source` (or older `from`) route param. A link from outside the app arrives without one. */
export function experimentOpenSourceParam(value: string | string[] | undefined): ExperimentOpenSource {
    const first = Array.isArray(value) ? value[0] : value
    return OPEN_SOURCES.find((source) => source === first) ?? 'other'
}

/** Buckets keep the typed text out of analytics. */
export function searchLengthBucket(text: string): '1-2' | '3-5' | '6-10' | '11+' {
    const length = text.trim().length
    if (length <= 2) {
        return '1-2'
    }
    if (length <= 5) {
        return '3-5'
    }
    return length <= 10 ? '6-10' : '11+'
}

export function trackExperimentsOpened(props: { chrome: ExperimentsChrome; segment: ExperimentListSegment }): void {
    track('mobile_experiments_opened', { chrome: props.chrome, segment: props.segment })
}

export function trackExperimentsSegmentChanged(props: { segment: ExperimentListSegment }): void {
    track('mobile_experiments_segment_changed', { segment: props.segment })
}

export function trackExperimentsSearched(props: { text: string; segment: ExperimentListSegment }): void {
    track('mobile_experiments_searched', { length_bucket: searchLengthBucket(props.text), segment: props.segment })
}

export function trackExperimentsRefreshed(props: { segment: ExperimentListSegment }): void {
    track('mobile_experiments_refreshed', { segment: props.segment })
}

export function trackExperimentsErrorShown(props: { kind: ExperimentsErrorKind }): void {
    track('mobile_experiments_error_shown', { kind: props.kind })
}

export function trackExperimentsOpenedInWeb(): void {
    track('mobile_experiments_opened_in_web')
}

export function trackExperimentOpened(props: {
    source: ExperimentOpenSource
    status: ExperimentStatus
    hasResult: boolean
}): void {
    track('mobile_experiment_opened', { source: props.source, status: props.status, has_result: props.hasResult })
}
