import { IconGraph } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { canViewMetrics } from 'products/metrics/frontend/metricsAccess'
import { metricsUrlForService } from 'products/metrics/frontend/metricsLinks'

export interface ViewServiceMetricsButtonProps extends Pick<
    LemonButtonProps,
    'size' | 'type' | 'className' | 'noPadding' | 'data-attr'
> {
    serviceName: string | null | undefined
    /** Opens the viewer on the window the caller was looking at, rather than the metrics default. */
    dateFrom?: string | null
    dateTo?: string | null
    iconOnly?: boolean
}

/**
 * Whether a metrics link would actually reach a chart for this team.
 *
 * Exported for callers that reserve layout space for the button, so a hidden button does not leave
 * a column misaligned. `ViewServiceMetricsButton` applies the same check itself.
 */
export function useCanViewServiceMetrics(): boolean {
    const metricsEnabled = useFeatureFlag('METRICS')
    return metricsEnabled && canViewMetrics()
}

/**
 * The hook form of the pivot, for surfaces that render their own menu item rather than a
 * LemonButton (e.g. error tracking's event actions). Mirrors logs' `useViewLogsButton`: the
 * flag/RBAC gate and the URL encoding stay here so each caller doesn't rebuild them.
 */
export function useViewServiceMetricsButton({
    serviceName,
    dateFrom,
    dateTo,
}: Pick<ViewServiceMetricsButtonProps, 'serviceName' | 'dateFrom' | 'dateTo'>): {
    enabled: boolean
    to: string | undefined
    disabledReason: string | undefined
} {
    const enabled = useCanViewServiceMetrics()

    return {
        enabled,
        to: serviceName ? metricsUrlForService(serviceName, { dateFrom, dateTo }) : undefined,
        disabledReason: serviceName ? undefined : 'No service associated with this event',
    }
}

/**
 * "Show me this service's metrics", for Logs and Tracing to drop into a service row or a span.
 *
 * Metrics owns this gate rather than each caller, because the product is in alpha behind a
 * flag: a link rendered without it lands on the feature preview gate instead of a chart, and
 * callers would each have to remember that.
 */
export function ViewServiceMetricsButton({
    serviceName,
    dateFrom,
    dateTo,
    iconOnly,
    ...buttonProps
}: ViewServiceMetricsButtonProps): JSX.Element | null {
    const canViewServiceMetrics = useCanViewServiceMetrics()

    if (!serviceName || !canViewServiceMetrics) {
        return null
    }

    return (
        <LemonButton
            icon={<IconGraph />}
            to={metricsUrlForService(serviceName, { dateFrom, dateTo })}
            tooltip={iconOnly ? `Metrics for ${serviceName}` : undefined}
            {...buttonProps}
        >
            {iconOnly ? undefined : 'View metrics'}
        </LemonButton>
    )
}
