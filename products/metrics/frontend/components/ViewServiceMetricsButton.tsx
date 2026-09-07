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
 * "Show me this service's metrics", for Logs and Tracing to drop into a service row or a span.
 *
 * Metrics owns this gate rather than each caller, because the product is in private alpha behind a
 * flag: a link rendered without it lands on the waitlist screen instead of a chart, and callers
 * would each have to remember that.
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
