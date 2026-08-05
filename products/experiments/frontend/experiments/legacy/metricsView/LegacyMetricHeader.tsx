import { LemonTag } from '@posthog/lemon-ui'

import type { ExperimentFunnelsQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { LegacyMetricTitle } from './LegacyMetricTitle'

// Type for legacy metrics that may have optional shared metric properties
type LegacyMetricWithOptionalShared = (ExperimentTrendsQuery | ExperimentFunnelsQuery) & {
    isSharedMetric?: boolean
    sharedMetricId?: number
}

function getMetricTag(metric: LegacyMetricWithOptionalShared): string {
    if (metric.kind === NodeKind.ExperimentFunnelsQuery) {
        return 'Funnel'
    }
    return 'Trend'
}

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 *
 * Note: Legacy experiments do not support editing, duplication, or shared metrics.
 * These features were added after legacy experiment format.
 */
export const LegacyMetricHeader = ({
    displayOrder,
    metric,
    metricType,
}: {
    displayOrder?: number
    metric: LegacyMetricWithOptionalShared
    metricType: InsightType
}): JSX.Element => {
    return (
        <div className="text-xs font-semibold flex flex-col justify-between h-full">
            <div className="deprecated-space-y-1">
                <div className="flex items-start justify-between gap-2 min-w-0">
                    <div className="text-xs font-semibold flex items-start min-w-0 flex-1">
                        {displayOrder !== undefined && <span className="mr-1 flex-shrink-0">{displayOrder + 1}.</span>}
                        <div className="min-w-0 flex-1">
                            <LegacyMetricTitle metric={metric} metricType={metricType} />
                        </div>
                    </div>
                </div>
                <div className="deprecated-space-x-1">
                    <LemonTag type="muted" size="small">
                        {getMetricTag(metric)}
                    </LemonTag>
                    {metric.isSharedMetric && (
                        <LemonTag type="option" size="small">
                            Shared
                        </LemonTag>
                    )}
                </div>
            </div>
        </div>
    )
}
