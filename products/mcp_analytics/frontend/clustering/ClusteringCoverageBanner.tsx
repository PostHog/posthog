import { useValues } from 'kea'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { mcpClusteringLogic } from './mcpClusteringLogic'

/**
 * States what the snapshot's sample actually covers so the percentages on this
 * tab are read as sample statistics, not census numbers.
 */
export function ClusteringCoverageBanner(): JSX.Element | null {
    const { snapshot } = useValues(mcpClusteringLogic)
    const meta = snapshot.computed_with

    if (!meta || meta.sampled_sessions === null || meta.sampled_sessions === undefined) {
        return null
    }

    const parts: string[] = []
    if (meta.window_sessions !== null && meta.window_sessions !== undefined) {
        parts.push(
            `Based on ${humanFriendlyNumber(meta.sampled_sessions)} sampled sessions out of ${humanFriendlyNumber(meta.window_sessions)} in the window`
        )
    } else {
        parts.push(`Based on ${humanFriendlyNumber(meta.sampled_sessions)} sampled sessions`)
    }
    if (meta.intent_coverage_pct !== null && meta.intent_coverage_pct !== undefined) {
        parts.push(`${meta.intent_coverage_pct.toFixed(0)}% of calls carried an intent`)
    }
    if (meta.advertisement_coverage_pct !== null && meta.advertisement_coverage_pct !== undefined) {
        parts.push(`advertisement data for ${meta.advertisement_coverage_pct.toFixed(0)}% of sampled sessions`)
    }
    if (meta.description_coverage_pct !== null && meta.description_coverage_pct !== undefined) {
        parts.push(`descriptions captured for ${meta.description_coverage_pct.toFixed(0)}% of tools`)
    }

    // The leading separator belongs to this component: it follows the run timestamp in the
    // status row and has to disappear along with it when there is no coverage to report.
    return <span className="text-xs text-muted">· {parts.join(' · ')}.</span>
}
