import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { type MetricsDisplayType } from '~/queries/schema/schema-general'

import { METRICS_PANELS } from '../panels/registry'
import { metricsViewerLogic } from './metricsViewerLogic'

const BASE_DISPLAY_TYPES: MetricsDisplayType[] = ['line', 'area', 'bar']
const PANEL_DISPLAY_TYPES: MetricsDisplayType[] = ['stat', 'gauge', 'bargauge', 'table']

export function MetricsDisplayTypeSelect({
    dataAttrPrefix,
    resultIsGrouped: resultIsGroupedProp,
    heatmap,
    disabledReason,
}: {
    dataAttrPrefix: string
    /** Whether the result has labels. Without it, the builder's group-bys decide. */
    resultIsGrouped?: boolean
    /** Offers the heatmap display, which saves a histogram query instead of a time series. */
    heatmap?: { eligible: boolean }
    disabledReason: string | null
}): JSX.Element {
    const { displayType, language, formula, namedClauses } = useValues(metricsViewerLogic)
    const { setDisplayType } = useActions(metricsViewerLogic)
    const dashboardPanelsEnabled = useFeatureFlag('METRICS_DASHBOARD_PANELS')

    // A formula result is ungrouped even when its input clauses group. PromQL and SQL results can have any labels.
    const resultIsGrouped =
        resultIsGroupedProp ??
        (language !== 'builder' || (!formula && namedClauses.some((clause) => clause.groupByKeys.length > 0)))
    const options = useMemo(() => {
        const types: MetricsDisplayType[] = dashboardPanelsEnabled
            ? [...BASE_DISPLAY_TYPES, ...PANEL_DISPLAY_TYPES, ...(heatmap ? (['heatmap'] as const) : [])]
            : BASE_DISPLAY_TYPES
        return types.map((value) => {
            const def = METRICS_PANELS[value]
            const reason = def.needsGroupBy
                ? !resultIsGrouped
                    ? 'Add a group-by to use this panel'
                    : undefined
                : def.needsHistogram && !heatmap?.eligible
                  ? 'Pick a single histogram metric (no formula) to use this panel'
                  : undefined
            return { value, label: def.label, disabledReason: reason }
        })
    }, [dashboardPanelsEnabled, resultIsGrouped, heatmap])

    return (
        <LemonSelect
            size="small"
            value={displayType}
            options={options}
            onChange={setDisplayType}
            data-attr={`${dataAttrPrefix}-display-type`}
            disabledReason={disabledReason}
        />
    )
}
